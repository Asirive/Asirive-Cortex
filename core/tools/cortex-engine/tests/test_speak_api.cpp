// Speech out through the C API: answers spoken on the speaker, the mic muted while Cortex talks, cuts.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <string>
#include <sys/stat.h>
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
using api_test::now_ms;
using api_test::show;

namespace {

const char* kWav = "/tmp/ce_answer.wav";
const char* kShort = "What is two plus two? Answer in a few words.";
const char* kLong = "Tell me a long story about a lighthouse keeper.";

void* open_speak(Events& ev, const std::string& extra = "") {
    std::string dev = std::string(",\"speak\":true,\"speaker_device\":\"wav:") + kWav + "\"";
    void* h = ce_open(config(dev + extra).c_str(), &Events::cb, &ev);
    if (!h) std::printf("  open failed: %s\n", ce_last_error());
    return h;
}

json status(void* h) { return json::parse(ce_status(h)); }

// index of the first event of this type at or after from, or -1
long index_of(Events& ev, const std::string& type, size_t from = 0) {
    auto all = ev.snapshot();
    for (size_t i = from; i < all.size(); i++)
        if (all[i]["type"] == type) return (long)i;
    return -1;
}

std::vector<float> wav(const char* stem) {
    std::vector<float> pcm;
    int rate = 0;
    std::string err;
    CHECK(ce::read_wav_s16(std::string("/var/lib/cortex/bench/media/") + stem + ".wav", &pcm, &rate, &err));
    return pcm;
}

void play(void* h, const std::vector<float>& pcm) {  // the microphone: 20 ms pieces at real-time pace
    const size_t piece = 320;
    auto next = steady_clock::now();
    for (size_t i = 0; i < pcm.size(); i += piece) {
        CHECK(ce_push_audio(h, pcm.data() + i, (int)std::min(piece, pcm.size() - i)) == 0);
        next += milliseconds(20);
        std::this_thread::sleep_until(next);
    }
}

long file_size(const char* p) {
    struct stat st;
    return ::stat(p, &st) == 0 ? (long)st.st_size : -1;
}

}  // namespace

TEST(speak_api_typed_ask_is_spoken) {
    std::remove(kWav);
    Events ev;
    void* h = open_speak(ev);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_ask(h, kShort, 60) == 0);
    size_t a = 0, b = 0, c = 0;
    json start, done, end;
    CHECK(ev.wait("sound_start", &start, &a));
    CHECK(status(h)["talking"] == true);
    CHECK(status(h)["muted"] == true);
    CHECK(ev.wait("done", &done, &b));
    CHECK(ev.wait("sound_end", &end, &c, 30000));
    std::printf("  frames %d frame_ms %.1f codec_ms %.1f sound_ms %.0f played %.0f gaps %d prebuffer %d\n",
                done.value("frames", -1), done.value("frame_ms", 0.0), done.value("codec_ms", 0.0),
                done.value("sound_ms", 0.0), end.value("sound_ms", 0.0), end.value("gaps", -1),
                status(h).value("prebuffer_ms", -1));
    CHECK(a < b);  // sound starts while the answer is still being made
    CHECK(done.value("frames", 0) >= 12);
    CHECK(end["cut"] == false);
    CHECK(end.value("sound_ms", 0.0) >= done.value("sound_ms", 0.0) - 100);  // all of it played
    CHECK(!start.contains("voice"));
    CHECK(status(h)["talking"] == false);
    const double played = end.value("sound_ms", 0.0);
    ce_close(h);
    const long bytes = file_size(kWav);
    std::printf("  wav %ld bytes\n", bytes);
    CHECK(bytes >= 44 + (long)(played * 48 * 0.95));
}

TEST(speak_api_cancel_stops_sound) {
    Events ev;
    void* h = open_speak(ev);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_ask(h, kLong, 300) == 0);
    size_t at = 0;
    json start, end, done;
    CHECK(ev.wait("sound_start", &start, &at));
    std::this_thread::sleep_for(milliseconds(500));
    const double t = now_ms();
    CHECK(ce_cancel(h) == 0);
    CHECK(ev.wait("sound_end", &end, &at, 2000));
    const double after = end.value("_rx_ms", 0.0) - t;
    std::printf("  sound_end %.0f ms after cancel, played %.0f ms\n", after, end.value("sound_ms", 0.0));
    CHECK(after < 200);
    CHECK(end["cut"] == true);
    CHECK(status(h)["talking"] == false);
    size_t d = 0;
    CHECK(ev.wait("done", &done, &d));
    CHECK(done["cancelled"] == true);
    ce_close(h);
}

TEST(speak_api_new_ask_cuts_playout) {
    Events ev;
    void* h = open_speak(ev);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_ask(h, kLong, 200) == 0);
    size_t at = 0;
    json done, end, start;
    CHECK(ev.wait("done", &done, &at, 60000));
    const bool talking = status(h)["talking"] == true;  // the audio lags the LM: it is still playing
    std::printf("  first answer %d frames, talking at done: %d\n", done.value("frames", 0), (int)talking);
    CHECK(talking);
    const size_t mark = ev.size();
    CHECK(ce_ask(h, kShort, 60) == 0);
    size_t m = mark;
    CHECK(ev.wait("sound_end", &end, &m));
    CHECK(end["cut"] == true);
    CHECK(ev.wait("sound_start", &start, &m));  // the second answer is heard
    CHECK(ev.wait("done", &done, &m));
    ce_close(h);
}

