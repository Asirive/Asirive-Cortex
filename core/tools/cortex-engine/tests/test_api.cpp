#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <nlohmann/json.hpp>

#include "../include/cortex_engine.h"
#include "check.h"
#include "golden.h"

using nlohmann::json;
using namespace std::chrono;

namespace {

std::string config(const std::string& extra = "") {
    const char* home = std::getenv("HOME");
    return std::string("{\"model\":\"/var/lib/cortex/models/LFM3-Omni-2B-Q4_0.gguf\",") +
           "\"mmproj\":\"/var/lib/cortex/models/mmproj-LFM3-Omni-2B-Q8_0.gguf\"," +
           "\"split_dir\":\"/var/lib/cortex/bench/npu/split\"," + "\"qnn_lib_dir\":\"" + (home ? home : "") +
           "/qnn-deb/x/usr/lib/aarch64-linux-gnu\"" + extra + "}";
}

struct Events {
    std::mutex mu;
    std::condition_variable cv;
    std::vector<json> all;
    static void cb(const char* line, void* user) {
        auto* e = static_cast<Events*>(user);
        {
            std::lock_guard<std::mutex> g(e->mu);
            e->all.push_back(json::parse(line));
        }
        e->cv.notify_all();
    }
    // waits for the first event of this type at or after index *from; advances *from past it
    bool wait(const std::string& type, json* out, size_t* from, int timeout_ms = 20000) {
        std::unique_lock<std::mutex> l(mu);
        return cv.wait_for(l, milliseconds(timeout_ms), [&] {
            for (size_t i = *from; i < all.size(); i++)
                if (all[i]["type"] == type) {
                    *out = all[i];
                    *from = i + 1;
                    return true;
                }
            return false;
        });
    }
    size_t count(const std::string& type, size_t from = 0) {
        std::lock_guard<std::mutex> g(mu);
        size_t n = 0;
        for (size_t i = from; i < all.size(); i++) n += all[i]["type"] == type;
        return n;
    }
    size_t size() {
        std::lock_guard<std::mutex> g(mu);
        return all.size();
    }
};

bool load_rgb(const std::string& stem, std::vector<uint8_t>* px, int* w, int* h) {
    std::ifstream f(golden::dir + stem + ".rgb", std::ios::binary);
    int32_t wh[2];
    if (!f.read(reinterpret_cast<char*>(wh), 8)) return false;
    *w = wh[0], *h = wh[1];
    px->resize((size_t)*w * *h * 3);
    return (bool)f.read(reinterpret_cast<char*>(px->data()), (std::streamsize)px->size());
}

// pushes stem as frame id, refreshes and returns its view event
bool show(void* h, Events& ev, const char* stem, long id, json* view, size_t* from) {
    std::vector<uint8_t> px;
    int w = 0, hh = 0;
    if (!load_rgb(stem, &px, &w, &hh)) return false;
    if (ce_push_frame(h, px.data(), w, hh, id) != 0) return false;
    if (ce_refresh(h) != 0) return false;
    return ev.wait("view", view, from);
}

}  // namespace

TEST(api_open_bad_config_is_error) {
    Events ev;
    void* h = ce_open("{\"model\":\"x\",\"mmproj\":\"y\",\"qnn_lib_dir\":\"z\"}", &Events::cb, &ev);
    CHECK(h == nullptr);
    CHECK(std::string(ce_last_error()).find("split_dir") != std::string::npos);
    CHECK(ce_open("not json", &Events::cb, &ev) == nullptr);
}

TEST(api_refresh_ask_skip_busy_cancel) {
    Events ev;
    void* h = ce_open(config().c_str(), &Events::cb, &ev);
    if (!h) std::printf("  open failed: %s\n", ce_last_error());
    CHECK(h != nullptr);
    if (!h) return;
    size_t at = 0;
    json view, done, err;

    // refresh_then_ask_events
    CHECK(show(h, ev, "t001", 101, &view, &at));
    std::printf("  view: %s\n", view.dump().c_str());
    CHECK(view["frame_id"] == 101 && view["skipped"] == false && view.contains("read_ms"));
    const size_t before = ev.size();
    CHECK(ce_ask(h, "What is the large toy in front of me? One sentence.", 40) == 0);
    CHECK(ev.wait("done", &done, &at));
    std::printf("  done: %s\n", done.dump().c_str());
    CHECK(ev.count("token", before) >= 1);
    CHECK(done["view_frame_id"] == 101 && done["cancelled"] == false);
    CHECK(done["ttft_ms"].get<double>() <= 400.0);

    // same_frame_is_skipped
    CHECK(show(h, ev, "t001", 102, &view, &at));
    std::printf("  view: %s\n", view.dump().c_str());
    CHECK(view["skipped"] == true && view["cos"].get<double>() >= 0.98 && !view.contains("read_ms"));

    // a different scene is read
    CHECK(show(h, ev, "t008", 108, &view, &at));
    CHECK(view["skipped"] == false && view["cos"].get<double>() < 0.98);

    // second_ask_busy_and_cancel
    const size_t mark = ev.size();
    CHECK(ce_ask(h, "Describe everything you see in great detail.", 200) == 0);
    CHECK(ce_ask(h, "Hello?", 10) == -1);
    size_t at_err = mark;
    CHECK(ev.wait("error", &err, &at_err, 1000) && err["what"] == "busy");
    std::this_thread::sleep_for(milliseconds(300));
    const auto t = steady_clock::now();
    CHECK(ce_cancel(h) == 0);
    size_t at_done = mark;
    CHECK(ev.wait("done", &done, &at_done, 2000));
    const double ms = duration<double, std::milli>(steady_clock::now() - t).count();
    std::printf("  cancel -> done in %.0f ms: %s\n", ms, done.dump().c_str());
    CHECK(done["cancelled"] == true && ms <= 100.0);
    CHECK(done["view_frame_id"] == 108);
    at = ev.size();

    // threads_stay_off_safety_cores
    json st = json::parse(ce_status(h));
    std::printf("  status: %s\n", st.dump().c_str());
    CHECK(st["threads"].size() >= 2);
    for (auto& th : st["threads"]) {
        CHECK(!th["cpus"].empty());
        for (auto& c : th["cpus"]) CHECK(c.get<int>() != 0 && c.get<int>() <= 7);
    }
    ce_close(h);
}

TEST(api_encode_failure_keeps_typed_asks) {
    Events ev;
    void* h = ce_open(config(",\"fail_encode_after\":1").c_str(), &Events::cb, &ev);
    CHECK(h != nullptr);
    if (!h) return;
    size_t at = 0;
    json view, err, done;
    CHECK(show(h, ev, "t001", 1, &view, &at));
    std::vector<uint8_t> px;
    int w = 0, hh = 0;
    CHECK(load_rgb("t008", &px, &w, &hh));
    CHECK(ce_push_frame(h, px.data(), w, hh, 8) == 0 && ce_refresh(h) == 0);
    CHECK(ev.wait("error", &err, &at));
    std::printf("  error: %s\n", err.dump().c_str());
    CHECK(ce_ask(h, "What is in front of me? One sentence.", 30) == 0);
    CHECK(ev.wait("done", &done, &at));
    CHECK(done["view_frame_id"] == 1 && done["n_out"].get<int>() >= 1);
    ce_close(h);
}
