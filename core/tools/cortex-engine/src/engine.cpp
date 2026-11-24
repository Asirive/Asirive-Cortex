// The engine's scheduler behind the C API.
//
//   control thread (vision_cpus)  frame -> prepare -> NPU + islands -> skip check -> Lm::read_view (background)
//   LM worker      (lm_cpus)      asks, one at a time; an ask preempts a background read (Lm) and goes ahead of the
//                                 next island (BigCores gate): priority ask > island > background read
//
// Each thread opens its own part (Vision::shared on control, Lm::open on the worker) because ggml pins the thread
// that creates or drives a threadpool to the pool's first core; the caller of ce_open is never pinned.
#include "cortex_engine.h"

#include <pthread.h>
#include <sched.h>
#include <sys/syscall.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <nlohmann/json.hpp>
#include <string>
#include <thread>
#include <vector>

#include "lm.h"
#include "prep.h"
#include "vision.h"

using nlohmann::json;

namespace ce {
namespace {

using clk = std::chrono::steady_clock;
double ms_since(clk::time_point t) { return std::chrono::duration<double, std::milli>(clk::now() - t).count(); }

thread_local std::string t_last_error;
constexpr int kCanvasW = 640, kCanvasH = 352;

struct Config {
    std::string model, mmproj, split_dir, qnn_lib_dir, system_prompt;
    std::vector<int> lm_cpus{4, 5, 6, 7}, vision_cpus{1, 2, 3}, island_cpus{4, 5, 6, 7};
    double skip_cos = 0.98;
    int max_tokens = 60, max_history_tokens = 1536;
    int fail_encode_after = 0;  // test-only fault injection: encodes after this many fail
};

Config parse_config(const char* text) {
    json j = json::parse(text ? text : "");
    Config c;
    for (const char* k : {"model", "mmproj", "split_dir", "qnn_lib_dir"})
        if (!j.contains(k) || !j[k].is_string()) throw std::runtime_error(std::string("config needs \"") + k + "\"");
    c.model = j["model"], c.mmproj = j["mmproj"], c.split_dir = j["split_dir"], c.qnn_lib_dir = j["qnn_lib_dir"];
    c.system_prompt = j.value("system_prompt", "");
    c.lm_cpus = j.value("lm_cpus", c.lm_cpus);
    c.vision_cpus = j.value("vision_cpus", c.vision_cpus);
    c.island_cpus = j.value("island_cpus", c.island_cpus);
    c.skip_cos = j.value("skip_cos", c.skip_cos);
    c.max_tokens = j.value("max_tokens", c.max_tokens);
    c.max_history_tokens = j.value("max_history_tokens", c.max_history_tokens);
    c.fail_encode_after = j.value("fail_encode_after", 0);
    for (auto* set : {&c.lm_cpus, &c.vision_cpus, &c.island_cpus}) {
        if (set->empty()) throw std::runtime_error("config: a cpu set is empty");
        for (int cpu : *set)
            if (cpu <= 0 || cpu >= CPU_SETSIZE)
                throw std::runtime_error("config: cpu " + std::to_string(cpu) + " not allowed (cpu0 is the safety core)");
    }
    return c;
}

void pin_self(const std::vector<int>& cpus) {
    cpu_set_t set;
    CPU_ZERO(&set);
    for (int c : cpus) CPU_SET(c, &set);
    pthread_setaffinity_np(pthread_self(), sizeof set, &set);
}

double mean_row_cos(const std::vector<float>& a, const std::vector<float>& b, int rows) {
    if (a.size() != b.size() || rows <= 0) return 0;
    const size_t cols = a.size() / rows;
    double sum = 0;
    for (int r = 0; r < rows; r++) {
        double ab = 0, aa = 0, bb = 0;
        for (size_t i = r * cols; i < (r + 1) * cols; i++) ab += a[i] * b[i], aa += a[i] * a[i], bb += b[i] * b[i];
        sum += aa > 0 && bb > 0 ? ab / std::sqrt(aa * bb) : 0;
    }
    return sum / rows;
}

// The big cores (cpu4-7) are shared by the LM and the vision islands. An ask holds them for its whole answer;
// islands wait while an ask is running or waiting.
struct BigCores {
    std::mutex m;
    std::condition_variable cv;
    bool ask = false, island = false;
    void island_enter() {
        std::unique_lock<std::mutex> l(m);
        cv.wait(l, [&] { return !ask; });
        island = true;
    }
    void island_exit() {
        { std::lock_guard<std::mutex> g(m); island = false; }
        cv.notify_all();
    }
    void ask_enter() {
        std::unique_lock<std::mutex> l(m);
        ask = true;
        cv.wait(l, [&] { return !island; });
    }
    void ask_exit() {
        { std::lock_guard<std::mutex> g(m); ask = false; }
        cv.notify_all();
    }
};

struct Engine {
    Config cfg;
    ce_event_cb cb = nullptr;
    void* user = nullptr;
    std::mutex emit_mu;

    std::shared_ptr<Vision> vision;
    std::unique_ptr<Lm> lm;
    BigCores big;

