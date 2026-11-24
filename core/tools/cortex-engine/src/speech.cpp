#include "speech.h"

#include <pthread.h>
#include <sched.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <mutex>
#include <thread>

#include "llama.h"
#include "mtmd.h"

namespace ce {
namespace {

using clk = std::chrono::steady_clock;
double ms_since(clk::time_point t) { return std::chrono::duration<double, std::milli>(clk::now() - t).count(); }

constexpr int kSchedule[] = {4, 4, 4};  // codebooks revealed per depthformer pass
constexpr int kTextBlock = 6, kAudioBlock = 12;

int special_token(const llama_vocab* v, const char* s) {
    llama_token t[4];
    const int n = llama_tokenize(v, s, (int32_t)std::strlen(s), t, 4, false, true);
    return n == 1 ? t[0] : -1;
}

std::vector<llama_token> tokenize(const llama_vocab* v, const std::string& s) {
    int n = -llama_tokenize(v, s.c_str(), (int32_t)s.size(), nullptr, 0, false, true);
    std::vector<llama_token> t(std::max(n, 0));
    if (n > 0) llama_tokenize(v, s.c_str(), (int32_t)s.size(), t.data(), n, false, true);
    return t;
}

}  // namespace

// ---------------------------------------------------------------- codec

std::unique_ptr<Codec> Codec::open(mtmd_context* ctx, std::string* err) {
    std::unique_ptr<Codec> c(new Codec());
    c->ctx_ = ctx;
    mtmd_gen_state_params p = mtmd_gen_state_params_default();
    c->st_ = mtmd_gen_state_init(ctx, p);
    if (!c->st_) {
        if (err) *err = "this mmproj cannot generate audio";
        return nullptr;
    }
    return c;
}

Codec::~Codec() {
    if (st_) mtmd_gen_state_free(st_);
}

bool Codec::decode(const int32_t* codes, std::vector<float>* pcm) {
    const auto t = clk::now();
    mtmd_gen_inp inp = mtmd_gen_inp_default(ctx_);
    inp.type = MTMD_GEN_PROCESS_TYPE_GEN_WAV;
    inp.codes = const_cast<int32_t*>(codes);
    inp.n_codes = codes ? kCodebooks : 0;
    mtmd_gen_out out{};
    if (mtmd_gen_audio_process(ctx_, st_, &inp, &out) != 0) return false;
    pcm->insert(pcm->end(), out.audio, out.audio + out.n_samples);
    pending_tail_ = codes != nullptr;
    last_ms_ = ms_since(t);
    return true;
}

bool Codec::flush(std::vector<float>* pcm) {
    if (!pending_tail_) return true;
    const bool ok = decode(nullptr, pcm);
    pending_tail_ = false;
    return ok;
}

void Codec::reset() {
    mtmd_gen_state_reset(st_);
    pending_tail_ = false;
}

// ---------------------------------------------------------------- codec thread

struct CodecThread::Impl {
    enum Kind { FRAME, FLUSH, END, CLEAR };
    struct Item {
        Kind kind;
        std::array<int32_t, kCodebooks> codes;
        long id;
    };
    std::function<void(const float*, int, bool)> on_pcm;
    std::mutex mu;
    std::condition_variable cv, done_cv;
    std::deque<Item> q;
    bool stop = false, opened = false;
    std::string open_err;
    long clear_req = 0, clear_done = 0;
    double total_ms = 0;  // this answer
    int n = 0;
    bool fresh = true;  // the next frame starts an answer
    std::thread th;

