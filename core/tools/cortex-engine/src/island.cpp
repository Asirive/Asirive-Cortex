#include "island.h"

#include <chrono>
#include <stdexcept>

#include "ggml-cpu.h"
#include "ggml.h"

namespace ce {

// Flash attention, F32 K/V: 23.5 ms on cpu4-7, exact (max abs 1e-7 vs ONNX). F16 K/V was no faster (24.8 ms);
// mul_mat + soft_max took 40.5 ms (F32) / 100 ms (F16). Measured 2026-11-24.
static const ggml_type kKvType = GGML_TYPE_F32;

static ggml_threadpool* pinned_pool(const std::vector<int>& cpus, int n_threads) {
    ggml_threadpool_params tpp = ggml_threadpool_params_default(n_threads);
    for (int c : cpus)
        if (c >= 0 && c < GGML_MAX_N_THREADS) tpp.cpumask[c] = true;
    tpp.strict_cpu = !cpus.empty();
    return ggml_threadpool_new(&tpp);
}

Island::Island(int n_tok, int heads, int dim, float scale, const std::vector<int>& cpus, int n_threads,
               const std::vector<int>& small_cpus)
    : n_tok_(n_tok), heads_(heads), dim_(dim), n_threads_(n_threads) {
    const size_t n = numel();
    ggml_init_params ip{};
    // inputs are repointed to the caller's buffers and the output is written straight into out, but the context
    // still allocates them once; plus Q cont and K/V casts
    ip.mem_size = n * (4 * 4 + 4 + 4 * 2) + 64 * ggml_tensor_overhead() + ggml_graph_overhead() + (1 << 20);
    ip.no_alloc = false;
    ctx_ = ggml_init(ip);
    if (!ctx_) throw std::runtime_error("island: ggml_init failed");
    // ggml dims are fastest-first: [dim, heads, tok]; flash attention wants [dim, tok, heads].
    q_ = ggml_new_tensor_3d(ctx_, GGML_TYPE_F32, dim, heads, n_tok);
    k_ = ggml_new_tensor_3d(ctx_, GGML_TYPE_F32, dim, heads, n_tok);
    v_ = ggml_new_tensor_3d(ctx_, GGML_TYPE_F32, dim, heads, n_tok);
    // Permute views copy their parent's data pointer when made, so run() repoints both (offset 0).
    qp_ = ggml_permute(ctx_, q_, 0, 2, 1, 3);
    kp_ = ggml_permute(ctx_, k_, 0, 2, 1, 3);
    vp_ = ggml_permute(ctx_, v_, 0, 2, 1, 3);
    ggml_tensor* q = ggml_cont(ctx_, qp_);  // [dim, tok, heads]
    ggml_tensor* k = ggml_cast(ctx_, kp_, kKvType);
    ggml_tensor* v = ggml_cast(ctx_, vp_, kKvType);
    ggml_tensor* fa = ggml_flash_attn_ext(ctx_, q, k, v, nullptr, scale, 0.0f, 0.0f);
    ggml_prec_set_acc(fa, GGML_PREC_F32);
    out_ = fa;  // result is [dim, heads, tok] contiguous = [tok, heads*dim] row-major
    gf_ = ggml_new_graph(ctx_);
    ggml_build_forward_expand(gf_, out_);

    tp_ = pinned_pool(cpus, n_threads);
    if (!tp_) throw std::runtime_error("island: threadpool failed");
    ggml_threadpool_pause(tp_);  // two pools: neither spins while the other runs
    if (!small_cpus.empty()) {
        n_small_ = (int)small_cpus.size();
        small_tp_ = pinned_pool(small_cpus, n_small_);
        if (!small_tp_) throw std::runtime_error("island: small threadpool failed");
        ggml_threadpool_pause(small_tp_);
    }
    ggml_cplan plan = ggml_graph_plan(gf_, n_threads, tp_);
    work_.resize(plan.work_size);
}

Island::~Island() {
    if (small_tp_) ggml_threadpool_free(small_tp_);
    if (tp_) ggml_threadpool_free(tp_);
    if (ctx_) ggml_free(ctx_);
}

void Island::run(const float* q, const float* k, const float* v, float* out, bool small) {
    const auto t0 = std::chrono::steady_clock::now();
    // Zero copy: the graph reads the caller's buffers and writes the result straight into out.
    q_->data = qp_->data = const_cast<float*>(q);
    k_->data = kp_->data = const_cast<float*>(k);
    v_->data = vp_->data = const_cast<float*>(v);
    out_->data = out;
    ggml_threadpool* tp = small && small_tp_ ? small_tp_ : tp_;
    ggml_cplan plan = ggml_graph_plan(gf_, tp == tp_ ? n_threads_ : n_small_, tp);
    if (plan.work_size > work_.size()) work_.resize(plan.work_size);
    plan.work_data = work_.data();
    ggml_threadpool_resume(tp);
    const ggml_status st = ggml_graph_compute(gf_, &plan);
    ggml_threadpool_pause(tp);
    if (st != GGML_STATUS_SUCCESS) throw std::runtime_error("island: compute failed");
    last_ms_ = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}

}  // namespace ce
