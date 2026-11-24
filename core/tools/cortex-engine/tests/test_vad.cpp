#include <chrono>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include "check.h"
#include "vad.h"

using namespace std::chrono;

namespace {

const std::string kMedia = "/var/lib/cortex/bench/media/";
const std::string kGolden = "/var/lib/cortex/bench/engine/vad/golden/";
const std::string kWeights = "/var/lib/cortex/models/silero_vad_v4.bin";

std::vector<float> wav(const std::string& stem) {
    std::vector<float> pcm;
    int rate = 0;
    std::string err;
    if (!ce::read_wav_s16(kMedia + stem + ".wav", &pcm, &rate, &err)) std::printf("  wav: %s\n", err.c_str());
    CHECK(rate == 16000);
    return pcm;
}

std::vector<float> golden(const std::string& stem) {
    std::ifstream f(kGolden + stem + ".vad.f32", std::ios::binary | std::ios::ate);
    std::vector<float> p((size_t)f.tellg() / 4);
    f.seekg(0);
    f.read(reinterpret_cast<char*>(p.data()), (std::streamsize)(p.size() * 4));
    return p;
}

struct Seen {
    std::vector<ce::VadEvent> ev;
    int starts = 0, ends = 0;
    size_t audio = 0;
};

Seen listen(const std::vector<float>& pcm, size_t piece) {
    ce::Listener l;
    std::string err;
    CHECK(l.open(kWeights, ce::ListenConfig{}, &err));
    Seen s;
    for (size_t i = 0; i < pcm.size(); i += piece) {
        std::vector<ce::VadEvent> out;
        l.push(pcm.data() + i, std::min(piece, pcm.size() - i), &out);
        for (auto& e : out) {
            s.starts += e.kind == ce::VadEvent::Start;
            s.ends += e.kind == ce::VadEvent::End;
            if (e.kind == ce::VadEvent::Audio) s.audio += e.pcm.size();
            s.ev.push_back(std::move(e));
        }
    }
    return s;
}

}  // namespace

TEST(vad_matches_onnxruntime) {
    ce::SileroVad vad;
    std::string err;
    CHECK(vad.load(kWeights, &err));
    if (!err.empty()) std::printf("  load: %s\n", err.c_str());
    for (const char* stem : {"question1", "question2", "room_noise", "conversation"}) {
        const auto pcm = wav(stem);
        const auto ref = golden(stem);
        CHECK(ref.size() == pcm.size() / 512 && !ref.empty());
        vad.reset();
        double worst = 0;
        for (size_t i = 0; i < ref.size(); i++) {
            const double d = std::fabs(vad.step(pcm.data() + i * 512) - ref[i]);
            worst = std::max(worst, d);
        }
        std::printf("  %s: %zu chunks, max |cpp - ort| = %.2e\n", stem, ref.size(), worst);
        CHECK(worst <= 1e-4);
    }
}

TEST(vad_step_is_cheap) {
    ce::SileroVad vad;
    std::string err;
    CHECK(vad.load(kWeights, &err));
    const auto pcm = wav("conversation");
    const auto t = steady_clock::now();
    const size_t n = pcm.size() / 512;
    for (size_t i = 0; i < n; i++) vad.step(pcm.data() + i * 512);
    const double us = duration<double, std::micro>(steady_clock::now() - t).count() / n;
    std::printf("  %.0f us per 32 ms chunk\n", us);
    CHECK(us <= 1000.0);
}

TEST(vad_listener_two_questions) {
    // conversation.wav: noise 2 s, question1 (3.2 s), noise 2 s, question2 (3.6 s), noise 1.5 s.
    // pushed in 20 ms pieces, which do not line up with the 512-sample VAD chunk
    const auto s = listen(wav("conversation"), 320);
    CHECK(s.starts == 2 && s.ends == 2);
    double q_start[2] = {2.0, 7.2}, q_end[2] = {5.2, 10.8};
    int k = -1;
    for (auto& e : s.ev) {
        const double at = e.sample / 16000.0;
        if (e.kind == ce::VadEvent::Start) {
            k++;
            std::printf("  start %d at %.2f s\n", k, at);
            if (k < 2) CHECK(at >= q_start[k] - 0.4 && at <= q_start[k] + 0.6);
        } else if (e.kind == ce::VadEvent::End) {
            std::printf("  end %d at %.2f s\n", k, at);
            if (k < 2) CHECK(at >= q_end[k] - 0.6 && at <= q_end[k] + 0.8);
        }
    }
    // the event order is Start, Audio..., End per utterance, and audio never arrives outside one
    bool in = false;
    for (auto& e : s.ev) {
        if (e.kind == ce::VadEvent::Start) {
            CHECK(!in);
            in = true;
        } else if (e.kind == ce::VadEvent::End) {
            CHECK(in);
            in = false;
        } else {
            CHECK(in && !e.pcm.empty());
        }
    }
    // what is forwarded is the speech plus short pads, not the 5.5 s of noise around it
    std::printf("  forwarded %.2f s of 12.3 s\n", s.audio / 16000.0);
    CHECK(s.audio / 16000.0 <= 6.8 + 1.6);
    CHECK(s.audio / 16000.0 >= 6.0);
}

TEST(vad_listener_ignores_room_noise) {
    const auto s = listen(wav("room_noise"), 480);
    CHECK(s.ev.empty());
}

TEST(vad_listener_audio_is_contiguous) {
    // each utterance's audio is one unbroken run of the input: Audio.sample advances by the previous size
    const auto pcm = wav("conversation");
    const auto s = listen(pcm, 1000);
    int64_t next = -1;
    for (auto& e : s.ev) {
        if (e.kind == ce::VadEvent::Start) next = e.sample;
        if (e.kind != ce::VadEvent::Audio) continue;
        CHECK(e.sample == next);
        CHECK(e.sample >= 0 && e.sample + (int64_t)e.pcm.size() <= (int64_t)pcm.size());
        CHECK(std::equal(e.pcm.begin(), e.pcm.end(), pcm.begin() + e.sample));
        next = e.sample + (int64_t)e.pcm.size();
    }
}
