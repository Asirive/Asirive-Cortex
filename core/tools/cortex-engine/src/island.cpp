#include "island.h"

#include <chrono>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>

#include "ggml-cpu.h"
#include "ggml.h"

namespace ce {

Island::Island(int n_tok, int heads, int dim, float scale, const std::vector<int>& cpus, int n_threads)
    : n_tok_(n_tok), heads_(heads), dim_(dim), n_threads_(n_threads) {
    const size_t n = numel();
    ggml_init_params ip{};
    ip.mem_size = n * (4 * 3 + 4 + 2 * 2 + 4) + 64 * ggml_tensor_overhead() + ggml_graph_overhead() + (1 << 20);
    ip.no_alloc = false;
    ctx_ = ggml_init(ip);
    if (!ctx_) throw std::runtime_error("island: ggml_init failed");
    // ggml dims are fastest-first: [dim, heads, tok]; flash attention wants [dim, tok, heads].
    q_ = ggml_new_tensor_3d(ctx_, GGML_TYPE_F32, dim, heads, n_tok);
    k_ = ggml_new_tensor_3d(ctx_, GGML_TYPE_F32, dim, heads, n_tok);
    v_ = ggml_new_tensor_3d(ctx_, GGML_TYPE_F32, dim, heads, n_tok);
    // Flash attention with F16 K/V beat ggml mul_mat + soft_max in F32 (40.5 ms) and F16 (100 ms) on cpu4-7
    // (2026-11-24), at the same accuracy (cosine 1.000000 vs ONNX).
    ggml_tensor* q = ggml_cont(ctx_, ggml_permute(ctx_, q_, 0, 2, 1, 3));                  // [dim, tok, heads]
    ggml_tensor* k = ggml_cast(ctx_, ggml_permute(ctx_, k_, 0, 2, 1, 3), GGML_TYPE_F16);
    ggml_tensor* v = ggml_cast(ctx_, ggml_permute(ctx_, v_, 0, 2, 1, 3), GGML_TYPE_F16);
    ggml_tensor* fa = ggml_flash_attn_ext(ctx_, q, k, v, nullptr, scale, 0.0f, 0.0f);
    ggml_prec_set_acc(fa, GGML_PREC_F32);
    out_ = fa;  // result is [dim, heads, tok] contiguous = [tok, heads*dim] row-major
    gf_ = ggml_new_graph(ctx_);
    ggml_build_forward_expand(gf_, out_);

    ggml_threadpool_params tpp = ggml_threadpool_params_default(n_threads);
    for (int c : cpus)
        if (c >= 0 && c < GGML_MAX_N_THREADS) tpp.cpumask[c] = true;
    tpp.strict_cpu = !cpus.empty();
    tp_ = ggml_threadpool_new(&tpp);
    if (!tp_) throw std::runtime_error("island: threadpool failed");
    ggml_cplan plan = ggml_graph_plan(gf_, n_threads, tp_);
    work_.resize(plan.work_size);
}

Island::~Island() {
    if (tp_) ggml_threadpool_free(tp_);
    if (ctx_) ggml_free(ctx_);
}

void Island::run(const float* q, const float* k, const float* v, float* out) {
    const auto t0 = std::chrono::steady_clock::now();
    const size_t bytes = numel() * sizeof(float);
    std::memcpy(q_->data, q, bytes);
    std::memcpy(k_->data, k, bytes);
    std::memcpy(v_->data, v, bytes);
    ggml_cplan plan = ggml_graph_plan(gf_, n_threads_, tp_);
    if (plan.work_size > work_.size()) work_.resize(plan.work_size);
    plan.work_data = work_.data();
    if (ggml_graph_compute(gf_, &plan) != GGML_STATUS_SUCCESS) throw std::runtime_error("island: compute failed");
    std::memcpy(out, out_->data, bytes);
    last_ms_ = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}

}  // namespace ce
