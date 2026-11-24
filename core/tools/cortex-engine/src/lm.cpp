#include "lm.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <mutex>

#include "ggml-cpu.h"
#include "llama.h"
#include "mtmd-helper.h"
#include "mtmd.h"
#include "speech.h"

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
    std::unique_ptr<Speech> speech;  // speak mode: the MIXED loop
    std::unique_ptr<Codec> codec;    // speak mode with the codec inline
    std::vector<float> pcm;
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

// embedding rows ([n * n_embd], e.g. audio) at the next positions of seq; 0 ok, 2 aborted
static int decode_rows(llama_context* ctx, const float* rows, int n, int n_embd, int seq, int* pos) {
    if (n <= 0) return 0;
    const int cap = std::min(n, kBatch);
    llama_batch b = llama_batch_init(cap, n_embd, 1);
    int rc = 0;
    for (int i = 0; i < n && rc == 0; i += cap) {
        const int m = std::min(n - i, cap);
        b.n_tokens = m;
        std::memcpy(b.embd, rows + (size_t)i * n_embd, (size_t)m * n_embd * sizeof(float));
        for (int j = 0; j < m; j++) {
            b.pos[j] = *pos + j;
            b.n_seq_id[j] = 1;
            b.seq_id[j][0] = seq;
            b.logits[j] = false;
        }
        rc = llama_decode(ctx, b);
        if (rc == 0) *pos += m;
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
    if (cfg.speak) {  // LFM3-Omni picks its voice from the system prompt
        std::string& sp = lm->cfg_.system_prompt;
        sp += (sp.empty() ? "" : "\n") + std::string("Speak using a ") + cfg.voice + " voice.";
    }
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
    mcp.warmup = false;  // the NPU encodes images; mtmd lays out the prompt and runs the audio encoder
    mcp.n_threads = cfg.audio_threads;
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

    // Greedy, text only. LFM3-Omni can answer in speech: <|mixed_start|> opens interleaved text + audio blocks and
    // <|audio_start|> audio alone (after a spoken question it often picks mixed, then ends the turn after one short
    // text block). Speech output is not ours to make here, so both are banned, as in llama.cpp's own text mode.
    im->smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    {
        std::vector<llama_logit_bias> ban;
        for (const char* s : {"<|audio_start|>", "<|mixed_start|>"}) {
            const auto t = tokenize(lm->model_, s);
            if (t.size() == 1) ban.push_back({t[0], -INFINITY});
        }
        if (!ban.empty())
            llama_sampler_chain_add(im->smpl, llama_sampler_init_logit_bias(
                                                  llama_vocab_n_tokens(llama_model_get_vocab(lm->model_)),
                                                  (int32_t)ban.size(), ban.data()));
        llama_sampler_chain_add(im->smpl, llama_sampler_init_greedy());
    }
    im->one = llama_batch_init(1, 0, 1);
    std::string e;
    if (cfg.speak) {
        im->speech = Speech::open(lm->ctx_, lm->mctx_, &e);
        if (!im->speech) return fail("speech: " + e);
        if (cfg.codec_inline) {
            im->codec = Codec::open(lm->mctx_, &e);
            if (!im->codec) return fail("codec: " + e);
        }
    }
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

int Lm::turn_tokens(const Turn& t) const {
    if (t.rows.empty()) return (int)tokenize(model_, turn_text(t.q, t.a)).size();
    return (int)(tokenize(model_, kUser).size() + t.rows.size() / n_embd_inp() +
                 tokenize(model_, std::string(kEnd) + t.a + kTurnEnd).size());
}

// a finished turn in H: text, or a spoken question kept as its audio rows (no transcript is made)
bool Lm::decode_turn(const Turn& t, int seq, std::string* err) {
    if (t.rows.empty()) return decode_text(turn_text(t.q, t.a), seq, false, err);
    if (!decode_text(kUser, seq, false, err)) return false;
    const int rc = decode_rows(ctx_, t.rows.data(), (int)(t.rows.size() / n_embd_inp()), n_embd_inp(), seq, &pos_[seq]);
    if (rc != 0) {
        if (err) *err = rc == 2 ? "preempted" : "audio rows decode failed (" + std::to_string(rc) + ")";
        return false;
    }
    return decode_text(std::string(kEnd) + t.a + kTurnEnd, seq, false, err);
}

std::string Lm::head_text() const {
    std::string head = kStart;
    if (!cfg_.system_prompt.empty()) head += "<|im_start|>system\n" + cfg_.system_prompt + kTurnEnd;
    return head;
}

bool Lm::commit_turns(std::string* err) {
    std::lock_guard<std::mutex> g(mu_);
    reading_ = true;
    struct Done {
        Lm* lm;
        ~Done() { lm->reading_ = false; }
    } done{this};
    if (preempt_) {
        if (err) *err = "preempted";
        return false;
    }
    return commit_locked(err);
}

// H + pending turns, built in slot 2 and swapped into H only when complete (a slot cannot be rewound, so a
// preempted build is simply dropped and the turns stay pending).
bool Lm::commit_locked(std::string* err) {
    if (pending_.empty()) return true;
    std::vector<Turn> hist = history_;
    hist.insert(hist.end(), pending_.begin(), pending_.end());
    int total = 0;
    std::vector<int> sizes;
    for (auto& t : hist) {
        sizes.push_back(turn_tokens(t));
        total += sizes.back();
    }
    size_t drop = 0;
    while (drop < hist.size() && total > cfg_.max_history_tokens) total -= sizes[drop++];
    hist.erase(hist.begin(), hist.begin() + (long)drop);
    im_->abortable = true;
    bool ok;
    if (drop > 0) {  // the oldest turns go: read H again from the start
        clear(2);
        ok = decode_text(head_text(), 2, false, err);
        for (size_t i = 0; ok && i < hist.size(); i++) ok = decode_turn(hist[i], 2, err);
    } else {  // H already holds the older turns; read only the new ones
        copy(0, 2);
        ok = true;
        for (size_t i = history_.size(); ok && i < hist.size(); i++) ok = decode_turn(hist[i], 2, err);
    }
    im_->abortable = false;
    if (!ok) {
        clear(2);
        if (err && preempt_) *err = "preempted";
        return false;
    }
    copy(2, 0);
    clear(2);
    history_ = std::move(hist);
    pending_.clear();
    pending_n_ = 0;
    return true;
}

bool Lm::rebuild_history(std::string* err) {
    clear(0);
    if (!decode_text(head_text(), 0, false, err)) return false;
    pos_base_ = pos_[0];
    for (const auto& t : history_)
        if (!decode_turn(t, 0, err)) return false;
    return true;
}

int Lm::history_tokens() const { return pos_[0] - pos_base_; }

void Lm::reset_history() {
    std::lock_guard<std::mutex> g(mu_);
    history_.clear();
    pending_.clear();
    pending_n_ = 0;
    std::string e;
    rebuild_history(&e);
    clear(1);
    clear(3);
    have_view_ = s_on_view_ = false;
    view_frame_id_ = -1;
    view_gen_++;
    v_rows_.clear();
    v_n_ = v_in_s_ = 0;
    v_active_ = false;
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
    // finished turns join H (text only), oldest dropped past the budget; normally already done by commit_turns
    if (preempt_ || !commit_locked(err)) {
        if (err && preempt_) *err = "preempted";
        return false;
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
    view_gen_++;         // an utterance in progress moves onto it (voice_s_locked)
    view_frame_id_ = frame_id;
    view_time_ = clk::now();
    last_read_ms_ = ms_since(t0);
    return true;
}

AskResult Lm::ask(const std::string& question, int max_tokens, const std::function<void(const std::string&)>& on_token) {
    const auto t0 = clk::now();
    // Always raise the flag before taking the lock: a background read or commit that wins the lock now sees it and
    // gives way at once (checking reading_ first left a window where the ask waited a whole read).
    preempt_ = true;
    std::lock_guard<std::mutex> g(mu_);
    preempt_ = false;
    AskResult r;
    std::string text;
    if (v_active_) {  // a typed question over an unfinished utterance: S holds half a turn
        s_on_view_ = v_active_ = false;
        v_rows_.clear();
        v_n_ = v_in_s_ = 0;
    }
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
    generate(r, max_tokens, on_token, t0);
    pending_.push_back({question, r.text, {}});
    pending_n_ = (int)pending_.size();
    return r;
}

// samples the answer greedily into S (seq 3) from the logits of the last decode
void Lm::generate(AskResult& r, int max_tokens, const std::function<void(const std::string&)>& on_token,
                  std::chrono::steady_clock::time_point t0) {
    if (im_->speech) return generate_speech(r, max_tokens, on_token, t0);
    LmImpl* im = im_;
    const llama_vocab* vocab = llama_model_get_vocab(model_);
    llama_sampler_reset(im->smpl);
    r.stop = "max";
    for (; r.n_out < max_tokens; r.n_out++) {
        if (cancel_) {
            r.cancelled = true;
            r.stop = "cancel";
            break;
        }
        const llama_token tok = llama_sampler_sample(im->smpl, ctx_, -1);
        if (r.n_out == 0) r.ttft_ms = ms_since(t0);
        if (llama_vocab_is_eog(vocab, tok)) {
            r.stop = "eog";
            break;
        }
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
            r.stop = "error";
            s_on_view_ = false;
            break;
        }
        pos_[3]++;
    }
    r.total_ms = ms_since(t0);
}

// The answer in Cortex's voice: the MIXED loop on S after "assistant\n" (already decoded). Each frame's codes go to
// the inline codec (sound out through on_pcm) or to the engine's codec thread (on_codes). One end per answer, also
// after a cut or an error, so the speaker always closes the answer.
void Lm::generate_speech(AskResult& r, int max_tokens, const std::function<void(const std::string&)>& on_token,
                         std::chrono::steady_clock::time_point t0) {
    LmImpl* im = im_;
    Codec* codec = im->codec.get();
    if (codec) codec->reset();
    bool first = true;
    double codec_total = 0;
    auto mark_first = [&] {
        if (first) r.ttft_ms = ms_since(t0), first = false;
    };
    auto emit = [&](bool end) {
        if (cfg_.on_pcm && (!im->pcm.empty() || end)) cfg_.on_pcm(im->pcm.data(), (int)im->pcm.size(), end);
        im->pcm.clear();
    };
    SpeakIo io;
    io.on_token = [&](const std::string& piece) {
        mark_first();
        r.text += piece;
        if (on_token) on_token(piece);
    };
    io.on_frame = [&](const int32_t* codes) {
        mark_first();
        if (codec) {
            if (!codec->decode(codes, &im->pcm)) return;
            codec_total += codec->last_ms();
            emit(false);
        }
        if (cfg_.on_codes) cfg_.on_codes(codes, 0);
    };
    io.on_flush = [&] {
        if (codec) {
            codec->flush(&im->pcm);
            emit(false);
        }
        if (cfg_.on_codes) cfg_.on_codes(nullptr, 1);
    };
    io.cancelled = [this] { return cancel_.load(); };
    const int max_frames = std::max(1, cfg_.max_speech_s * 1000 / 80);
    SpeakResult s = im->speech->run(3, &pos_[3], "", max_tokens, max_frames, cfg_.seed, io);
    if (s.stop != "cancel" && codec) codec->flush(&im->pcm);  // the last frame's tail; a cut drops it
    emit(true);
    if (cfg_.on_codes) cfg_.on_codes(nullptr, 2);
    // the loop decoded into S itself: take its position from the memory, whatever happened
    pos_[3] = llama_memory_seq_pos_max(llama_get_memory(ctx_), 3) + 1;
    r.stop = s.stop;
    r.cancelled = s.stop == "cancel";
    if (s.stop == "error") {
        r.error = s.error;
        s_on_view_ = false;
    }
    r.n_out = s.n_text;
    r.frames = s.frames;
    r.frame_ms = s.frame_ms;
    r.codec_ms = s.frames && codec ? codec_total / s.frames : 0;
    r.sound_ms = s.frames * 80.0;
    r.total_ms = ms_since(t0);
}

// ---------------------------------------------------------------- spoken questions

std::unique_ptr<AudioIn> Lm::audio_in(std::string* err) {
    if (!mtmd_support_audio_stream(mctx_)) {
        if (err) *err = "this mmproj has no streaming audio encoder";
        return nullptr;
    }
    return std::unique_ptr<AudioIn>(new AudioIn(mctx_, n_embd_inp()));
}

int Lm::n_embd_inp() const { return llama_model_n_embd_inp(model_); }

// S ready to take the utterance's rows: the first rows open a turn on the current view (or continue the
// conversation about it); a view that landed since the utterance began restarts S from it, rows to come again.
bool Lm::voice_s_locked(std::string* err) {
    if (v_active_ && v_gen_ == view_gen_) return true;
    std::string pre;
    if (!v_active_ && s_on_view_) {
        pre = std::string(kTurnEnd) + kUser;  // follow-up on the same view
    } else {
        copy(have_view_ ? 1 : 0, 3);
        pre = have_view_ ? "\n" : kUser;
        s_on_view_ = true;
        s_frame_id_ = have_view_ ? view_frame_id_ : -1;
    }
    v_in_s_ = 0;
    if (!decode_text(pre, 3, false, err)) {
        s_on_view_ = v_active_ = false;
        return false;
    }
    v_active_ = true;
    v_gen_ = view_gen_;
    return true;
}

bool Lm::voice_feed(const float* rows, int n, std::string* err) {
    std::lock_guard<std::mutex> g(mu_);
    v_rows_.insert(v_rows_.end(), rows, rows + (size_t)n * n_embd_inp());
    v_n_ += n;
    if (!voice_s_locked(err)) return false;
    const int rc = decode_rows(ctx_, v_rows_.data() + (size_t)v_in_s_ * n_embd_inp(), v_n_ - v_in_s_, n_embd_inp(), 3,
                               &pos_[3]);
    if (rc != 0) {
        if (err) *err = "audio rows decode failed (" + std::to_string(rc) + ")";
        s_on_view_ = v_active_ = false;
        return false;
    }
    v_in_s_ = v_n_;
    return true;
}

AskResult Lm::voice_answer(int max_tokens, const std::function<void(const std::string&)>& on_token) {
    const auto t0 = clk::now();
    preempt_ = true;  // as ask(): a background read gives way at once
    std::lock_guard<std::mutex> g(mu_);
    preempt_ = false;
    AskResult r;
    struct Reset {
        Lm* lm;
        ~Reset() {
            lm->v_rows_.clear();
            lm->v_n_ = lm->v_in_s_ = 0;
            lm->v_active_ = false;
        }
    } reset{this};
    if (v_n_ == 0) {
        r.error = "no speech";
        return r;
    }
    if (!voice_s_locked(&r.error)) return r;
    if (v_in_s_ < v_n_) {
        const int rc = decode_rows(ctx_, v_rows_.data() + (size_t)v_in_s_ * n_embd_inp(), v_n_ - v_in_s_,
                                   n_embd_inp(), 3, &pos_[3]);
        if (rc != 0) {
            r.error = "audio rows decode failed (" + std::to_string(rc) + ")";
            s_on_view_ = false;
            return r;
        }
        v_in_s_ = v_n_;
    }
    r.view_frame_id = s_frame_id_;
    if (s_frame_id_ >= 0) r.view_age_ms = std::chrono::duration<double, std::milli>(t0 - view_time_).count();
    if (!decode_text(kEnd, 3, true, &r.error)) {
        s_on_view_ = false;
        return r;
    }
    generate(r, max_tokens, on_token, t0);
    pending_.push_back({std::string(), r.text, std::move(v_rows_)});
    pending_n_ = (int)pending_.size();
    return r;
}

void Lm::voice_drop() {
    std::lock_guard<std::mutex> g(mu_);
    if (v_active_) s_on_view_ = false;  // S holds half a turn: the next question starts again from V
    v_rows_.clear();
    v_n_ = v_in_s_ = 0;
    v_active_ = false;
}

}  // namespace ce
