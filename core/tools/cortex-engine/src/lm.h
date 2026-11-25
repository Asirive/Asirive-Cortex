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
    // Tool calls: the tools as one JSON object per line ("" = none). Every answer opens with
    // "<think></think>" as in the model's template, and a first token <tool_call> makes the answer a call.
    std::string tools;
    float tool_bias = 0;                          // added to the <tool_call> logit before the decision
    std::string tts_language = "American English";  // ce_say's TTS prompt
    std::vector<int> cpus = {4, 5, 6, 7};
    int n_threads = 4;
    int n_ctx = 8192;
    // image tokens per decode batch during a background read. Preemption does not need small batches (llama's abort
    // callback fires inside graph compute), so the whole image goes in one batch for prefill throughput.
    int chunk = 256;
    int max_history_tokens = 1536;  // H beyond start + system; oldest turns dropped past this
    int stand_in_w = 640, stand_in_h = 360;  // image size that lays out the NPU canvas's 220 tokens
    // audio encoder threads; they run on the cores of the thread that calls AudioIn (the engine's audio thread)
    int audio_threads = 3;

    // ---- speech out: every answer in LFM3-Omni's own voice (interleaved text + audio)
    bool speak = false;
    std::string voice = "female";  // "Speak using a <voice> voice." joins the system prompt
    int max_speech_s = 180;        // audio frames per answer are capped at this (stop "max")
    // Codes -> PCM. Normally on its own thread and mtmd context on codec_cpus, behind the LM (one mtmd context runs
    // one graph at a time, so sharing the LM's would make the depthformer wait). Inline runs it in the LM loop.
    bool codec_inline = false;
    std::vector<int> codec_cpus = {3};
    int codec_threads = 1;
    uint32_t seed = 0;  // the depthformer's sampling seed (fixed: the same question gives the same voice)
    // 24 kHz mono, end once per answer (also after a cut). Inline: called on the LM thread during ask(); threaded:
    // on the codec thread, and the end may come after ask() has returned.
    std::function<void(const float* pcm, int n, bool end)> on_pcm;
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
    // speech out
    int frames = 0;          // audio frames (80 ms each)
    double frame_ms = 0;     // mean time to make one frame on the LM (depthformer + feedback decode)
    double codec_ms = 0;     // mean time to turn one frame into sound (inline codec only)
    double sound_ms = 0;     // audio length: frames * 80
    // tool calls
    bool tool = false;       // the answer is a tool call (text holds it; stop "tool")
    float tool_gap = 0;      // <tool_call> logit (+ bias) minus the best other token's, at the decision
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
    // Speak mode, before a new answer: the codec drops what is still queued from earlier answers (their sound is cut
    // by the new answer), so nothing of them reaches on_pcm afterwards. Call it from the thread that asks.
    void drop_sound();
    void reset_history();

    // ---- tool calls
    bool awaiting_tool() const { return tool_wait_.load(); }
    // The answer to the waiting call. say empty: the LM answers (and may call again); else result + say are recorded
    // and say is spoken as is.
    AskResult tool_result(const std::string& result, const std::string& say, int max_tokens,
                          const std::function<void(const std::string&)>& on_token);
    // Speaks text in Cortex's voice on the TTS slots; the conversation is not changed. Needs speak.
    AskResult say(const std::string& text);
    bool can_say() const;
    void set_state(const std::string& text);
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
    // A follow-up continues S only while a third of the context is still free for it: past that the conversation
    // starts again from V (its turns are still committed to H), so an answer is not cut by the context's end.
    bool s_has_room() const;
    bool decode_turn(const Turn& t, int seq, std::string* err);
    int turn_tokens(const Turn& t) const;
    void generate(AskResult& r, int max_tokens, const std::function<void(const std::string&)>& on_token,
                  std::chrono::steady_clock::time_point t0);
    void generate_speech(AskResult& r, int max_tokens, const std::function<void(const std::string&)>& on_token,
                         std::chrono::steady_clock::time_point t0, int seq = 3, bool audio_only = false);
    // After the answer's opening is decoded (logits on its last token): is the first token <tool_call>?
    bool decide_tool(AskResult& r);
    void generate_tool(AskResult& r, int max_tokens, std::chrono::steady_clock::time_point t0);
    // The answer after the decision; a tool call leaves the turn open (tool_wait_), else it is finished.
    void answer(AskResult& r, int max_tokens, const std::function<void(const std::string&)>& on_token,
                std::chrono::steady_clock::time_point t0);
    void finish_turn();
    void abandon_tool();  // a new question while a call waits: the call is dropped, S starts again from V
    std::string state_prefix();
    int s_limit() const;
    void speak_tts(AskResult& r, const std::string& text, std::chrono::steady_clock::time_point t0);
    // Speak mode: one end through on_pcm per answer. An ask opens it; generate_speech or, on an early return,
    // SoundEnd's destructor sends it.
    struct SoundEnd {
        Lm* lm;
        explicit SoundEnd(Lm* l) : lm(l) { lm->sound_open_ = true; }
        ~SoundEnd() { lm->end_sound(); }
    };
    void end_sound();
    bool sound_open_ = false;
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
    int pos_[6] = {0, 0, 0, 0, 0, 0};  // seq 4: the TTS head (system prompt), seq 5: one ce_say
    int pos_base_ = 0;                    // H position after start + system
    std::vector<Turn> history_;           // turns already in H
    std::vector<Turn> pending_;           // turns in S, not yet in H
    std::string open_;                    // closes the user turn, opens the answer ("<think></think>" with tools)
    std::atomic<bool> tool_wait_{false};  // a call was made and waits for its result
    Turn cur_;                            // the open turn while a call waits: a = call + results so far
    int tok_tool_call_ = -1;
    std::mutex state_mu_;
    std::string state_;
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
