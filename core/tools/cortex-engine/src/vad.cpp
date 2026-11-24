#include "vad.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

namespace ce {

bool read_wav_s16(const std::string& path, std::vector<float>* pcm, int* rate, std::string* err) {
    std::ifstream f(path, std::ios::binary);
    char riff[12];
    if (!f.read(riff, 12) || std::memcmp(riff, "RIFF", 4) || std::memcmp(riff + 8, "WAVE", 4)) {
        *err = path + ": not a RIFF/WAVE file";
        return false;
    }
    int channels = 0, bits = 0, format = 0;
    for (;;) {
        char id[4];
        uint32_t size = 0;
        if (!f.read(id, 4) || !f.read(reinterpret_cast<char*>(&size), 4)) {
            *err = path + ": no data chunk";
            return false;
        }
        if (!std::memcmp(id, "fmt ", 4)) {
            std::vector<char> b(size);
            f.read(b.data(), size);
            uint16_t u16;
            uint32_t u32;
            std::memcpy(&u16, &b[0], 2), format = u16;
            std::memcpy(&u16, &b[2], 2), channels = u16;
            std::memcpy(&u32, &b[4], 4), *rate = (int)u32;
            std::memcpy(&u16, &b[14], 2), bits = u16;
        } else if (!std::memcmp(id, "data", 4)) {
            if (format != 1 || channels != 1 || bits != 16) {
                *err = path + ": need 16-bit PCM mono";
                return false;
            }
            std::vector<int16_t> s(size / 2);
            f.read(reinterpret_cast<char*>(s.data()), (std::streamsize)(s.size() * 2));
            s.resize((size_t)f.gcount() / 2);
            pcm->resize(s.size());
            for (size_t i = 0; i < s.size(); i++) (*pcm)[i] = s[i] / 32768.0f;
            return true;
        } else {
            f.seekg(size + (size & 1), std::ios::cur);
        }
    }
}

// ---------------------------------------------------------------- Silero v4, 16 kHz branch
namespace {

constexpr int kPad = 96, kWin = 256, kHop = 64, kBins = 129, kT = 8, kH = 64;

// depthwise conv, kernel 5, pad 2, + bias: [C][T] -> [C][T]
void dw5(const float* in, int C, int T, const float* w, const float* b, float* out) {
    for (int c = 0; c < C; c++)
        for (int t = 0; t < T; t++) {
            float s = b[c];
            for (int k = 0; k < 5; k++) {
                const int i = t + k - 2;
                if (i >= 0 && i < T) s += w[c * 5 + k] * in[c * T + i];
            }
            out[c * T + t] = s;
        }
}

// 1x1 conv with stride, + bias: [Ci][T] -> [Co][To]; returns To
int pw(const float* in, int Ci, int T, const float* w, const float* b, int Co, int stride, float* out) {
    const int To = (T - 1) / stride + 1;
    for (int o = 0; o < Co; o++)
        for (int t = 0; t < To; t++) {
            float s = b[o];
            const float* wo = w + o * Ci;
            for (int i = 0; i < Ci; i++) s += wo[i] * in[i * T + t * stride];
            out[o * To + t] = s;
        }
    return To;
}

void relu(float* x, size_t n) {
    for (size_t i = 0; i < n; i++) x[i] = x[i] > 0 ? x[i] : 0;
}

float sigm(float x) { return 1.0f / (1.0f + std::exp(-x)); }

}  // namespace

const float* SileroVad::p(const char* name) const { return w_.at(name).v.data(); }

bool SileroVad::load(const std::string& path, std::string* err) {
    std::ifstream f(path, std::ios::binary);
    char magic[8];
    if (!f.read(magic, 8) || std::memcmp(magic, "SVAD4", 5)) {
        *err = path + ": not a Silero v4 weight file (run core/scripts/engine/silero_export.py)";
        return false;
    }
    w_.clear();
    uint32_t len;
    while (f.read(reinterpret_cast<char*>(&len), 4)) {
        std::string name(len, '\0');
        uint32_t nd;
        f.read(&name[0], len);
        f.read(reinterpret_cast<char*>(&nd), 4);
        T t;
        size_t n = 1;
        for (uint32_t i = 0; i < nd; i++) {
            uint32_t d;
            f.read(reinterpret_cast<char*>(&d), 4);
            t.dims.push_back((int)d);
            n *= d;
        }
        t.v.resize(n);
        if (!f.read(reinterpret_cast<char*>(t.v.data()), (std::streamsize)(n * 4))) {
            *err = path + ": truncated at " + name;
            return false;
        }
        w_[name] = std::move(t);
    }
    const std::pair<const char*, size_t> need[] = {
        {"model.feature_extractor.forward_basis_buffer", 258 * kWin},
        {"model.adaptive_normalization.filter_", 7},
        {"model.first_layer.0.dw_conv.0.weight", 258 * 5},
        {"model.first_layer.0.pw_conv.0.weight", 16 * 258},
        {"model.first_layer.0.proj.weight", 16 * 258},
        {"model.encoder.3.0.pw_conv.0.weight", 32 * 16},
        {"model.encoder.7.0.pw_conv.0.weight", 32 * 32},
        {"model.encoder.11.0.pw_conv.0.weight", 64 * 32},
        {"model.decoder.decoder.1.weight", 64},
        {"1110", 16 * 16}, {"1113", 32 * 32}, {"1116", 32 * 32}, {"1119", 64 * 64},
        {"lstm0.W", 4 * kH * kH}, {"lstm0.R", 4 * kH * kH}, {"lstm0.B", 8 * kH},
        {"lstm1.W", 4 * kH * kH}, {"lstm1.R", 4 * kH * kH}, {"lstm1.B", 8 * kH},
        {"spect.mul", 1}, {"spect.add", 1},
    };
    for (auto& [name, n] : need) {
        auto it = w_.find(name);
        if (it == w_.end() || it->second.v.size() != n) {
            *err = path + ": missing or wrong size: " + name;
            return false;
        }
    }
    pad_.resize(kChunk + 2 * kPad);
    stft_.resize(258 * kT);
    x1_.resize(258 * kT);
    a_.resize(258 * kT);
    b_.resize(258 * kT);
    r_.resize(258 * kT);
    reset();
    return true;
}

void SileroVad::reset() {
    std::memset(h_, 0, sizeof h_);
    std::memset(c_, 0, sizeof c_);
}

float SileroVad::step(const float* x) {
    // reflect pad 96 both sides, then the STFT as a stride-64 conv: 258 rows (129 real, 129 imaginary) x 8 frames
    float* pd = pad_.data();
    for (int i = 0; i < kPad; i++) pd[i] = x[kPad - i];
    std::memcpy(pd + kPad, x, kChunk * sizeof(float));
    for (int k = 0; k < kPad; k++) pd[kPad + kChunk + k] = x[kChunk - 2 - k];
    const float* basis = p("model.feature_extractor.forward_basis_buffer");
    for (int c = 0; c < 258; c++)
        for (int t = 0; t < kT; t++) {
            float s = 0;
            const float* bc = basis + c * kWin;
            const float* xt = pd + t * kHop;
            for (int k = 0; k < kWin; k++) s += bc[k] * xt[k];
            stft_[c * kT + t] = s;
        }
    // x1 = [magnitude; log(magnitude * 2^20 + 1) - smoothed mean]
    const float mul = *p("spect.mul"), add = *p("spect.add");
    float* mag = x1_.data();
    float* norm = x1_.data() + kBins * kT;
    float mean[kT] = {};
    for (int f = 0; f < kBins; f++)
        for (int t = 0; t < kT; t++) {
            const float re = stft_[f * kT + t], im = stft_[(kBins + f) * kT + t];
            const float m = std::sqrt(re * re + im * im);
            mag[f * kT + t] = m;
            norm[f * kT + t] = std::log(m * mul + add);
            mean[t] += norm[f * kT + t];
        }
    for (float& m : mean) m /= kBins;
    const float m0[kT + 6] = {mean[3], mean[2], mean[1], mean[0], mean[1], mean[2], mean[3],
                              mean[4], mean[5], mean[6], mean[7], mean[6], mean[5], mean[4]};
    const float* filt = p("model.adaptive_normalization.filter_");
    float mm = 0;
    for (int t = 0; t < kT; t++)
        for (int k = 0; k < 7; k++) mm += filt[k] * m0[t + k];
    mm /= kT;
    for (int i = 0; i < kBins * kT; i++) norm[i] -= mm;

    // conv blocks: dw(k5)+relu -> pw, plus 1x1 projection (or identity), relu; then a 1x1 conv (stride) + relu
    int C = 258, T = kT;
    float* cur = x1_.data();
    auto block = [&](const std::string& pre, int Co, bool proj) {
        dw5(cur, C, T, p((pre + ".dw_conv.0.weight").c_str()), p((pre + ".dw_conv.0.bias").c_str()), a_.data());
        relu(a_.data(), (size_t)C * T);
        pw(a_.data(), C, T, p((pre + ".pw_conv.0.weight").c_str()), p((pre + ".pw_conv.0.bias").c_str()), Co, 1,
           b_.data());
        if (proj) {
            pw(cur, C, T, p((pre + ".proj.weight").c_str()), p((pre + ".proj.bias").c_str()), Co, 1, r_.data());
            for (int i = 0; i < Co * T; i++) b_[i] += r_[i];
        } else {
            for (int i = 0; i < Co * T; i++) b_[i] += cur[i];
        }
        relu(b_.data(), (size_t)Co * T);
        C = Co;
    };
    auto down = [&](const char* w, const char* b, int stride) {
        T = pw(b_.data(), C, T, p(w), p(b), C, stride, r_.data());
        relu(r_.data(), (size_t)C * T);
        std::memcpy(x1_.data(), r_.data(), (size_t)C * T * sizeof(float));
        cur = x1_.data();
    };
    block("model.first_layer.0", 16, true);
    down("1110", "1111", 2);
    block("model.encoder.3.0", 32, true);
    down("1113", "1114", 2);
    block("model.encoder.7.0", 32, false);
    down("1116", "1117", 2);
    block("model.encoder.11.0", 64, true);
    down("1119", "1120", 1);
    // T == 1 here: one LSTM step per chunk

    // two LSTM layers (ONNX gate order i, o, f, c; B = [Wb; Rb])
    float in[kH];
    std::memcpy(in, cur, sizeof in);
    for (int l = 0; l < 2; l++) {
        const std::string n = "lstm" + std::to_string(l);
        const float *W = p((n + ".W").c_str()), *R = p((n + ".R").c_str()), *B = p((n + ".B").c_str());
        float g[4 * kH];
        for (int j = 0; j < 4 * kH; j++) {
            float s = B[j] + B[4 * kH + j];
            const float *wj = W + j * kH, *rj = R + j * kH;
            for (int k = 0; k < kH; k++) s += wj[k] * in[k] + rj[k] * h_[l][k];
            g[j] = s;
        }
        for (int k = 0; k < kH; k++) {
            const float i = sigm(g[k]), o = sigm(g[kH + k]), f = sigm(g[2 * kH + k]), cc = std::tanh(g[3 * kH + k]);
            c_[l][k] = f * c_[l][k] + i * cc;
            h_[l][k] = o * std::tanh(c_[l][k]);
        }
        std::memcpy(in, h_[l], sizeof in);
    }
    const float* dw = p("model.decoder.decoder.1.weight");
    float s = *p("model.decoder.decoder.1.bias");
    for (int k = 0; k < kH; k++) s += dw[k] * (in[k] > 0 ? in[k] : 0);
    return sigm(s);
}

// ---------------------------------------------------------------- Listener
namespace {
int chunks(int ms) { return (ms * SileroVad::kRate / 1000 + SileroVad::kChunk - 1) / SileroVad::kChunk; }
}  // namespace

bool Listener::open(const std::string& weights, const ListenConfig& cfg, std::string* err) {
    cfg_ = cfg;
    if (!vad_.load(weights, err)) return false;
    reset();
    return true;
}

void Listener::reset() {
    vad_.reset();
    state_ = Idle;
    partial_.clear();
    pre_.clear();
    held_.clear();
    pos_ = held_at_ = sent_ = utt_start_ = 0;
    voiced_ = quiet_ = 0;
}

void Listener::push(const float* x, size_t n, std::vector<VadEvent>* out) {
    partial_.insert(partial_.end(), x, x + n);
    size_t at = 0;
    while (partial_.size() - at >= (size_t)SileroVad::kChunk) {
        const float* c = partial_.data() + at;
        on_chunk(c, vad_.step(c), out);
        pos_ += SileroVad::kChunk;
        at += SileroVad::kChunk;
    }
    partial_.erase(partial_.begin(), partial_.begin() + (long)at);
}

void Listener::audio(const float* x, size_t n, std::vector<VadEvent>* out) {
    if (!n) return;
    VadEvent e{VadEvent::Audio, sent_, std::vector<float>(x, x + n)};
    sent_ += (int64_t)n;
    out->push_back(std::move(e));
}

void Listener::on_chunk(const float* c, float prob, std::vector<VadEvent>* out) {
    const size_t K = SileroVad::kChunk, pre_n = (size_t)cfg_.pre_roll_ms * SileroVad::kRate / 1000;
    auto to_pre = [&](const float* x, size_t n) {
        pre_.insert(pre_.end(), x, x + n);
        while (pre_.size() > pre_n) pre_.pop_front();
    };
    switch (state_) {
    case Idle:
        if (prob < cfg_.on) {
            to_pre(c, K);
            return;
        }
        held_.assign(pre_.begin(), pre_.end());
        held_at_ = pos_ - (int64_t)pre_.size();
        held_.insert(held_.end(), c, c + K);
        pre_.clear();
        voiced_ = 1, quiet_ = 0;
        state_ = Candidate;
        break;
    case Candidate:
        held_.insert(held_.end(), c, c + K);
        voiced_ += prob >= cfg_.on;
        quiet_ = prob < cfg_.off ? quiet_ + 1 : 0;
        if (quiet_ >= chunks(cfg_.confirm_ms)) {  // a click, not speech: back to idle
            to_pre(held_.data(), held_.size());
            held_.clear();
            state_ = Idle;
            return;
        }
        break;
    case Speaking:
        if (prob >= cfg_.off) {
            audio(held_.data(), held_.size(), out);
            held_.clear();
            audio(c, K, out);
            quiet_ = 0;
        } else {
            held_.insert(held_.end(), c, c + K);
            quiet_++;
        }
        if (quiet_ >= chunks(cfg_.hangover_ms) || pos_ + (int64_t)K - utt_start_ >= (int64_t)cfg_.max_utterance_ms * 16) {
            const size_t tail = std::min(held_.size(), (size_t)cfg_.tail_ms * SileroVad::kRate / 1000);
            audio(held_.data(), tail, out);
            out->push_back(VadEvent{VadEvent::End, sent_, {}});
            to_pre(held_.data() + tail, held_.size() - tail);
            held_.clear();
            quiet_ = voiced_ = 0;
            state_ = Idle;
        }
        return;
    }
    if (state_ == Candidate && voiced_ >= chunks(cfg_.confirm_ms)) {
        utt_start_ = sent_ = held_at_;
        out->push_back(VadEvent{VadEvent::Start, sent_, {}});
        audio(held_.data(), held_.size(), out);
        held_.clear();
        quiet_ = 0;
        state_ = Speaking;
    }
}

}  // namespace ce
