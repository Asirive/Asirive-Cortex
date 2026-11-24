#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <thread>
#include <vector>

#include "../src/speaker.h"
#include "check.h"

using namespace std::chrono;

namespace {

// Plays at `speed` x real time and keeps every sample it got.
struct FakeSink : ce::Sink {
    double speed;
    std::mutex mu;
    std::vector<int16_t> got;
    int drops = 0;
    explicit FakeSink(double s) : speed(s) {}
    int write(const int16_t* s, int n) override {
        std::this_thread::sleep_for(microseconds((long)(n * 1e6 / 24000 / speed)));
        std::lock_guard<std::mutex> g(mu);
        got.insert(got.end(), s, s + n);
        return n;
    }
    void drop() override {
        std::lock_guard<std::mutex> g(mu);
        ++drops;
    }
    size_t n() {
        std::lock_guard<std::mutex> g(mu);
        return got.size();
    }
};

struct Rec {
    std::mutex mu;
    std::condition_variable cv;
    std::vector<ce::SoundEvent> ev;
    void on(const ce::SoundEvent& e) {
        { std::lock_guard<std::mutex> g(mu); ev.push_back(e); }
        cv.notify_all();
    }
    int count(const char* type) {
        std::lock_guard<std::mutex> g(mu);
        int n = 0;
        for (auto& e : ev) n += e.type == type;
        return n;
    }
    // waits for the n-th (1-based) event of this type
    bool wait(const char* type, int nth, ce::SoundEvent* out, int timeout_ms) {
        std::unique_lock<std::mutex> l(mu);
        return cv.wait_for(l, milliseconds(timeout_ms), [&] {
            int n = 0;
            for (auto& e : ev)
                if (e.type == type && ++n == nth) {
                    if (out) *out = e;
                    return true;
                }
            return false;
        });
    }
};

std::vector<float> tone(int ms, float amp = 0.3f) {
    std::vector<float> v(ms * 24);
    for (size_t i = 0; i < v.size(); i++) v[i] = amp * std::sin(2 * M_PI * 440 * i / 24000.0);
    return v;
}

struct Rig {
    FakeSink* sink;
    Rec rec;
    std::unique_ptr<ce::Speaker> spk;
    explicit Rig(double speed = 1.0, int prebuffer_ms = 200) {
        ce::SpeakerConfig c;
        c.prebuffer_ms = prebuffer_ms;
        auto s = std::make_unique<FakeSink>(speed);
        sink = s.get();
        spk = std::make_unique<ce::Speaker>(c, std::move(s), [this](const ce::SoundEvent& e) { rec.on(e); });
    }
    void push(const std::vector<float>& v) { spk->push(v.data(), (int)v.size()); }
};

}  // namespace

TEST(speaker_waits_for_prebuffer) {
    Rig r;
    r.spk->begin();
    r.push(tone(150));
    std::this_thread::sleep_for(milliseconds(100));
    CHECK(r.rec.count("sound_start") == 0);
    r.push(tone(100));
    CHECK(r.rec.wait("sound_start", 1, nullptr, 50));
    CHECK(r.spk->playing());
    r.spk->end();
    ce::SoundEvent e;
    CHECK(r.rec.wait("sound_end", 1, &e, 1000));
    CHECK_NEAR(e.sound_ms, 250, 5);
    CHECK(e.gaps == 0 && !e.cut);
    CHECK(!r.spk->playing());
}

TEST(speaker_short_answer_plays_on_end) {
    Rig r;
    r.spk->begin();
    r.push(tone(80));
    r.spk->end();
    ce::SoundEvent e;
    CHECK(r.rec.wait("sound_start", 1, nullptr, 100));
    CHECK(r.rec.wait("sound_end", 1, &e, 500));
    CHECK_NEAR(e.sound_ms, 80, 1);
}

TEST(speaker_zero_audio_answer) {
    Rig r;
    r.spk->begin();
    r.spk->end();
    ce::SoundEvent e;
    CHECK(r.rec.wait("sound_end", 1, &e, 200));
    CHECK(e.sound_ms == 0 && !e.cut && e.gaps == 0);
    CHECK(r.rec.count("sound_start") == 0);
}

TEST(speaker_stop_cuts_now) {
    Rig r;
    r.spk->begin();
    r.push(tone(2000));
    CHECK(r.rec.wait("sound_start", 1, nullptr, 100));
    std::this_thread::sleep_for(milliseconds(200));
    auto t0 = steady_clock::now();
    r.spk->stop();
    ce::SoundEvent e;
    CHECK(r.rec.wait("sound_end", 1, &e, 50));
    const double cut_ms = duration<double, std::milli>(steady_clock::now() - t0).count();
    CHECK(cut_ms < 50);
    CHECK(e.cut);
    CHECK(!r.spk->playing());
    std::this_thread::sleep_for(milliseconds(100));
    CHECK(r.sink->n() < 24000);  // < 1 s reached the device
    CHECK(r.sink->drops >= 1);
}

