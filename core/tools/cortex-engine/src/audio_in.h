// Speech into the LM's input space while the user talks: the LFM3 audio encoder (mtmd audio stream, causal, no
// prompt) turns PCM into decoder rows step by step. Only the encoder runs here, never llama_decode: the thread
// that drives the LM threadpool gets pinned to its first core, so the rows go to the LM thread to be decoded.
#pragma once
#include <cstddef>
#include <string>
#include <vector>

struct mtmd_context;
struct mtmd_audio_stream;

namespace ce {

class AudioIn {
public:
    AudioIn(mtmd_context* mctx, int n_embd) : mctx_(mctx), n_embd_(n_embd) {}
    ~AudioIn();
    AudioIn(const AudioIn&) = delete;
    AudioIn& operator=(const AudioIn&) = delete;

    bool begin(std::string* err);  // opens the stream for a new utterance (drops any open one)
    // PCM float at rate(); appends the rows that are ready ([n * n_embd]) and returns how many, or -1.
    int push(const float* pcm, size_t n, std::vector<float>* rows);
    // closes the utterance: encodes what is left and appends the last rows (with the audio end marker)
    int end(std::vector<float>* rows);
    void drop();
    int rate() const;
    int n_embd() const { return n_embd_; }

private:
    int drain(std::vector<float>* rows);
    mtmd_context* mctx_;
    int n_embd_;
    mtmd_audio_stream* s_ = nullptr;
};

}  // namespace ce
