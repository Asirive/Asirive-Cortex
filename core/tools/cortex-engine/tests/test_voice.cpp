// Spoken questions through the LM: audio rows from the LFM3 audio stream decoded into S while the user talks.
#include <pthread.h>
#include <sched.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "../src/audio_in.h"
#include "../src/lm.h"
#include "../src/vad.h"
#include "check.h"
#include "golden.h"

using namespace std::chrono;

namespace {

const std::string kModels = "/var/lib/cortex/models/";
const std::string kMedia = "/var/lib/cortex/bench/media/";

ce::LmConfig cfg() {
    ce::LmConfig c;
    c.model = kModels + "LFM3-Omni-2B-Q4_0.gguf";
    c.mmproj = kModels + "mmproj-LFM3-Omni-2B-Q8_0.gguf";
    return c;
}

std::vector<float> wav(const char* stem) {
    std::vector<float> pcm;
    int rate = 0;
    std::string err;
    CHECK(ce::read_wav_s16(kMedia + stem + ".wav", &pcm, &rate, &err));
    CHECK(rate == 16000);
    return pcm;
}

std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return (char)std::tolower(c); });
    return s;
}

// Encodes pcm in 320 ms pieces on a thread pinned to cpu1-3 (where the engine's audio thread runs).
// pieces[i] = rows produced by push i; the last entry is what end() produced.
struct Encoded {
    std::vector<std::vector<float>> pieces;
    std::vector<double> push_ms;
    double end_ms = 0, begin_ms = 0;
    int rows = 0;
};

Encoded encode(ce::Lm& lm, const std::vector<float>& pcm) {
    Encoded e;
    std::thread th([&] {
        cpu_set_t set;
        CPU_ZERO(&set);
        for (int c : {1, 2, 3}) CPU_SET(c, &set);
        pthread_setaffinity_np(pthread_self(), sizeof set, &set);
        std::string err;
        auto t = steady_clock::now();
        auto in = lm.audio_in(&err);
        CHECK(in != nullptr);
        if (!in) {
            std::printf("  audio_in: %s\n", err.c_str());
            return;
        }
        CHECK(in->begin(&err));
        e.begin_ms = duration<double, std::milli>(steady_clock::now() - t).count();
        const size_t step = 5120;
        for (size_t i = 0; i < pcm.size(); i += step) {
            std::vector<float> rows;
            t = steady_clock::now();
            CHECK(in->push(pcm.data() + i, std::min(step, pcm.size() - i), &rows) >= 0);
            e.push_ms.push_back(duration<double, std::milli>(steady_clock::now() - t).count());
            e.pieces.push_back(std::move(rows));
        }
        std::vector<float> rows;
        t = steady_clock::now();
        CHECK(in->end(&rows) >= 0);
        e.end_ms = duration<double, std::milli>(steady_clock::now() - t).count();
        e.pieces.push_back(std::move(rows));
    });
    th.join();
    for (auto& p : e.pieces) e.rows += (int)(p.size() / lm.n_embd_inp());
    return e;
}

int rows_of(const ce::Lm& lm, const std::vector<float>& v) { return (int)(v.size() / lm.n_embd_inp()); }
std::unique_ptr<ce::Lm> open_lm() {
    std::string err;
    auto lm = ce::Lm::open(cfg(), &err);
    if (!lm) std::printf("  open failed: %s\n", err.c_str());
    return lm;
}

}  // namespace

TEST(voice_audio_stream_encodes_while_talking) {
    auto lm = open_lm();
    if (!lm) { CHECK(false); return; }
    const auto pcm = wav("question1");
    const auto e = encode(*lm, pcm);
    CHECK(!e.push_ms.empty());
    if (e.push_ms.empty()) return;
    std::vector<double> ms = e.push_ms;
    std::sort(ms.begin(), ms.end());
    std::printf("  %d rows for %.2f s (%.1f rows/s); begin %.0f ms; push of 320 ms audio: median %.0f max %.0f ms; "
                "end %.0f ms (%d rows)\n",
                e.rows, pcm.size() / 16000.0, e.rows / (pcm.size() / 16000.0), e.begin_ms, ms[ms.size() / 2],
                ms.back(), e.end_ms, rows_of(*lm, e.pieces.back()));
    CHECK(e.rows > 0);
    CHECK(ms[ms.size() / 2] <= 320.0);  // keeps up with real time on cpu1-3
}