    std::mutex mu;  // guards everything below
    std::condition_variable cv;
    bool stop = false;
    int ready = 0;  // threads finished opening their part
    std::string open_error;
    // latest frame
    std::vector<uint8_t> frame;
    int fw = 0, fh = 0;
    long fid = -1;
    bool refresh_pending = false, commit_pending = false;
    // ask queue (one slot)
    bool ask_pending = false;
    std::string ask_text;
    int ask_max = 0;
    std::atomic<bool> asking{false};
    // view state (control thread)
    std::vector<float> last_read;  // features of the view in the LM
    int n_encodes = 0;
    std::atomic<long> view_id{-1};
    std::atomic<bool> force_read{false};

    std::thread control, worker;
    std::atomic<long> control_tid{0}, worker_tid{0};
    std::string status_buf;

    void emit(const json& j) {
        const std::string line = j.dump();
        std::lock_guard<std::mutex> g(emit_mu);
        if (cb) cb(line.c_str(), user);
    }
    void error(const std::string& what) { emit({{"type", "error"}, {"what", what}}); }

    void opened(const std::string& err) {
        std::lock_guard<std::mutex> g(mu);
        if (!err.empty() && open_error.empty()) open_error = err;
        ready++;
        cv.notify_all();
    }

    void control_main() {
        control_tid = (long)syscall(SYS_gettid);
        pin_self(cfg.vision_cpus);
        std::string err;
        vision = Vision::shared(cfg.split_dir, cfg.qnn_lib_dir, cfg.island_cpus, (int)cfg.island_cpus.size(), &err);
        if (vision) {
            if ((int)vision->pixel_count() != kCanvasW / 32 * (kCanvasH / 32) * 4 * 1536)
                err = "split encoder input does not match the 640x352 canvas", vision.reset();
            else
                vision->set_island_gate([this] { big.island_enter(); }, [this] { big.island_exit(); });
        }
        opened(vision ? "" : "vision: " + err);
        if (!vision) return;
        std::vector<float> pv(vision->pixel_count()), feat;
        for (;;) {
            std::vector<uint8_t> px;
            int w, h;
            long id;
            {
                std::unique_lock<std::mutex> l(mu);
                cv.wait(l, [&] { return stop || refresh_pending || (commit_pending && !asking && !ask_pending); });
                if (stop) return;
                if (!refresh_pending) {
                    // background: the last answer joins the history now, off the next refresh's critical path
                    commit_pending = false;
                    l.unlock();
                    std::string err;
                    if (!lm->commit_turns(&err) && err != "preempted") error("history: " + err);
                    continue;
                }
                refresh_pending = false;
                if (fid < 0) {
                    l.unlock();
                    error("refresh: no frame pushed");
                    continue;
                }
                px = frame, w = fw, h = fh, id = fid;
            }
            refresh(px, w, h, id, pv, feat);
        }
    }

    void refresh(const std::vector<uint8_t>& px, int w, int h, long id, std::vector<float>& pv, std::vector<float>& feat) {
        std::string err;
        auto t = clk::now();
        if (!prepare(px.data(), w, h, kCanvasW, kCanvasH, pv.data(), &err)) return error("prepare: " + err);
        const double prep_ms = ms_since(t);
        t = clk::now();
        bool ok = cfg.fail_encode_after > 0 && n_encodes >= cfg.fail_encode_after
                      ? (err = "injected encode failure", false)
                      : vision->encode(pv.data(), &feat, &err);
        if (!ok) return error("encode: " + err);
        n_encodes++;
        const double encode_ms = ms_since(t);
        json ev = {{"type", "view"}, {"frame_id", id}, {"prep_ms", prep_ms}, {"encode_ms", encode_ms}};
        if (force_read.exchange(false)) last_read.clear();  // the view was dropped (reset_history): read it again
        const double cos = last_read.empty() ? 0.0 : mean_row_cos(last_read, feat, vision->n_tokens());
        ev["cos"] = cos;
        if (!last_read.empty() && cos >= cfg.skip_cos) {
            ev["skipped"] = true;  // same scene: the view in the LM stays
            return emit(ev);
        }
        int preempted = 0;
        t = clk::now();
        for (;;) {
            if (lm->read_view(feat.data(), vision->n_tokens(), id, &err)) break;
            if (err != "preempted") return error("read view: " + err);
            preempted++;
            // an ask took the LM: read again once it is answered
            std::unique_lock<std::mutex> l(mu);
            cv.wait(l, [&] { return stop || (!asking && !ask_pending); });
            if (stop) return;
        }
        last_read = feat;
        view_id = id;
        ev["skipped"] = false;
        ev["read_ms"] = lm->last_read_ms();
        ev["preempted"] = preempted;
        emit(ev);
    }

