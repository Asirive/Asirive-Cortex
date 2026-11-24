// Hands-free listening through the C API: the toggle, VAD utterances, spoken answers.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

#include "../include/cortex_engine.h"
#include "../src/vad.h"
#include "check.h"
#include "events.h"

using namespace std::chrono;
using api_test::config;
using api_test::Events;
using api_test::json;
using api_test::show;

namespace {

std::vector<float> wav(const char* stem) {
    std::vector<float> pcm;
    int rate = 0;
    std::string err;
    CHECK(ce::read_wav_s16(std::string("/var/lib/cortex/bench/media/") + stem + ".wav", &pcm, &rate, &err));
    return pcm;
}

// the microphone: 20 ms pieces at real-time pace
void play(void* h, const std::vector<float>& pcm) {
    const size_t piece = 320;
    auto next = steady_clock::now();
    for (size_t i = 0; i < pcm.size(); i += piece) {
        CHECK(ce_push_audio(h, pcm.data() + i, (int)std::min(piece, pcm.size() - i)) == 0);
        next += milliseconds(20);
        std::this_thread::sleep_until(next);
    }
}

std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return (char)std::tolower(c); });
    return s;
}

}  // namespace

TEST(listen_answers_two_spoken_questions) {
    Events ev;
    // 30 tokens: answer 1 must end inside the 2 s gap, or question 2 rightly barges in on it
    void* h = ce_open(config(",\"max_tokens\":30").c_str(), &Events::cb, &ev);
    if (!h) std::printf("  open failed: %s\n", ce_last_error());
    CHECK(h != nullptr);
    if (!h) return;
    size_t at = 0;
    json view;
    CHECK(show(h, ev, "t001", 1, &view, &at));
    CHECK(ce_set_listening(h, 1) == 0);
    const size_t mark = ev.size();
    play(h, wav("conversation"));  // noise 2 s, question1, noise 2 s, question2, noise 1.5 s
    json done;
    size_t at_done = mark;
    CHECK(ev.wait("done", &done, &at_done, 15000));
    CHECK(ev.wait("done", &done, &at_done, 15000));
    const auto all = ev.snapshot();
    std::string answer[2];
    int k = -1;
    std::vector<std::string> order;
    for (size_t i = mark; i < all.size(); i++) {
        const auto& e = all[i];
        const std::string t = e["type"];
        if (t == "speech_start" || t == "speech_end" || t == "done") order.push_back(t);
        if (t == "speech_start") k++;
        if (t == "token" && k >= 0 && k < 2) {
            answer[k] += e["text"].get<std::string>();
            CHECK(e.value("voice", false));  // spoken answers are marked, so clients route them apart from asks
        }
        if (t == "speech_end" || t == "speech_start" || t == "done") std::printf("  %s\n", e.dump().c_str());
        if (t == "error") std::printf("  ERROR %s\n", e.dump().c_str());
    }
    std::printf("  answer 1: %s\n  answer 2: %s\n", answer[0].c_str(), answer[1].c_str());
    const std::vector<std::string> want = {"speech_start", "speech_end", "done", "speech_start", "speech_end", "done"};
    CHECK(order == want);
    CHECK(lower(answer[0]).find("singapore") != std::string::npos);
    CHECK(!answer[1].empty());
    // spoken answers are never cut mid-sentence (greedy end-of-turn on a near tie used to stop at "is **")
    for (auto& a : answer) CHECK(a.size() >= 60);
    CHECK(ev.count("error", mark) == 0);
    // the spoken answers start soon after the VAD calls the end of speech. Measured 128-306 ms over 8 answers: the
    // spread is wait_ms, the rows the encoder flushes at the end (how many depends on where speech stops in its window)
    size_t from = mark;
    for (int i = 0; i < 2; i++) {
        CHECK(ev.wait("done", &done, &from, 100));
        CHECK(done["voice"] == true && done["cancelled"] == false);
        CHECK(done["end_to_first_ms"].get<double>() <= 400.0);
        CHECK(done["wait_ms"].get<double>() <= done["end_to_first_ms"].get<double>());
    }
    // the audio thread stays on cpu1-3: it only encodes, the LM thread decodes
    json st = json::parse(ce_status(h));
    std::printf("  status: %s\n", st.dump().c_str());
    bool found = false;
    for (auto& th : st["threads"])
        if (th["name"] == "audio") {
            found = true;
            for (auto& c : th["cpus"]) CHECK(c.get<int>() >= 1 && c.get<int>() <= 3);
        }
    CHECK(found);
    CHECK(st["listening"] == true);
    ce_close(h);
}

TEST(listen_noise_and_toggle_off_stay_silent) {
    Events ev;
    void* h = ce_open(config().c_str(), &Events::cb, &ev);
    CHECK(h != nullptr);
    if (!h) return;
    // listening on, room noise only: no utterance, nothing fed to the model
    CHECK(ce_set_listening(h, 1) == 0);
    play(h, wav("room_noise"));
    std::this_thread::sleep_for(milliseconds(800));
    CHECK(ev.count("speech_start") == 0 && ev.count("done") == 0);
    // listening off: speech is ignored
    CHECK(ce_set_listening(h, 0) == 0);
    play(h, wav("question1"));
    std::this_thread::sleep_for(milliseconds(800));
    CHECK(ev.count("speech_start") == 0 && ev.count("done") == 0);
    // off mid-utterance: the utterance is dropped, no answer
    CHECK(ce_set_listening(h, 1) == 0);
    auto q = wav("question1");
    std::vector<float> first(q.begin(), q.begin() + q.size() / 2);
    play(h, first);
    CHECK(ce_set_listening(h, 0) == 0);
    std::this_thread::sleep_for(milliseconds(1500));
    std::printf("  starts %zu ends %zu dones %zu\n", ev.count("speech_start"), ev.count("speech_end"), ev.count("done"));
    CHECK(ev.count("speech_start") == 1 && ev.count("done") == 0);
    // and a typed ask still works afterwards
    size_t at = 0;
    json done;
    CHECK(ce_ask(h, "Say OK.", 5) == 0);
    CHECK(ev.wait("done", &done, &at));
    CHECK(done["n_out"].get<int>() >= 1);
    ce_close(h);
}

TEST(listen_barge_in_cancels_the_answer) {
    Events ev;
    void* h = ce_open(config().c_str(), &Events::cb, &ev);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_set_listening(h, 1) == 0);
    CHECK(ce_ask(h, "Describe the history of Singapore in great detail.", 300) == 0);
    std::this_thread::sleep_for(milliseconds(500));
    play(h, wav("question1"));  // the user talks over the answer
    std::vector<float> quiet(16000, 0.0f);
    play(h, quiet);
    json done;
    size_t at = 0;
    CHECK(ev.wait("done", &done, &at, 15000));
    std::printf("  typed answer: %s\n", done.dump().c_str());
    CHECK(done["cancelled"] == true);
    CHECK(ev.wait("done", &done, &at, 15000));
    std::printf("  spoken answer: %s\n", done.dump().c_str());
    CHECK(done["voice"] == true && done["n_out"].get<int>() >= 1);
    ce_close(h);
}