TEST(voice_answers_spoken_question) {
    auto lm = open_lm();
    if (!lm) { CHECK(false); return; }
    const auto e = encode(*lm, wav("question1"));  // "What is the capital of Singapore and how big is it?"
    std::string err;
    for (auto& p : e.pieces)
        if (!p.empty()) CHECK(lm->voice_feed(p.data(), rows_of(*lm, p), &err));
    const auto r = lm->voice_answer(60, nullptr);
    std::printf("  answer: %s (ttft %.0f ms, err '%s')\n", r.text.c_str(), r.ttft_ms, r.error.c_str());
    CHECK(r.error.empty() && r.n_out > 3);
    CHECK(lower(r.text).find("singapore") != std::string::npos);
    CHECK(r.view_frame_id == -1);
}

TEST(voice_tail_costs_little_after_speech_ends) {
    // rows are decoded while the user talks; after the end only the last rows, the turn close and one token remain
    auto lm = open_lm();
    if (!lm) { CHECK(false); return; }
    auto f = golden::load_f32(golden::npu_feats + "t001.npu.f32");
    std::string err;
    CHECK(lm->read_view(f.data(), 220, 1, &err));
    const auto e = encode(*lm, wav("question1"));
    for (size_t i = 0; i + 1 < e.pieces.size(); i++)
        if (!e.pieces[i].empty()) CHECK(lm->voice_feed(e.pieces[i].data(), rows_of(*lm, e.pieces[i]), &err));
    const auto t = steady_clock::now();
    auto& last = e.pieces.back();
    if (!last.empty()) CHECK(lm->voice_feed(last.data(), rows_of(*lm, last), &err));
    const auto r = lm->voice_answer(40, nullptr);
    const double after_end = duration<double, std::milli>(steady_clock::now() - t).count() - r.total_ms + r.ttft_ms;
    std::printf("  encode end %.0f ms + rows/close/first token %.0f ms = %.0f ms speech-end -> first token: %s\n",
                e.end_ms, after_end, e.end_ms + after_end, r.text.c_str());
    CHECK(r.view_frame_id == 1);
    CHECK(e.end_ms + after_end <= 600.0);
}

TEST(voice_rebuilds_on_a_view_that_lands_mid_utterance) {
    auto lm = open_lm();
    if (!lm) { CHECK(false); return; }
    auto f1 = golden::load_f32(golden::npu_feats + "t001.npu.f32");
    auto f8 = golden::load_f32(golden::npu_feats + "t008.npu.f32");
    std::string err;
    CHECK(lm->read_view(f1.data(), 220, 1, &err));
    const auto e = encode(*lm, wav("question1"));
    const size_t half = e.pieces.size() / 2;
    for (size_t i = 0; i < half; i++)
        if (!e.pieces[i].empty()) CHECK(lm->voice_feed(e.pieces[i].data(), rows_of(*lm, e.pieces[i]), &err));
    CHECK(lm->read_view(f8.data(), 220, 8, &err));  // the speech-start refresh lands
    for (size_t i = half; i < e.pieces.size(); i++)
        if (!e.pieces[i].empty()) CHECK(lm->voice_feed(e.pieces[i].data(), rows_of(*lm, e.pieces[i]), &err));
    const auto r = lm->voice_answer(60, nullptr);
    std::printf("  answer on view 8: %s\n", r.text.c_str());
    CHECK(r.view_frame_id == 8);
    CHECK(lower(r.text).find("singapore") != std::string::npos);
}

