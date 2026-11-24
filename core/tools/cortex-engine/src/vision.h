// LFM3-Omni vision encoder: 7 NPU segments (QNN HTP, w8a16) + 6 ggml attention islands, the C++ port of
// cortex_core/npu/split_encoder.py. The NPU is opened once per process; a second open is refused (a quick
// close + reopen reset the box through a fastrpc unmap error, 2026-11-24).
#pragma once
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace ce {

class Vision {
public:
    static std::unique_ptr<Vision> open(const std::string& split_dir, const std::string& qnn_lib_dir,
                                        const std::vector<int>& island_cpus, int island_threads, std::string* err);
    // The process's one encoder: opened on first call (on the calling thread, which ggml pins to an island core),
    // then reused and never closed. Engines use this, so several engines in one process share the NPU.
    static std::shared_ptr<Vision> shared(const std::string& split_dir, const std::string& qnn_lib_dir,
                                          const std::vector<int>& island_cpus, int island_threads, std::string* err);
    ~Vision();
    // Called around each CPU island so a scheduler can give the big cores to an ask first.
    void set_island_gate(std::function<void()> enter, std::function<void()> exit) {
        gate_enter_ = std::move(enter), gate_exit_ = std::move(exit);
    }
    // pixel_values: vision_prep layout [11, 20, 2, 2, 1536] float32. features: [n_tokens * n_embd].
    bool encode(const float* pixel_values, std::vector<float>* features, std::string* err);
    int n_tokens() const { return n_tokens_; }
    int n_embd() const { return n_embd_; }
    size_t pixel_count() const { return pixel_count_; }
    const std::map<std::string, double>& last_ms() const { return last_ms_; }

    struct Stage;

private:
    Vision() = default;
    std::vector<std::unique_ptr<Stage>> stages_;
    std::map<std::string, std::vector<float>> env_;
    std::map<std::string, double> last_ms_;
    std::function<void()> gate_enter_, gate_exit_;
    int n_tokens_ = 0, n_embd_ = 0;
    size_t pixel_count_ = 0;
};

}  // namespace ce
