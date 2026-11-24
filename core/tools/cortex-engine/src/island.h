// One CPU attention island of the split vision encoder: out = softmax(Q Kt * scale) V per head, no mask.
// Layout in and out: [n_tok, heads, dim] row-major (the ONNX [1, n_tok, heads, dim] / [1, n_tok, heads*dim]).
// ggml flash attention with F16 K/V and F32 accumulation, on its own pinned threadpool; buffers reused.
#pragma once
#include <vector>

struct ggml_context;
struct ggml_cgraph;
struct ggml_tensor;
struct ggml_threadpool;

namespace ce {

class Island {
public:
    // small_cpus: a second threadpool (one thread per core) for run(..., small = true), used while an answer holds
    // the big cores
    Island(int n_tok, int heads, int dim, float scale, const std::vector<int>& cpus, int n_threads,
           const std::vector<int>& small_cpus = {});
    ~Island();
    Island(const Island&) = delete;
    Island& operator=(const Island&) = delete;
    void run(const float* q, const float* k, const float* v, float* out, bool small = false);
    bool has_small() const { return small_tp_ != nullptr; }
    double last_ms() const { return last_ms_; }
    size_t numel() const { return (size_t)n_tok_ * heads_ * dim_; }

private:
    int n_tok_, heads_, dim_, n_threads_;
    ggml_context* ctx_ = nullptr;
    ggml_cgraph* gf_ = nullptr;
    ggml_tensor *q_ = nullptr, *k_ = nullptr, *v_ = nullptr, *out_ = nullptr;
    ggml_tensor *qp_ = nullptr, *kp_ = nullptr, *vp_ = nullptr;  // permute views of q_, k_, v_
    ggml_threadpool* tp_ = nullptr;
    ggml_threadpool* small_tp_ = nullptr;
    int n_small_ = 0;
    std::vector<unsigned char> work_;
    double last_ms_ = 0;
};

}  // namespace ce