TEST(voice_turn_is_remembered) {
    auto lm = open_lm();
    if (!lm) { CHECK(false); return; }
    const auto e = encode(*lm, wav("question1"));
    std::string err;
    for (auto& p : e.pieces)
        if (!p.empty()) CHECK(lm->voice_feed(p.data(), rows_of(*lm, p), &err));
    const auto a = lm->voice_answer(40, nullptr);
    // a typed follow-up continues the same conversation
    const auto b = lm->ask("Which country did I just ask you about? One word.", 10, nullptr);
    std::printf("  follow-up: %s [%s, %d tokens]\n", b.text.c_str(), b.stop.c_str(), b.n_out);
    CHECK(lower(b.text).find("singapore") != std::string::npos);
    CHECK(b.n_out <= 6 && b.stop == "eog");  // a confident end (one word, no full stop) is not held
    // the spoken turn (its audio rows) moves into H with the next view, and is still known there
    const int before = lm->history_tokens();
    auto f = golden::load_f32(golden::npu_feats + "t001.npu.f32");
    CHECK(lm->read_view(f.data(), 220, 1, &err));
    std::printf("  history %d -> %d tokens (%d audio rows)\n", before, lm->history_tokens(), e.rows);
    CHECK(lm->history_tokens() >= before + e.rows);
    const auto c = lm->ask("Earlier I asked about the capital of a country. Which country? One word.", 10, nullptr);
    std::printf("  from history: %s\n", c.text.c_str());
    CHECK(lower(c.text).find("singapore") != std::string::npos);
    (void)a;
}

TEST(voice_answer_from_vad_segment_is_complete) {
    // the engine's path without its threads: VAD segment (pre-roll noise + speech + tail) -> encoder -> S on a view
    auto lm = open_lm();
    if (!lm) { CHECK(false); return; }
    auto f = golden::load_f32(golden::npu_feats + "t001.npu.f32");
    std::string err;
    CHECK(lm->read_view(f.data(), 220, 1, &err));
    // utterance 1 straight after the first view read: before text-only sampling, LFM3 opened an interleaved
    // text + speech block (<|mixed_start|>) here and ended the turn after "The capital of Singapore is **"
    ce::Listener l;
    CHECK(l.open("/var/lib/cortex/models/silero_vad_v4.bin", ce::ListenConfig{}, &err));
    const auto pcm = wav("conversation");
    std::vector<ce::VadEvent> evs;
    for (size_t i = 0; i < pcm.size(); i += 320) l.push(pcm.data() + i, std::min<size_t>(320, pcm.size() - i), &evs);
    std::vector<std::vector<float>> utts(1);
    for (auto& e : evs) {
        if (e.kind == ce::VadEvent::End) utts.emplace_back();
        if (e.kind == ce::VadEvent::Audio) utts.back().insert(utts.back().end(), e.pcm.begin(), e.pcm.end());
    }
    CHECK(utts.size() >= 2);
    for (size_t u = 0; u < 2 && u < utts.size(); u++) {
        const auto e = encode(*lm, utts[u]);
        for (auto& p : e.pieces)
            if (!p.empty()) CHECK(lm->voice_feed(p.data(), rows_of(*lm, p), &err));
        const auto r = lm->voice_answer(60, nullptr);
        std::printf("  q%zu (%.2f s, %d rows): %s [%s, %d tokens]\n", u + 1, utts[u].size() / 16000.0, e.rows,
                    r.text.c_str(), r.stop.c_str(), r.n_out);
        CHECK(r.n_out >= 15);
        CHECK(lm->read_view(f.data(), 220, 2 + (long)u, &err));
    }
}

TEST(voice_drop_forgets_the_utterance) {
    auto lm = open_lm();
    if (!lm) { CHECK(false); return; }
    const auto e = encode(*lm, wav("question1"));
    std::string err;
    CHECK(lm->voice_feed(e.pieces[2].data(), rows_of(*lm, e.pieces[2]), &err));
    lm->voice_drop();
    const auto r = lm->voice_answer(10, nullptr);
    CHECK(!r.error.empty() && r.n_out == 0);  // nothing to answer
    const auto t = lm->ask("Say OK.", 5, nullptr);
    CHECK(t.error.empty() && t.n_out >= 1);
}
