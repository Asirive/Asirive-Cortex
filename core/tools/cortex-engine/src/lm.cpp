#include "lm.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <mutex>

#include "ggml-cpu.h"
#include "llama.h"
#include "mtmd-helper.h"
#include "mtmd.h"

namespace ce {

namespace {
using clk = std::chrono::steady_clock;
double ms_since(clk::time_point t) { return std::chrono::duration<double, std::milli>(clk::now() - t).count(); }

const char* kStart = "<|startoftext|>";
const char* kUser = "<|im_start|>user\n";
const char* kEnd = "<|im_end|>\n<|im_start|>assistant\n";  // closes the user turn, opens the answer
const char* kTurnEnd = "<|im_end|>\n";
constexpr int kBatch = 2048;

void quiet_log(ggml_log_level level, const char* text, void*) {
    if (level >= GGML_LOG_LEVEL_ERROR) std::fputs(text, stderr);
}

std::once_flag g_backend;
}  // namespace

// llama/mtmd objects the header keeps opaque
struct LmImpl {
    ggml_threadpool* tp = nullptr;
    mtmd_input_chunks* chunks = nullptr;      // the view prompt laid out once with a grey stand-in image
    const mtmd_input_chunk* image = nullptr;
    std::vector<llama_token> pre, tail;       // text before the image, and the image's closing tokens after it
    llama_sampler* smpl = nullptr;
    llama_batch one{};
    std::atomic<bool> abortable{false};
};

static std::vector<llama_token> tokenize(const llama_model* model, const std::string& text) {
    const llama_vocab* vocab = llama_model_get_vocab(model);
    int n = -llama_tokenize(vocab, text.c_str(), (int32_t)text.size(), nullptr, 0, false, true);
    std::vector<llama_token> t(n);
    if (n > 0) llama_tokenize(vocab, text.c_str(), (int32_t)text.size(), t.data(), n, false, true);
    return t;
}

// 0 ok, 2 aborted, other llama_decode errors
static int decode_tokens(llama_context* ctx, const std::vector<llama_token>& toks, int seq, int* pos, bool logits_last) {
    if (toks.empty()) return 0;
    llama_batch b = llama_batch_init(kBatch, 0, 1);
    int rc = 0;
    for (size_t i = 0; i < toks.size() && rc == 0; i += kBatch) {
        const size_t n = std::min(toks.size() - i, (size_t)kBatch);
        b.n_tokens = (int32_t)n;
        for (size_t j = 0; j < n; j++) {
            b.token[j] = toks[i + j];
            b.pos[j] = *pos + (int)j;
            b.n_seq_id[j] = 1;
            b.seq_id[j][0] = seq;
            b.logits[j] = logits_last && i + j + 1 == toks.size();
        }
        rc = llama_decode(ctx, b);
        if (rc == 0) *pos += (int)n;
    }
    llama_batch_free(b);
    return rc;
}

bool Lm::abort_cb(void* self) {
    auto* lm = static_cast<Lm*>(self);
    return lm->im_ && lm->im_->abortable.load() && lm->preempt_.load();
}

std::unique_ptr<Lm> Lm::open(const LmConfig& cfg, std::string* err) {
    auto fail = [&](const std::string& m) {
        if (err) *err = m;
        return std::unique_ptr<Lm>();
    };
    std::call_once(g_backend, [] {
        llama_log_set(quiet_log, nullptr);
        mtmd_helper_log_set(quiet_log, nullptr);
        llama_backend_init();
    });
    std::unique_ptr<Lm> lm(new Lm());
    lm->cfg_ = cfg;
    auto* im = lm->im_ = new LmImpl();
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 0;
    lm->model_ = llama_model_load_from_file(cfg.model.c_str(), mp);
    if (!lm->model_) return fail("cannot load model " + cfg.model);
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = cfg.n_ctx;
    cp.n_batch = cp.n_ubatch = kBatch;
    cp.n_seq_max = 4;
    cp.kv_unified = true;  // slots share their common prefix cells; a copy only re-tags cells
    cp.n_threads = cp.n_threads_batch = cfg.n_threads;
    lm->ctx_ = llama_init_from_model(lm->model_, cp);
    if (!lm->ctx_) return fail("cannot create llama context");
    ggml_threadpool_params tpp = ggml_threadpool_params_default(cfg.n_threads);
    for (int c : cfg.cpus)
        if (c >= 0 && c < GGML_MAX_N_THREADS) tpp.cpumask[c] = true;
    tpp.strict_cpu = true;
    im->tp = ggml_threadpool_new(&tpp);
    if (!im->tp) return fail("cannot create LM threadpool");
    llama_attach_threadpool(lm->ctx_, im->tp, im->tp);
    llama_set_abort_callback(lm->ctx_, &Lm::abort_cb, lm.get());

    mtmd_context_params mcp = mtmd_context_params_default();
    mcp.use_gpu = false;
    mcp.print_timings = false;
    mcp.warmup = false;  // the NPU encodes; mtmd only lays out the prompt
    lm->mctx_ = mtmd_init_from_file(cfg.mmproj.c_str(), lm->model_, mcp);
    if (!lm->mctx_) return fail("cannot load mmproj " + cfg.mmproj);

    // Lay out "user: <image>\nQ" once. Everything up to the image's closing tokens is the view (V); the question
    // part is tokenised at ask time. Splitting at special tokens keeps the tokens identical to one whole prompt.
    std::vector<unsigned char> grey((size_t)cfg.stand_in_w * cfg.stand_in_h * 3, 128);
    mtmd_bitmap* bmp = mtmd_bitmap_init(cfg.stand_in_w, cfg.stand_in_h, grey.data());
    const std::string probe = "Q";
    const std::string prompt = std::string(kUser) + mtmd_get_marker(lm->mctx_) + "\n" + probe + kEnd;
    mtmd_input_text text{prompt.c_str(), prompt.size(), false, true};
    im->chunks = mtmd_input_chunks_init();
    const mtmd_bitmap* bitmaps[] = {bmp};
    const int32_t rc = mtmd_tokenize(lm->mctx_, im->chunks, &text, bitmaps, 1);
    mtmd_bitmap_free(bmp);
    if (rc != 0) return fail("cannot lay out the view prompt");
    std::vector<llama_token> post;
    for (size_t i = 0; i < mtmd_input_chunks_size(im->chunks); i++) {
        const mtmd_input_chunk* c = mtmd_input_chunks_get(im->chunks, i);
        if (mtmd_input_chunk_get_type(c) == MTMD_INPUT_CHUNK_TYPE_IMAGE) {
            if (im->image) return fail("the stand-in image splits into tiles; use a smaller stand_in size");
            im->image = c;
            continue;
        }
        size_t n = 0;
        const llama_token* t = mtmd_input_chunk_get_tokens_text(c, &n);
        (im->image ? post : im->pre).insert((im->image ? post : im->pre).end(), t, t + n);
    }
    if (!im->image) return fail("no image chunk in the view prompt");
    const auto q = tokenize(lm->model_, "\n" + probe + kEnd);
    if (post.size() < q.size() || !std::equal(q.begin(), q.end(), post.end() - q.size()))
        return fail("view prompt does not split cleanly before the question");
    im->tail.assign(post.begin(), post.end() - q.size());

    im->smpl = llama_sampler_init_greedy();
    im->one = llama_batch_init(1, 0, 1);
    std::string e;
    if (!lm->rebuild_history(&e)) return fail(e);
    return lm;
}

Lm::~Lm() {
    LmImpl* im = im_;
    if (im) {
        if (im->smpl) llama_sampler_free(im->smpl);
        if (im->one.token) llama_batch_free(im->one);
        if (im->chunks) mtmd_input_chunks_free(im->chunks);
    }
    if (mctx_) mtmd_free(mctx_);
    if (ctx_) llama_free(ctx_);
    if (model_) llama_model_free(model_);
    if (im) {
        if (im->tp) ggml_threadpool_free(im->tp);
        delete im;
    }
}

void Lm::clear(int seq) {
    llama_memory_seq_rm(llama_get_memory(ctx_), seq, -1, -1);
    pos_[seq] = 0;
}

void Lm::copy(int src, int dst) {
    const auto t = clk::now();
    clear(dst);
    llama_memory_seq_cp(llama_get_memory(ctx_), src, dst, -1, -1);
    pos_[dst] = pos_[src];
    copy_ms_ = ms_since(t);
}

bool Lm::decode_text(const std::string& text, int seq, bool logits_last, std::string* err) {
    const int rc = decode_tokens(ctx_, tokenize(model_, text), seq, &pos_[seq], logits_last);
    if (rc != 0 && err) *err = rc == 2 ? "preempted" : "llama_decode failed (" + std::to_string(rc) + ")";
    return rc == 0;
}

static std::string turn_text(const std::string& q, const std::string& a) {
    return std::string(kUser) + q + kEnd + a + kTurnEnd;
}

bool Lm::rebuild_history(std::string* err) {
    clear(0);
    std::string head = kStart;
    if (!cfg_.system_prompt.empty()) head += "<|im_start|>system\n" + cfg_.system_prompt + kTurnEnd;
    if (!decode_text(head, 0, false, err)) return false;
    pos_base_ = pos_[0];
    for (const auto& t : history_)
        if (!decode_text(turn_text(t.q, t.a), 0, false, err)) return false;
    return true;
}

int Lm::history_tokens() const { return pos_[0] - pos_base_; }

void Lm::reset_history() {
    std::lock_guard<std::mutex> g(mu_);
    history_.clear();
    pending_.clear();
    std::string e;
    rebuild_history(&e);
    clear(1);
    clear(3);
    have_view_ = s_on_view_ = false;
    view_frame_id_ = -1;
}

bool Lm::read_view(const float* features, int n_tok, long frame_id, std::string* err) {
    std::lock_guard<std::mutex> g(mu_);
    reading_ = true;
    struct Done {
        Lm* lm;
        ~Done() { lm->reading_ = false; }
    } done{this};
    const auto t0 = clk::now();
    LmImpl* im = im_;
    if (n_tok !=(int)mtmd_input_chunk_get_n_tokens(im->image)) {
        if (err) *err = "view has " + std::to_string(n_tok) + " tokens, the prompt expects " +
                        std::to_string(mtmd_input_chunk_get_n_tokens(im->image));
        return false;
    }
    // finished turns join H (text only), oldest dropped past the budget
    if (!pending_.empty()) {
        const size_t n_new = pending_.size();
        for (auto& t : pending_) history_.push_back(t);
        pending_.clear();
        int total = 0;
        std::vector<int> sizes;
        for (auto& t : history_) {
            sizes.push_back((int)tokenize(model_, turn_text(t.q, t.a)).size());
            total += sizes.back();
        }
        size_t drop = 0;
        while (drop < history_.size() && total > cfg_.max_history_tokens) total -= sizes[drop++];
        if (drop > 0) {  // the oldest turns go: H is re-read from the start (a slot cannot be cut)
            history_.erase(history_.begin(), history_.begin() + (long)drop);
            if (!rebuild_history(err)) return false;
        } else {  // H already holds the older turns; read only the new ones
            for (size_t i = history_.size() - n_new; i < history_.size(); i++)
                if (!decode_text(turn_text(history_[i].q, history_[i].a), 0, false, err)) return false;
        }
    }
    if (preempt_) {
        if (err) *err = "preempted";
        return false;
    }
    copy(0, 2);
    im->abortable = true;
    int rc = decode_tokens(ctx_, im->pre, 2, &pos_[2], false);
    if (rc == 0) {
        llama_pos np = 0;
        rc = mtmd_helper_decode_image_chunk(mctx_, ctx_, im->image, const_cast<float*>(features), pos_[2], 2,
                                            cfg_.chunk, &np, nullptr, nullptr);
        if (rc == 0) pos_[2] = np;
        else if (preempt_) rc = 2;
    }
    if (rc == 0) rc = decode_tokens(ctx_, im->tail, 2, &pos_[2], false);
    im->abortable = false;
    if (rc != 0) {
        clear(2);
        if (err) *err = rc == 2 || preempt_ ? "preempted" : "view decode failed (" + std::to_string(rc) + ")";
        return false;
    }
    copy(2, 1);
    clear(2);
    have_view_ = true;
    s_on_view_ = false;  // the next ask starts a fresh conversation about this view
    view_frame_id_ = frame_id;
    view_time_ = clk::now();
    last_read_ms_ = ms_since(t0);
    return true;
}

AskResult Lm::ask(const std::string& question, int max_tokens, const std::function<void(const std::string&)>& on_token) {
    const auto t0 = clk::now();
    if (reading_) preempt_ = true;
    std::lock_guard<std::mutex> g(mu_);
    preempt_ = false;
    LmImpl* im = im_;
    AskResult r;
    std::string text;
    if (s_on_view_) {
        text = std::string(kTurnEnd) + kUser + question + kEnd;  // follow-up: S already holds the conversation
    } else {
        copy(have_view_ ? 1 : 0, 3);
        text = (have_view_ ? "\n" : kUser) + question + kEnd;
        s_on_view_ = true;
        s_frame_id_ = have_view_ ? view_frame_id_ : -1;
    }
    r.view_frame_id = s_frame_id_;
    if (s_frame_id_ >= 0) r.view_age_ms = std::chrono::duration<double, std::milli>(t0 - view_time_).count();
    if (!decode_text(text, 3, true, &r.error)) {
        s_on_view_ = false;
        return r;
    }
    const llama_vocab* vocab = llama_model_get_vocab(model_);
    llama_sampler_reset(im->smpl);
    for (; r.n_out < max_tokens; r.n_out++) {
        if (cancel_) {
            r.cancelled = true;
            break;
        }
        const llama_token tok = llama_sampler_sample(im->smpl, ctx_, -1);
        if (r.n_out == 0) r.ttft_ms = ms_since(t0);
        if (llama_vocab_is_eog(vocab, tok)) break;
        char buf[256];
        const int n = llama_token_to_piece(vocab, tok, buf, sizeof buf, 0, false);
        if (n > 0) {
            const std::string piece(buf, (size_t)n);
            r.text += piece;
            if (on_token) on_token(piece);
        }
        im->one.n_tokens = 1;
        im->one.token[0] = tok;
        im->one.pos[0] = pos_[3];
        im->one.n_seq_id[0] = 1;
        im->one.seq_id[0][0] = 3;
        im->one.logits[0] = true;
        const int rc = llama_decode(ctx_, im->one);
        if (rc != 0) {
            r.error = "llama_decode failed while generating (" + std::to_string(rc) + ")";
            s_on_view_ = false;
            break;
        }
        pos_[3]++;
    }
    r.total_ms = ms_since(t0);
    pending_.push_back({question, r.text});
    return r;
}

}  // namespace ce
