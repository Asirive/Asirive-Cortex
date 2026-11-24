#include "audio_in.h"

#include "llama.h"
#include "mtmd.h"

namespace ce {

AudioIn::~AudioIn() { drop(); }

void AudioIn::drop() {
    if (s_) mtmd_audio_stream_free(s_);
    s_ = nullptr;
}

int AudioIn::rate() const { return mtmd_get_audio_sample_rate(mctx_); }

bool AudioIn::begin(std::string* err) {
    drop();
    s_ = mtmd_audio_stream_init(mctx_, mtmd_audio_stream_params_default());
    if (!s_ && err) *err = "cannot open the audio stream";
    return s_ != nullptr;
}

int AudioIn::drain(std::vector<float>* rows) {
    int total = 0;
    for (;;) {
        const int32_t n = mtmd_audio_stream_step(s_, LLAMA_TOKEN_NULL);
        if (n == -2) return -1;
        if (n <= 0) return total;
        const float* r = mtmd_audio_stream_get_output_embd(s_);
        rows->insert(rows->end(), r, r + (size_t)n * n_embd_);
        total += n;
    }
}

int AudioIn::push(const float* pcm, size_t n, std::vector<float>* rows) {
    if (!s_ || mtmd_audio_stream_push(s_, pcm, n) != 0) return -1;
    return drain(rows);
}

int AudioIn::end(std::vector<float>* rows) {
    if (!s_) return -1;
    mtmd_audio_stream_flush(s_, true);
    const int n = drain(rows);
    drop();
    return n;
}

}  // namespace ce
