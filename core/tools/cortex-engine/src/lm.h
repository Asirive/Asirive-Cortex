// The LM side of the engine: LFM3-Omni on llama.cpp with four memory slots (sequences).
//
//   H  (seq 0)  start-of-text + system prompt + finished turns (text only)
//   V  (seq 1)  H + "user: <image>"                       the current view, ready before the ask
//   V' (seq 2)  H + "user: <image>" for the next view     built in the background, swapped in when complete
//   S  (seq 3)  V + question + answer (+ follow-ups)      the conversation about the current view
//
// LFM3 is hybrid (conv + attention): llama.cpp can copy a sequence's whole state but cannot rewind it, so slots
// are only ever copied or cleared, never truncated. An ask copies V into S (or continues S if it is about the same
// view) and only reads the question. Finished turns move into H when the next view is built, so V never goes stale
// mid-conversation. An ask preempts a background read through llama's abort callback; the half-built V' is dropped.
#pragma once
#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

struct llama_model;
struct llama_context;
struct mtmd_context;

#include "audio_in.h"

namespace ce {
struct LmImpl;

struct LmConfig {
    std::string model, mmproj, system_prompt;
    std::vector<int> cpus = {4, 5, 6, 7};
    int n_threads = 4;
    int n_ctx = 4096;
    // image tokens per decode batch during a background read. Preemption does not need small batches (llama's abort
    // callback fires inside graph compute), so the whole image goes in one batch for prefill throughput.
    int chunk = 256;
    int max_history_tokens = 1536;  // H beyond start + system; oldest turns dropped past this
    int stand_in_w = 640, stand_in_h = 360;  // image size that lays out the NPU canvas's 220 tokens
    // audio encoder threads; they run on the cores of the thread that calls AudioIn (the engine's audio thread)
    int audio_threads = 3;
};

struct AskResult {
    std::string text;
    double ttft_ms = 0, total_ms = 0;
    int n_out = 0;
    long view_frame_id = -1;
    double view_age_ms = 0;
    bool cancelled = false;
    std::string stop;  // why generation ended: "eog", "max", "cancel", "error"
    std::string error;
};

class Lm {
public:
    static std::unique_ptr<Lm> open(const LmConfig& cfg, std::string* err);
    ~Lm();
    // Builds V' from H + features ([n_tok * n_embd]) and swaps it in as V. Returns false with *err = "preempted"
    // when an ask arrived meanwhile (V unchanged), or another error.
    bool read_view(const float* features, int n_tok, long frame_id, std::string* err);
    AskResult ask(const std::string& question, int max_tokens, const std::function<void(const std::string&)>& on_token);
    // Moves finished turns into H (built in scratch slot V', swapped in when complete), so the next read_view only
    // reads the image. Background work: an ask preempts it (*err = "preempted", turns stay pending). read_view does
    // this itself when turns are still pending.
    bool commit_turns(std::string* err);
    bool has_pending_turns() const { return pending_n_ > 0; }
    // cancel() stops the running ask; the flag stays set until clear_cancel(), so a cancel that lands while the ask
    // is still queued or prefilling is not lost. The caller clears it before starting the next ask.
    void cancel() { cancel_ = true; }
    void clear_cancel() { cancel_ = false; }
    void reset_history();
    double copy_ms() const { return copy_ms_; }
    int history_tokens() const;
    double last_read_ms() const { return last_read_ms_; }

    // ---- spoken questions
    // An audio encoder over this model (call it from the audio thread; it never touches the LM context).
    std::unique_ptr<AudioIn> audio_in(std::string* err);
    int n_embd_inp() const;
    // Decodes the next rows of the utterance into S while the user talks. S is built on the current view at the first
    // rows (or continues the conversation about it), and is rebuilt from the new V with all rows so far when a new
    // view lands mid-utterance. Does not preempt a background read: it waits for it, so the speech-start view lands.
    bool voice_feed(const float* rows, int n, std::string* err);
    // Closes the spoken turn and answers it: preempts any background read, decodes rows not yet in S, generates.
    AskResult voice_answer(int max_tokens, const std::function<void(const std::string&)>& on_token);
    void voice_drop();  // forgets the utterance (S is rebuilt from V at the next question)
    // makes a running background read give way now (the speech just ended; voice_answer is about to lock)
    void preempt() { preempt_ = true; }
    bool reading() const { return reading_; }

private:
    Lm() = default;
    struct Turn {
        std::string q, a;
        std::vector<float> rows;  // a spoken question: its audio rows instead of q
    };
    bool voice_s_locked(std::string* err);  // S ready for the utterance's rows on the current view
    bool decode_turn(const Turn& t, int seq, std::string* err);
    int turn_tokens(const Turn& t) const;
    void generate(AskResult& r, int max_tokens, const std::function<void(const std::string&)>& on_token,
                  std::chrono::steady_clock::time_point t0);
    bool decode_text(const std::string& text, int seq, bool logits_last, std::string* err);
    bool rebuild_history(std::string* err);  // H from scratch: start + system + kept turns
    bool commit_locked(std::string* err);
    std::string head_text() const;
    void clear(int seq);
    void copy(int src, int dst);
    static bool abort_cb(void* self);

    LmConfig cfg_;
    LmImpl* im_ = nullptr;        // llama/mtmd objects kept out of this header
    llama_model* model_ = nullptr;
    llama_context* ctx_ = nullptr;
    mtmd_context* mctx_ = nullptr;
    std::mutex mu_;                       // one llama_context: all decodes are serialised
    std::atomic<bool> preempt_{false}, reading_{false}, cancel_{false};
    int pos_[4] = {0, 0, 0, 0};
    int pos_base_ = 0;                    // H position after start + system
    std::vector<Turn> history_;           // turns already in H
    std::vector<Turn> pending_;           // turns in S, not yet in H
    std::atomic<int> pending_n_{0};
    bool have_view_ = false, s_on_view_ = false;
    long view_frame_id_ = -1, s_frame_id_ = -1;
    std::chrono::steady_clock::time_point view_time_{};
    double copy_ms_ = 0, last_read_ms_ = 0;
    long view_gen_ = 0;                   // bumped by every new V (and reset)
    // the utterance being spoken: all its rows, how many are in S, and the view generation S was built on
    std::vector<float> v_rows_;
    int v_n_ = 0, v_in_s_ = 0;
    long v_gen_ = -1;
    bool v_active_ = false;
};

}  // namespace ce
