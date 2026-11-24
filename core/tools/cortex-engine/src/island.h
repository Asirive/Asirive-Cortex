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
    Island(int n_tok, int heads, int dim, float scale, const std::vector<int>& cpus, int n_threads);
    ~Island();
    Island(const Island&) = delete;
    Island& operator=(const Island&) = delete;
    void run(const float* q, const float* k, const float* v, float* out);
    double last_ms() const { return last_ms_; }
    size_t numel() const { return (size_t)n_tok_ * heads_ * dim_; }

private:
    int n_tok_, heads_, dim_, n_threads_;
    ggml_context* ctx_ = nullptr;
    ggml_cgraph* gf_ = nullptr;
    ggml_tensor *q_ = nullptr, *k_ = nullptr, *v_ = nullptr, *out_ = nullptr;
    ggml_threadpool* tp_ = nullptr;
    std::vector<unsigned char> work_;
    double last_ms_ = 0;
};

}  // namespace ce