TEST(speaker_begin_cuts_previous) {
    Rig r;
    r.spk->begin();
    r.push(tone(2000));
    CHECK(r.rec.wait("sound_start", 1, nullptr, 100));
    r.spk->begin();
    ce::SoundEvent e;
    CHECK(r.rec.wait("sound_end", 1, &e, 50));
    CHECK(e.cut);
    r.push(tone(80));
    r.spk->end();
    CHECK(r.rec.wait("sound_end", 2, &e, 500));
    CHECK(!e.cut);
    CHECK_NEAR(e.sound_ms, 80, 1);
}

TEST(speaker_dry_ring_counts_gap_and_grows_prebuffer) {
    Rig r;
    ce::SoundEvent e;
    r.spk->begin();
    r.push(tone(200));
    std::this_thread::sleep_for(milliseconds(400));
    r.push(tone(200));
    r.spk->end();
    CHECK(r.rec.wait("sound_end", 1, &e, 1000));
    CHECK(e.gaps == 1);
    CHECK(r.spk->prebuffer_ms() == 300);
    for (int i = 0; i < 3; i++) {  // three gapless answers shrink it by 50
        r.spk->begin();
        r.push(tone(100));
        r.spk->end();
        CHECK(r.rec.wait("sound_end", 2 + i, &e, 1000));
        CHECK(e.gaps == 0);
    }
    CHECK(r.spk->prebuffer_ms() == 250);
}

TEST(speaker_prebuffer_caps_at_800) {
    Rig r(20.0);  // 20x real time
    ce::SoundEvent e;
    for (int i = 0; i < 7; i++) {
        r.spk->begin();
        r.push(tone(r.spk->prebuffer_ms()));
        std::this_thread::sleep_for(milliseconds(100));  // plays out and runs dry
        r.push(tone(20));
        r.spk->end();
        CHECK(r.rec.wait("sound_end", 1 + i, &e, 1000));
        CHECK(e.gaps == 1);
    }
    CHECK(r.spk->prebuffer_ms() == 800);
}

TEST(speaker_float_to_s16_clips) {
    Rig r;
    r.spk->begin();
    float v[3] = {2.0f, -2.0f, 0.5f};
    r.spk->push(v, 3);
    r.spk->end();
    CHECK(r.rec.wait("sound_end", 1, nullptr, 200));
    std::lock_guard<std::mutex> g(r.sink->mu);
    CHECK(r.sink->got.size() == 3);
    if (r.sink->got.size() == 3) {
        CHECK(r.sink->got[0] == 32767);
        CHECK(r.sink->got[1] == -32767);
        CHECK(r.sink->got[2] == 16384 || r.sink->got[2] == 16383);
    }
}

TEST(speaker_wav_sink_writes_valid_file) {
    const char* path = "/tmp/ce_spk.wav";
    std::remove(path);
    {
        ce::SpeakerConfig c;
        c.device = std::string("wav:") + path;
        std::string err;
        auto sink = ce::open_sink(c, &err);
        CHECK(sink != nullptr);
        if (!sink) return;
        Rec rec;
        ce::Speaker spk(c, std::move(sink), [&](const ce::SoundEvent& e) { rec.on(e); });
        spk.begin();
        auto t = tone(500);
        spk.push(t.data(), (int)t.size());
        spk.end();
        CHECK(rec.wait("sound_end", 1, nullptr, 2000));
    }
    std::ifstream f(path, std::ios::binary);
    std::vector<char> b((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    CHECK(b.size() == 44 + 24000);
    if (b.size() < 44) return;
    uint32_t rate;
    uint16_t ch, bits;
    std::memcpy(&ch, &b[22], 2);
    std::memcpy(&rate, &b[24], 4);
    std::memcpy(&bits, &b[34], 2);
    CHECK(std::memcmp(&b[0], "RIFF", 4) == 0 && std::memcmp(&b[8], "WAVE", 4) == 0);
    CHECK(rate == 24000 && ch == 1 && bits == 16);
}

// By ear: CE_SPEAKER_DEVICE=plughw:0,0 engine_tests speaker_alsa_tone  (skipped without the variable)
TEST(speaker_alsa_tone) {
    const char* dev = std::getenv("CE_SPEAKER_DEVICE");
    if (!dev) {
        std::printf("  skipped (set CE_SPEAKER_DEVICE)\n");
        return;
    }
    ce::SpeakerConfig c;
    c.device = dev;
    std::string err;
    auto sink = ce::open_sink(c, &err);
    if (!sink) std::printf("  open: %s\n", err.c_str());
    CHECK(sink != nullptr);
    if (!sink) return;
    Rec rec;
    ce::Speaker spk(c, std::move(sink), [&](const ce::SoundEvent& e) { rec.on(e); });
    spk.begin();
    auto t = tone(1000);
    spk.push(t.data(), (int)t.size());
    spk.end();
    ce::SoundEvent e;
    CHECK(rec.wait("sound_end", 1, &e, 3000));
    std::printf("  sound_ms %.0f gaps %d\n", e.sound_ms, e.gaps);
    CHECK(e.gaps == 0);
}