    void worker_main() {
        worker_tid = (long)syscall(SYS_gettid);
        pin_self(cfg.lm_cpus);
        LmConfig lc;
        lc.model = cfg.model, lc.mmproj = cfg.mmproj, lc.system_prompt = cfg.system_prompt;
        lc.cpus = cfg.lm_cpus, lc.n_threads = (int)cfg.lm_cpus.size();
        lc.max_history_tokens = cfg.max_history_tokens;
        std::string err;
        lm = Lm::open(lc, &err);
        opened(lm ? "" : "lm: " + err);
        if (!lm) return;
        for (;;) {
            std::string text;
            int max;
            {
                std::unique_lock<std::mutex> l(mu);
                cv.wait(l, [&] { return stop || ask_pending; });
                if (stop) return;
                text = ask_text, max = ask_max;
                ask_pending = false;
            }
            big.ask_enter();
            AskResult r = lm->ask(text, max, [this](const std::string& piece) {
                emit({{"type", "token"}, {"text", piece}});
            });
            big.ask_exit();
            if (!r.error.empty()) error("ask: " + r.error);
            emit({{"type", "done"},
                  {"ttft_ms", r.ttft_ms},
                  {"total_ms", r.total_ms},
                  {"n_out", r.n_out},
                  {"view_frame_id", r.view_frame_id},
                  {"view_age_ms", r.view_age_ms},
                  {"cancelled", r.cancelled}});
            {
                std::lock_guard<std::mutex> g(mu);
                asking = false;
                commit_pending = true;
            }
            cv.notify_all();
        }
    }

    void shutdown() {
        {
            std::lock_guard<std::mutex> g(mu);
            stop = true;
        }
        if (lm) lm->cancel();
        cv.notify_all();
        if (control.joinable()) control.join();
        if (worker.joinable()) worker.join();
        if (vision) vision->set_island_gate(nullptr, nullptr);
        lm.reset();
    }
};

json thread_info(const char* name, long tid) {
    json cpus = json::array();
    cpu_set_t set;
    CPU_ZERO(&set);
    if (tid > 0 && sched_getaffinity((pid_t)tid, sizeof set, &set) == 0)
        for (int c = 0; c < CPU_SETSIZE; c++)
            if (CPU_ISSET(c, &set)) cpus.push_back(c);
    return {{"name", name}, {"tid", tid}, {"cpus", cpus}};
}

}  // namespace
}  // namespace ce

using ce::Engine;

extern "C" {

void* ce_open(const char* config_json, ce_event_cb cb, void* user) {
    auto* e = new Engine();
    try {
        e->cfg = ce::parse_config(config_json);
    } catch (const std::exception& ex) {
        ce::t_last_error = ex.what();
        delete e;
        return nullptr;
    }
    e->cb = cb, e->user = user;
    e->control = std::thread([e] { e->control_main(); });
    e->worker = std::thread([e] { e->worker_main(); });
    std::string err;
    {
        std::unique_lock<std::mutex> l(e->mu);
        e->cv.wait(l, [&] { return e->ready == 2 || !e->open_error.empty(); });
        err = e->open_error;
    }
    if (!err.empty()) {
        ce::t_last_error = err;
        e->shutdown();
        delete e;
        return nullptr;
    }
    return e;
}

const char* ce_last_error(void) { return ce::t_last_error.c_str(); }

int ce_push_frame(void* h, const uint8_t* rgb, int w, int hgt, long frame_id) {
    auto* e = static_cast<Engine*>(h);
    if (!e || !rgb || w <= 0 || hgt <= 0) return -1;
    std::lock_guard<std::mutex> g(e->mu);
    e->frame.assign(rgb, rgb + (size_t)w * hgt * 3);
    e->fw = w, e->fh = hgt, e->fid = frame_id;
    return 0;
}

int ce_refresh(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return -1;
    {
        std::lock_guard<std::mutex> g(e->mu);
        e->refresh_pending = true;
    }
    e->cv.notify_all();
    return 0;
}

int ce_ask(void* h, const char* text, int max_tokens) {
    auto* e = static_cast<Engine*>(h);
    if (!e || !text) return -1;
    {
        std::unique_lock<std::mutex> g(e->mu);
        if (e->asking) {
            g.unlock();
            e->error("busy");
            return -1;
        }
        e->asking = true;
        e->lm->clear_cancel();
        e->ask_text = text;
        e->ask_max = max_tokens > 0 ? max_tokens : e->cfg.max_tokens;
        e->ask_pending = true;
    }
    e->cv.notify_all();
    return 0;
}

int ce_cancel(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return -1;
    std::lock_guard<std::mutex> g(e->mu);
    if (e->asking) e->lm->cancel();
    return 0;
}

int ce_reset_history(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return -1;
    // The view in the LM was read on the old history and goes too; asks are text-only until the next refresh,
    // which reads the scene again even if it has not changed.
    e->force_read = true;
    e->lm->reset_history();
    e->view_id = -1;
    return 0;
}

const char* ce_status(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return "{}";
    nlohmann::json st;
    {
        std::lock_guard<std::mutex> g(e->mu);
        st["asking"] = e->asking.load();
        st["frame_id"] = e->fid;
    }
    st["view_frame_id"] = e->view_id.load();
    st["history_tokens"] = e->lm->history_tokens();
    st["threads"] = {ce::thread_info("control", e->control_tid), ce::thread_info("lm", e->worker_tid)};
    e->status_buf = st.dump();
    return e->status_buf.c_str();
}

void ce_close(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return;
    e->shutdown();
    delete e;
}

}  // extern "C"