TEST(speak_api_mic_muted_while_talking) {
    Events ev;
    void* h = open_speak(ev);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_set_listening(h, 1) == 0);
    CHECK(ce_ask(h, kLong, 300) == 0);
    size_t at = 0;
    json start, end;
    CHECK(ev.wait("sound_start", &start, &at));
    CHECK(status(h)["muted"] == true);
    const size_t mark = ev.size();
    play(h, wav("question1"));  // the user talks while Cortex talks: not heard
    CHECK(ev.count("speech_start", mark) == 0);
    CHECK(ce_cancel(h) == 0);
    CHECK(ev.wait("sound_end", &end, &at, 2000));
    CHECK(status(h)["muted"] == true);  // the tail: the room still rings
    std::this_thread::sleep_for(milliseconds(300 + 150));
    CHECK(status(h)["muted"] == false);
    json done, sp;
    size_t d = 0;
    CHECK(ev.wait("done", &done, &d));
    const size_t mark2 = ev.size();
    play(h, wav("question1"));  // heard again
    size_t m = mark2;
    CHECK(ev.wait("speech_start", &sp, &m, 5000));
    ce_close(h);
}

TEST(speak_api_zero_audio_answer_unmutes) {
    Events ev;
    void* h = open_speak(ev);
    CHECK(h != nullptr);
    if (!h) return;
    CHECK(ce_ask(h, kShort, 1) == 0);  // one text token: the answer ends before any audio
    size_t at = 0;
    json done, end;
    CHECK(ev.wait("done", &done, &at));
    size_t s = 0;
    CHECK(ev.wait("sound_end", &end, &s, 3000));
    std::printf("  frames %d, sound_end played %.0f ms\n", done.value("frames", -1), end.value("sound_ms", -1.0));
    CHECK(done.value("frames", -1) == 0);
    CHECK(ev.count("sound_start") == 0);
    std::this_thread::sleep_for(milliseconds(300 + 150));
    CHECK(status(h)["muted"] == false);
    CHECK(status(h)["talking"] == false);
    ce_close(h);
}

TEST(speak_api_bad_speaker_falls_back_to_text) {
    Events ev;
    void* h = ce_open(config(",\"speak\":true,\"speaker_device\":\"plughw:9,9\"").c_str(), &Events::cb, &ev);
    CHECK(h != nullptr);
    if (!h) return;
    size_t at = 0;
    json err, done;
    CHECK(ev.wait("error", &err, &at, 1000));
    std::printf("  %s\n", err.value("what", std::string()).c_str());
    CHECK(err.value("what", std::string()).rfind("speaker:", 0) == 0);
    CHECK(ce_ask(h, kShort, 40) == 0);
    size_t d = 0;
    CHECK(ev.wait("done", &done, &d));
    CHECK(done.value("frames", -1) == 0);
    CHECK(done.value("n_out", 0) > 0);
    CHECK(ev.count("token") > 0);
    CHECK(ev.count("sound_start") == 0);
    CHECK(status(h)["muted"] == false);
    ce_close(h);
}

TEST(speak_api_spoken_question_end_to_sound) {
    Events ev;
    void* h = open_speak(ev, ",\"max_tokens\":40");
    CHECK(h != nullptr);
    if (!h) return;
    size_t at = 0;
    json view, se, start, done;
    CHECK(show(h, ev, "t001", 1, &view, &at));
    CHECK(ce_set_listening(h, 1) == 0);
    play(h, wav("question1"));
    std::vector<float> quiet(16000 * 2, 0.0f);
    play(h, quiet);
    CHECK(ev.wait("speech_end", &se, &at, 10000));
    CHECK(ev.wait("sound_start", &start, &at, 10000));
    size_t d = at;
    CHECK(ev.wait("done", &done, &d, 30000));
    const double e2s = start.value("end_to_sound_ms", -1.0);
    std::printf("  end_to_sound %.0f ms (sound_start), %.0f ms (done), end_to_first %.0f ms\n", e2s,
                done.value("end_to_sound_ms", -1.0), done.value("end_to_first_ms", -1.0));
    CHECK(start["voice"] == true);
    CHECK(done["voice"] == true);
    CHECK(e2s > 0 && e2s < 1000);
    ce_close(h);
}

TEST(speak_api_view_encoded_during_answer) {
    Events ev;
    void* h = open_speak(ev);
    CHECK(h != nullptr);
    if (!h) return;
    size_t at = 0;
    json view, start, done;
    CHECK(show(h, ev, "t001", 1, &view, &at));
    CHECK(ce_ask(h, kLong, 300) == 0);
    CHECK(ev.wait("sound_start", &start, &at));
    std::vector<uint8_t> px;
    int w = 0, hh = 0;
    CHECK(api_test::load_rgb("t008", &px, &w, &hh));
    CHECK(ce_push_frame(h, px.data(), w, hh, 8) == 0);
    CHECK(ce_refresh(h) == 0);
    size_t d = at, v = at;
    CHECK(ev.wait("done", &done, &d, 60000));
    CHECK(ev.wait("view", &view, &v, 20000));
    // the encode ran on the small cores during the answer: after done only the read is left
    const double lag = view.value("_rx_ms", 0.0) - done.value("_rx_ms", 0.0);
    std::printf("  view %ld encode %.0f ms, read %.0f ms, %.0f ms after done (answer %.0f ms)\n",
                view.value("frame_id", -1L), view.value("encode_ms", 0.0), view.value("read_ms", 0.0), lag,
                done.value("total_ms", 0.0));
    CHECK(view.value("frame_id", -1L) == 8);
    CHECK(lag < view.value("read_ms", 0.0) + 300);
    ce_close(h);
}