    void run(const std::string& mmproj, const llama_model* model, const std::vector<int>& cpus, int n_threads);
};

void CodecThread::Impl::run(const std::string& mmproj, const llama_model* model, const std::vector<int>& cpus,
                            int n_threads) {
    if (!cpus.empty()) {  // before the context exists: ggml's compute threads start from here and inherit the cores
        cpu_set_t set;
        CPU_ZERO(&set);
        for (int c : cpus) CPU_SET(c, &set);
        pthread_setaffinity_np(pthread_self(), sizeof set, &set);
    }
    mtmd_context_params mcp = mtmd_context_params_default();
    mcp.use_gpu = false, mcp.print_timings = false, mcp.warmup = false, mcp.n_threads = n_threads;
    mtmd_context* ctx = mtmd_init_from_file(mmproj.c_str(), model, mcp);
    std::string err = ctx ? "" : "cannot load mmproj " + mmproj;
    std::unique_ptr<Codec> codec = ctx ? Codec::open(ctx, &err) : nullptr;
    {
        std::lock_guard<std::mutex> g(mu);
        opened = true;
        open_err = codec ? "" : err;
        if (!codec) stop = true;
    }
    done_cv.notify_all();
    std::vector<float> pcm;
    auto emit = [&](bool end) {
        if (!pcm.empty() || end) on_pcm(pcm.data(), (int)pcm.size(), end);
        pcm.clear();
    };
    while (codec) {
        Item it;
        {
            std::unique_lock<std::mutex> l(mu);
            cv.wait(l, [&] { return stop || !q.empty(); });
            if (stop) break;
            it = q.front();
            q.pop_front();
        }
        switch (it.kind) {
        case FRAME: {
            const bool ok = codec->decode(it.codes.data(), &pcm);
            {
                std::lock_guard<std::mutex> g(mu);
                if (fresh) total_ms = 0, n = 0, fresh = false;
                if (ok) total_ms += codec->last_ms(), n++;
            }
            emit(false);
            break;
        }
        case FLUSH:
            codec->flush(&pcm);
            emit(false);
            break;
        case END:
            codec->flush(&pcm);
            emit(true);
            codec->reset();
            {
                std::lock_guard<std::mutex> g(mu);
                fresh = true;
            }
            break;
        case CLEAR:
            pcm.clear();
            codec->reset();
            on_pcm(nullptr, 0, true);
            {
                std::lock_guard<std::mutex> g(mu);
                fresh = true;
                clear_done = it.id;
            }
            done_cv.notify_all();
            break;
        }
    }
    codec.reset();
    if (ctx) mtmd_free(ctx);
}

std::unique_ptr<CodecThread> CodecThread::open(const std::string& mmproj, const llama_model* model,
                                               const std::vector<int>& cpus, int n_threads,
                                               std::function<void(const float*, int, bool)> on_pcm,
                                               std::string* err) {
    std::unique_ptr<CodecThread> t(new CodecThread());
    t->im_.reset(new Impl());
    Impl* im = t->im_.get();
    im->on_pcm = on_pcm ? std::move(on_pcm) : [](const float*, int, bool) {};
    im->th = std::thread([im, mmproj, model, cpus, n_threads] { im->run(mmproj, model, cpus, n_threads); });
    std::unique_lock<std::mutex> l(im->mu);
    im->done_cv.wait(l, [&] { return im->opened; });
    if (!im->open_err.empty()) {
        if (err) *err = im->open_err;
        l.unlock();
        return nullptr;  // the destructor joins the finished thread
    }
    return t;
}

CodecThread::~CodecThread() {
    if (!im_) return;
    {
        std::lock_guard<std::mutex> g(im_->mu);
        im_->stop = true;
    }
    im_->cv.notify_all();
    if (im_->th.joinable()) im_->th.join();
}

void CodecThread::push(const int32_t* codes) {
    Impl::Item it{Impl::FRAME, {}, 0};
    std::copy(codes, codes + kCodebooks, it.codes.begin());
    {
        std::lock_guard<std::mutex> g(im_->mu);
        im_->q.push_back(it);
    }
    im_->cv.notify_one();
}

void CodecThread::flush() {
    {
        std::lock_guard<std::mutex> g(im_->mu);
        im_->q.push_back({Impl::FLUSH, {}, 0});
    }
    im_->cv.notify_one();
}

void CodecThread::end() {
    {
        std::lock_guard<std::mutex> g(im_->mu);
        im_->q.push_back({Impl::END, {}, 0});
    }
    im_->cv.notify_one();
}

void CodecThread::clear() {
    std::unique_lock<std::mutex> l(im_->mu);
    if (im_->stop) return;
    // only this answer's items go: an earlier answer still queued (up to its END) plays out whole
    size_t keep = 0;
    for (size_t i = 0; i < im_->q.size(); i++)
        if (im_->q[i].kind == Impl::END) keep = i + 1;
    im_->q.erase(im_->q.begin() + (long)keep, im_->q.end());
    const long id = ++im_->clear_req;
    im_->q.push_back({Impl::CLEAR, {}, id});
    im_->cv.notify_one();
    im_->done_cv.wait(l, [&] { return im_->stop || im_->clear_done >= id; });
}

double CodecThread::mean_ms() const {
    std::lock_guard<std::mutex> g(im_->mu);
    return im_->n ? im_->total_ms / im_->n : 0;
}

// ---------------------------------------------------------------- speech loop

std::unique_ptr<Speech> Speech::open(llama_context* lctx, mtmd_context* mctx, std::string* err) {
    auto fail = [&](const std::string& m) {
        if (err) *err = m;
        return std::unique_ptr<Speech>();
    };
    if (mtmd_gen_audio_get_info(mctx).type != MTMD_GEN_AUDIO_TYPE_LFM3A) return fail("the mmproj has no LFM3 speech");
    std::unique_ptr<Speech> s(new Speech());
    s->lctx_ = lctx, s->mctx_ = mctx;
    const llama_model* model = llama_get_model(lctx);
    const llama_vocab* v = llama_model_get_vocab(model);
    s->n_embd_ = llama_model_n_embd(model);
    s->tok_audio_start_ = special_token(v, "<|audio_start|>");
    s->tok_mixed_start_ = special_token(v, "<|mixed_start|>");
    s->tok_text_end_ = special_token(v, "<|text_end|>");
    s->tok_im_end_ = special_token(v, "<|im_end|>");
    if (s->tok_audio_start_ < 0 || s->tok_mixed_start_ < 0 || s->tok_text_end_ < 0 || s->tok_im_end_ < 0)
        return fail("missing LFM3 speech control tokens");
    const mtmd_gen_inp def = mtmd_gen_inp_default(mctx);
    s->temp_ = def.temp, s->top_k_ = def.top_k, s->rep_penalty_ = def.penalty_repeat, s->rep_window_ = def.penalty_last_n;
    s->greedy_ = llama_sampler_init_greedy();
    return s;
}

Speech::~Speech() {
    if (st_) mtmd_gen_state_free(st_);
    if (greedy_) llama_sampler_free(greedy_);
}

bool Speech::decode_token(int tok, int seq, int* pos) {
    llama_batch b = llama_batch_init(1, 0, 1);
    b.n_tokens = 1, b.token[0] = tok, b.pos[0] = *pos, b.n_seq_id[0] = 1, b.seq_id[0][0] = seq, b.logits[0] = true;
    const int rc = llama_decode(lctx_, b);
    llama_batch_free(b);
    if (rc == 0) ++*pos;
    return rc == 0;
}

bool Speech::decode_embd(const float* e, int seq, int* pos) {
    llama_batch b = llama_batch_init(1, n_embd_, 1);
    std::memcpy(b.embd, e, (size_t)n_embd_ * sizeof(float));
    b.n_tokens = 1, b.pos[0] = *pos, b.n_seq_id[0] = 1, b.seq_id[0][0] = seq, b.logits[0] = true;
    const int rc = llama_decode(lctx_, b);
    llama_batch_free(b);
    if (rc == 0) ++*pos;
    return rc == 0;
}

SpeakResult Speech::run(int seq, int* pos, const std::string& lead, int max_tokens, int max_frames, uint32_t seed,
                        const SpeakIo& io) {
    SpeakResult r;
    const llama_vocab* vocab = llama_model_get_vocab(llama_get_model(lctx_));
    auto fail = [&](const std::string& m) {
        r.stop = "error", r.error = m;
        llama_set_embeddings(lctx_, false);
        return r;
    };
    // fresh per answer, as the helper's set_input: the RNG stream and the depthformer state start from the seed
    if (st_) mtmd_gen_state_free(st_);
    mtmd_gen_state_params gp = mtmd_gen_state_params_default();
    gp.seed = seed;
    st_ = mtmd_gen_state_init(mctx_, gp);
    if (!st_) return fail("cannot create the depthformer state");
    rng_.seed(seed);
    hist_.clear();
    llama_sampler_reset(greedy_);
    llama_set_embeddings(lctx_, true);

    {  // lead + <|mixed_start|> in one batch, logits on the last
        auto t = tokenize(vocab, lead);
        t.push_back(tok_mixed_start_);
        llama_batch b = llama_batch_init((int)t.size(), 0, 1);
        b.n_tokens = (int)t.size();
        for (int i = 0; i < b.n_tokens; i++)
            b.token[i] = t[i], b.pos[i] = *pos + i, b.n_seq_id[i] = 1, b.seq_id[i][0] = seq,
            b.logits[i] = i + 1 == b.n_tokens;
        const int rc = llama_decode(lctx_, b);
        llama_batch_free(b);
        if (rc != 0) return fail("mixed start decode failed (" + std::to_string(rc) + ")");
        *pos += (int)t.size();
    }

    enum Mode { TEXT, AUDIO, MIXED } mode = MIXED;
    int slots_left = kTextBlock;
    bool speaking = false, text_done = false;
    double frame_total = 0;
    std::vector<int32_t> codes;
    r.stop = "eog";
    for (;;) {
        if (io.cancelled && io.cancelled()) {
            r.stop = "cancel";
            break;
        }
        const bool interleaving = mode == MIXED;
        const bool next_text = mode == TEXT || (mode == MIXED && !speaking);
        if (next_text) {
            if (r.n_text >= max_tokens) {
                r.stop = "max";
                break;
            }
            const llama_token tok = llama_sampler_sample(greedy_, lctx_, -1);
            // <|im_end|> ends the answer in any text slot, <|text_end|> outside an interleaved block too
            if (tok == tok_im_end_ || (!interleaving && tok == tok_text_end_)) break;
            if (!interleaving) {
                if (tok == tok_audio_start_) {
                    mode = AUDIO;
                } else if (tok == tok_mixed_start_) {
                    mode = MIXED, slots_left = kTextBlock, speaking = false, text_done = false;
                }
            } else if (tok == tok_text_end_) {
                text_done = true, speaking = true;
            }
            char buf[256];
            const int n = llama_token_to_piece(vocab, tok, buf, sizeof buf, 0, false);
            if (n > 0) {
                const std::string piece(buf, (size_t)n);
                r.text += piece;
                if (io.on_token) io.on_token(piece);
            }
            r.n_text++;
            if (!decode_token(tok, seq, pos)) return fail("text decode failed");
        } else {
            if (r.frames >= max_frames) {
                r.stop = "max";
                break;
            }
            const auto t = clk::now();
            const float* fb = nullptr;
            bool is_eos = false;
            if (!sample_frame(h_state_.data(), codes, &fb, &is_eos)) return fail("depthformer pass failed");
            if (is_eos) {
                if (io.on_flush) io.on_flush();  // the segment ends; the answer goes on in text
                mode = TEXT;
            } else {
                hist_.insert(hist_.end(), codes.begin(), codes.end());
                if (io.on_frame) io.on_frame(codes.data());
                r.frames++;
            }
            if (!decode_embd(fb, seq, pos)) return fail("feedback decode failed");
            if (!is_eos) frame_total += ms_since(t);
        }
        // a slot emitted while interleaving counts down the block, the switching token itself does not
        if (interleaving && !text_done && --slots_left == 0) {
            speaking = !speaking;
            slots_left = speaking ? kAudioBlock : kTextBlock;
        }
        const float* he = llama_get_embeddings_ith(lctx_, -1);
        if (!he) return fail("no hidden state (embeddings off?)");
        h_state_.assign(he, he + n_embd_);
    }
    llama_set_embeddings(lctx_, false);
    r.frame_ms = r.frames ? frame_total / r.frames : 0;
    return r;
}

// A random order of the codebooks, revealed by the schedule; fb is the feedback embedding of the codes. At the end of
// audio every code is the end code (its feedback embedding is still built: the answer continues).
bool Speech::sample_frame(const float* h_state, std::vector<int32_t>& codes, const float** fb, bool* is_eos) {
    std::vector<int> order(kCodebooks);
    for (int i = 0; i < kCodebooks; i++) order[(size_t)i] = i;
    std::shuffle(order.begin(), order.end(), rng_);

    codes.assign(kCodebooks, -1);
    mtmd_gen_inp inp = mtmd_gen_inp_default(mctx_);
    inp.type = MTMD_GEN_PROCESS_TYPE_GEN_CODE;
    inp.embd = const_cast<float*>(h_state);
    inp.codes = codes.data();
    inp.n_codes = codes.size();
    mtmd_gen_out out{};

    int k = 0;
    for (int n_pick : kSchedule) {
        if (mtmd_gen_audio_process(mctx_, st_, &inp, &out) != 0 || out.n_feats == 0 || out.n_feats % kCodebooks != 0)
            return false;
        const size_t n_vocab = out.n_feats / kCodebooks;
        logits_.assign(out.feats, out.feats + out.n_feats);
        for (int j = 0; j < n_pick; j++, k++) {
            const int i = order[(size_t)k];
            float* l = logits_.data() + (size_t)i * n_vocab;
            apply_rep_penalty(l, n_vocab, i);
            codes[(size_t)i] = sample(l, n_vocab);
        }
    }
    const int32_t eos = (int32_t)(logits_.size() / kCodebooks) - 1;
    *is_eos = std::find(codes.begin(), codes.end(), eos) != codes.end();
    if (*is_eos) codes.assign(kCodebooks, eos);
    // all codes known: only the feedback embedding
    if (mtmd_gen_audio_process(mctx_, st_, &inp, &out) != 0) return false;
    fb_.assign(out.embd, out.embd + n_embd_);
    *fb = fb_.data();
    return true;
}

// CTRL penalty over the codes codebook cb took in the last rep_window frames
void Speech::apply_rep_penalty(float* l, size_t n_vocab, int cb) const {
    if (rep_penalty_ <= 1.0f || rep_window_ <= 0) return;
    const size_t n_hist = hist_.size() / kCodebooks;
    const size_t n_win = std::min(n_hist, (size_t)rep_window_);
    std::vector<bool> seen(n_vocab, false);
    for (size_t f = n_hist - n_win; f < n_hist; f++) {
        const int32_t c = hist_[f * kCodebooks + (size_t)cb];
        if (c >= 0 && (size_t)c < n_vocab && !seen[(size_t)c]) {
            seen[(size_t)c] = true;
            l[c] = l[c] > 0.0f ? l[c] / rep_penalty_ : l[c] * rep_penalty_;
        }
    }
}

int32_t Speech::sample(const float* l, size_t n_vocab) {
    if (temp_ <= 0.0f) return (int32_t)(std::max_element(l, l + n_vocab) - l);
    // top-k keeps the codes scoring at least the k-th best, ties included
    float lmin = -INFINITY;
    if (top_k_ > 0 && (size_t)top_k_ < n_vocab) {
        std::vector<float> sorted(l, l + n_vocab);
        std::nth_element(sorted.begin(), sorted.begin() + (top_k_ - 1), sorted.end(), std::greater<float>());
        lmin = sorted[(size_t)top_k_ - 1];
    }
    const float lmax = *std::max_element(l, l + n_vocab);
    std::vector<double> prob(n_vocab);
    double sum = 0.0;
    for (size_t v = 0; v < n_vocab; v++) {
        prob[v] = l[v] < lmin ? 0.0 : std::exp((double)(l[v] - lmax) / temp_);
        sum += prob[v];
    }
    double r = std::uniform_real_distribution<double>(0.0, 1.0)(rng_) * sum;
    for (size_t v = 0; v < n_vocab; v++) {
        r -= prob[v];
        if (r <= 0.0) return (int32_t)v;
    }
    return (int32_t)n_vocab - 1;
}

}  // namespace ce
