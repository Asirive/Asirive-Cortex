// The big cores (cpu4-7) are shared by the LM and the vision islands. An answer holds them from the ask to its end;
// an island that comes while an answer runs (or waits) does not wait for it: it runs on the small cores instead, so
// the view keeps moving while Cortex speaks. An ask waits only for an island already running on the big cores.
#pragma once
#include <condition_variable>
#include <mutex>

namespace ce {

struct BigCores {
    std::mutex m;
    std::condition_variable cv;
    bool ask = false, island = false;
    // true: the big cores are the island's until island_exit(true). false: an answer holds them, run small now.
    bool island_enter() {
        std::lock_guard<std::mutex> g(m);
        if (ask) return false;
        island = true;
        return true;
    }
    void island_exit(bool big) {
        if (!big) return;
        {
            std::lock_guard<std::mutex> g(m);
            island = false;
        }
        cv.notify_all();
    }
    void ask_enter() {
        std::unique_lock<std::mutex> l(m);
        ask = true;
        cv.wait(l, [&] { return !island; });
    }
    void ask_exit() {
        {
            std::lock_guard<std::mutex> g(m);
            ask = false;
        }
        cv.notify_all();
    }
};

}  // namespace ce
