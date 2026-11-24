// Voice activity detection for hands-free listening: a plain C++ port of Silero VAD v4 (16 kHz branch),
// and a Listener that turns its per-chunk speech probability into utterances.
//
// Weights: /var/lib/cortex/models/silero_vad_v4.bin, exported from silero_vad.onnx (v4) by
// core/scripts/engine/silero_export.py. Not in git. Output matches onnxruntime to 1e-4.
#pragma once
#include <cstdint>
#include <deque>
#include <map>
#include <string>
#include <vector>

namespace ce {

// 16 kHz mono float PCM in [-1, 1) from a 16-bit PCM WAV file.
bool read_wav_s16(const std::string& path, std::vector<float>* pcm, int* rate, std::string* err);

class SileroVad {
public:
    static constexpr int kRate = 16000;
    static constexpr int kChunk = 512;  // 32 ms

    bool load(const std::string& weights, std::string* err);
    // Speech probability of the next kChunk samples. The LSTM state carries across calls.
    float step(const float* chunk);
    void reset();

private:
    struct T {
        std::vector<int> dims;
        std::vector<float> v;
    };
    std::map<std::string, T> w_;
    const float* p(const char* name) const;
    float h_[2][64] = {}, c_[2][64] = {};
    // scratch, sized at load
    std::vector<float> pad_, stft_, x1_, a_, b_, r_;
};

struct ListenConfig {
    float on = 0.5f;          // a chunk at or above this is speech
    float off = 0.35f;        // while speaking, a chunk below this counts toward the end
    int confirm_ms = 96;      // speech chunks needed before Start (drops clicks)
    int pre_roll_ms = 320;    // audio kept from before the first speech chunk
    int hangover_ms = 500;    // silence that ends an utterance
    int tail_ms = 96;         // silence forwarded after the last speech chunk
    int max_utterance_ms = 30000;
};

struct VadEvent {
    enum Kind { Start, Audio, End } kind;
    int64_t sample = 0;      // Start: first forwarded sample; Audio: its first sample; End: one past the last
    std::vector<float> pcm;  // Audio only
};

// Feeds any number of samples at a time. Events per utterance: Start, Audio..., End. Audio carries only the
// utterance (pre-roll, speech, short tail): noise between utterances is never forwarded.
class Listener {
public:
    bool open(const std::string& weights, const ListenConfig& cfg, std::string* err);
    void push(const float* pcm, size_t n, std::vector<VadEvent>* out);
    void reset();  // drops any utterance in progress without an End
    bool speaking() const { return state_ == Speaking; }

private:
    void on_chunk(const float* chunk, float prob, std::vector<VadEvent>* out);
    void audio(const float* x, size_t n, std::vector<VadEvent>* out);

    SileroVad vad_;
    ListenConfig cfg_;
    enum { Idle, Candidate, Speaking } state_ = Idle;
    std::vector<float> partial_;  // < kChunk samples waiting for the next push
    int64_t pos_ = 0;             // input samples consumed into chunks
    std::deque<float> pre_;       // Idle: last pre_roll samples
    std::vector<float> held_;     // Candidate: pre-roll + candidate chunks; Speaking: unsent silence
    int64_t held_at_ = 0;         // input sample index of held_[0]
    int voiced_ = 0, quiet_ = 0;  // chunk counters
    int64_t sent_ = 0;            // Speaking: next sample to forward
    int64_t utt_start_ = 0;
};

}  // namespace ce
