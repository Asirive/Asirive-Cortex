// Shared by the C API tests: the engine config on the box and an event recorder.
#pragma once
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "../include/cortex_engine.h"
#include "golden.h"

namespace api_test {

using nlohmann::json;

inline std::string config(const std::string& extra = "") {
    const char* home = std::getenv("HOME");
    return std::string("{\"model\":\"/var/lib/cortex/models/LFM3-Omni-2B-Q4_0.gguf\",") +
           "\"mmproj\":\"/var/lib/cortex/models/mmproj-LFM3-Omni-2B-Q8_0.gguf\"," +
           "\"split_dir\":\"/var/lib/cortex/bench/npu/split\"," + "\"qnn_lib_dir\":\"" + (home ? home : "") +
           "/qnn-deb/x/usr/lib/aarch64-linux-gnu\",\"speak\":false" + extra + "}";  // a later "speak" wins
}

inline double now_ms() {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count();
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
            e->all.back()["_rx_ms"] = now_ms();  // arrival, steady clock (the clock of sound events' at_ms)
        }
        e->cv.notify_all();
    }
    // waits for the first event of this type at or after index *from; advances *from past it
    bool wait(const std::string& type, json* out, size_t* from, int timeout_ms = 20000) {
        std::unique_lock<std::mutex> l(mu);
        if (out->is_null()) *out = json::object();  // a timeout leaves an empty object, so value() checks just fail
        return cv.wait_for(l, std::chrono::milliseconds(timeout_ms), [&] {
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
    std::vector<json> snapshot() {
        std::lock_guard<std::mutex> g(mu);
        return all;
    }
};

inline bool load_rgb(const std::string& stem, std::vector<uint8_t>* px, int* w, int* h) {
    std::ifstream f(golden::dir + stem + ".rgb", std::ios::binary);
    int32_t wh[2];
    if (!f.read(reinterpret_cast<char*>(wh), 8)) return false;
    *w = wh[0], *h = wh[1];
    px->resize((size_t)*w * *h * 3);
    return (bool)f.read(reinterpret_cast<char*>(px->data()), (std::streamsize)px->size());
}

// pushes stem as frame id, refreshes and returns its view event
inline bool show(void* h, Events& ev, const char* stem, long id, json* view, size_t* from) {
    std::vector<uint8_t> px;
    int w = 0, hh = 0;
    if (!load_rgb(stem, &px, &w, &hh)) return false;
    if (ce_push_frame(h, px.data(), w, hh, id) != 0) return false;
    if (ce_refresh(h) != 0) return false;
    return ev.wait("view", view, from);
}

}  // namespace api_test
