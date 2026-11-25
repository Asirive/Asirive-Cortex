// Cortex's voice: LFM3-Omni answering in interleaved text + audio (MIXED mode) on the engine's own LM context.
//
// A port of llama.cpp b12679's lfm3a pipeline (tools/mtmd/mtmd-helper-gen.cpp, lfm3a_gen_audio_pipeline::step_gen)
// with one change: the codec is not run inside the loop. Each frame's 12 codes go out through SpeakIo::on_frame, so
// the caller can turn them into sound on another thread and another mtmd context (one mtmd context runs one graph at
// a time) while the backbone and depthformer make the next frame. tests/test_speech.cpp checks the port against the
// helper: same text, same PCM for a fixed seed.
//
//   text slot   the backbone's greedy token; <|im_end|> ends the answer, <|text_end|> ends the text (audio only from
//               there), pieces go to on_token (control tokens print as nothing)
//   audio slot  3 depthformer passes reveal the 12 codebooks (4/4/4, random order), then the feedback embedding of the
//               frame is decoded into the backbone; the end-of-audio code ends the segment (codec tail: on_flush) and
//               the answer goes on in text, where the model may open another audio or mixed segment
//   MIXED       6 text slots, 12 audio slots, ... until <|text_end|>
#pragma once
#include <cstdint>
#include <functional>
#include <memory>
#include <random>
#include <string>
#include <vector>

struct llama_context;
struct llama_model;
struct llama_sampler;
struct mtmd_context;
struct mtmd_gen_state;

namespace ce {

constexpr int kCodebooks = 12;
constexpr int kFrameSamples = 1920;  // 80 ms at 24 kHz

// codes -> PCM (codec decoder + ISTFT) with its own gen state on the given mtmd context. Stateful across frames.
class Codec {
public:
    static std::unique_ptr<Codec> open(mtmd_context* ctx, std::string* err);
    ~Codec();
    bool decode(const int32_t* codes, std::vector<float>* pcm);  // one frame; appends its samples
    bool flush(std::vector<float>* pcm);                         // the ISTFT tail of the last frame, if any
    void reset();                                                // cold start for the next answer
    double last_ms() const { return last_ms_; }

private:
    Codec() = default;
    mtmd_context* ctx_ = nullptr;
    mtmd_gen_state* st_ = nullptr;
    bool pending_tail_ = false;
    double last_ms_ = 0;
};

// The codec on its own thread and its own mtmd context (one context runs one graph at a time, so a codec on the LM's
// context would wait for the depthformer). The thread pins itself to `cpus` and opens the context from there, so
// ggml's compute threads stay on those cores. Frames are decoded in order, behind the LM, and come out through
// on_pcm, which is called on the codec thread.
class CodecThread {
public:
    static std::unique_ptr<CodecThread> open(const std::string& mmproj, const llama_model* model,
                                             const std::vector<int>& cpus, int n_threads,
                                             std::function<void(const float*, int, bool end)> on_pcm,
                                             std::string* err);
    ~CodecThread();
    void push(const int32_t* codes);  // copies the 12 codes, returns at once
    void flush();                     // an audio segment ended: its ISTFT tail, after the queued frames
    void end();                       // the answer ended: after the queued frames, the tail, on_pcm(.., end), reset
    // The answer was cut: queued frames are dropped, the state reset, on_pcm(nullptr, 0, true). Returns when done,
    // so nothing of this answer comes out afterwards.
    void clear();
    // A new answer starts: every queued item of every earlier answer is dropped (their sound is being cut), the state
    // reset, nothing sent. Returns when done, so nothing of those answers comes out afterwards.
    void drop();
    double mean_ms() const;  // mean codec time per frame, this answer so far

private:
    CodecThread() = default;
    struct Impl;
    std::unique_ptr<Impl> im_;
};

struct SpeakIo {
    std::function<void(const std::string&)> on_token;  // shown text pieces
    std::function<void(const int32_t* codes)> on_frame;  // 12 codes per audio frame
    std::function<void()> on_flush;                     // an audio segment ended: flush the codec tail
    std::function<bool()> cancelled;
};

struct SpeakResult {
    std::string text, stop, error;  // stop: "eog", "max", "cancel", "error"
    int n_text = 0, frames = 0;
    double frame_ms = 0;  // mean LM-thread time per audio frame: depthformer + on_frame + feedback decode
};

class Speech {
public:
    static std::unique_ptr<Speech> open(llama_context* lctx, mtmd_context* mctx, std::string* err);
    ~Speech();
    // Decodes `lead` + <|mixed_start|> on seq at *pos, then generates until a stop. Advances *pos. Turns the context's
    // embeddings output on for the run and off after it.
    SpeakResult run(int seq, int* pos, const std::string& lead, int max_tokens, int max_frames, uint32_t seed,
                    const SpeakIo& io);
    int max_pos = 1 << 30;  // the context's end: generation stops before a decode at *pos >= max_pos (stop "max")

private:
    Speech() = default;
    bool decode_token(int tok, int seq, int* pos);
    bool decode_embd(const float* e, int seq, int* pos);
    bool sample_frame(const float* h_state, std::vector<int32_t>& codes, const float** fb, bool* is_eos);
    void apply_rep_penalty(float* l, size_t n_vocab, int cb) const;
    int32_t sample(const float* l, size_t n_vocab);

    llama_context* lctx_ = nullptr;
    mtmd_context* mctx_ = nullptr;
    mtmd_gen_state* st_ = nullptr;  // depthformer
    llama_sampler* greedy_ = nullptr;
    int n_embd_ = 0;
    int tok_audio_start_ = -1, tok_mixed_start_ = -1, tok_text_end_ = -1, tok_im_end_ = -1;
    float temp_ = 0, rep_penalty_ = 1;
    int top_k_ = 0, rep_window_ = 0;
    std::mt19937 rng_;
    std::vector<float> logits_, fb_, h_state_;
    std::vector<int32_t> hist_;  // frame-major codes of this answer
};

}  // namespace ce
