// Cortex's voice out: a ring of 24 kHz mono PCM and a writer thread that plays it on a sink as it arrives.
//
// Playback of an answer starts once `prebuffer` of audio is queued (or the answer's audio is complete). A ring that
// runs dry mid-answer is a gap (the device underruns): playback pauses until rebuffer_ms is queued again, so a
// producer slower than real time costs a rare pause instead of a stutter every few periods. An answer with a gap
// raises the next answer's prebuffer by 100 ms (cap 800), three gapless answers lower it by 50 ms (floor: the
// configured value).
//
// Sinks: "null" (paced at real time, discards), "wav:<path>" (paced, writes a 16-bit WAV), else an ALSA device. ALSA
// is loaded with dlopen("libasound.so.2") (no headers on the box); opening it also applies the UCM verb/device that
// route the codec to the headphone jack and the mixer values, so a reboot never leaves the jack silent.
#pragma once
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace ce {

struct SpeakerConfig {
    std::string device = "plughw:0,0", ucm_card = "hw:0", ucm_verb = "HiFi", ucm_device = "Headphones";
    std::vector<std::pair<std::string, int>> mixer = {{"HPHL Volume", 20}, {"HPHR Volume", 20}};  // 20 = 0 dB (0..24, -30 dB + 1.5 dB/step)
    int prebuffer_ms = 200, rate = 24000;
    // after the ring runs dry mid-answer, playback resumes once this much is queued again (or the answer is complete)
    int rebuffer_ms = 1000;
    std::vector<int> cpus = {3};
};

class Sink {  // a blocking writer, like ALSA
public:
    virtual ~Sink() = default;
    virtual int write(const int16_t* s, int n) = 0;  // frames written; < 0 = a device error it could not recover
    virtual void drop() = 0;                          // discard what the device still holds
};

std::unique_ptr<Sink> open_sink(const SpeakerConfig& c, std::string* err);

struct SoundEvent {
    std::string type;  // "sound_start" | "sound_end"
    double at_ms = 0;  // steady_clock ms
    double sound_ms = 0;
    int gaps = 0;
    bool cut = false;
};

class Speaker {
public:
    Speaker(const SpeakerConfig& c, std::unique_ptr<Sink> sink, std::function<void(const SoundEvent&)> on_event);
    ~Speaker();
    Speaker(const Speaker&) = delete;
    Speaker& operator=(const Speaker&) = delete;
    void begin();                        // a new answer (cuts audio still playing, like stop())
    void push(const float* pcm, int n);  // float [-1, 1], 24 kHz
    void end();                          // the answer's audio is complete: play out, then sound_end
    void stop();                         // cut now
    bool playing() const;
    int prebuffer_ms() const;

private:
    void run();
    void cut_locked(std::vector<SoundEvent>* out);
    void finish_locked(std::vector<SoundEvent>* out);
    void emit(const std::vector<SoundEvent>& evs);

    SpeakerConfig c_;
    std::unique_ptr<Sink> sink_;
    std::function<void(const SoundEvent&)> on_event_;
    mutable std::mutex mu_;
    std::condition_variable cv_;
    std::vector<int16_t> ring_;
    size_t head_ = 0, n_ = 0;  // read index, queued samples
    bool active_ = false, started_ = false, ended_ = false, dry_ = false, drop_ = false, quit_ = false;
    long written_ = 0;  // samples of this answer handed to the sink
    int gaps_ = 0, prebuffer_ms_, clean_ = 0;
    long gen_ = 0;  // bumped by every cut, so a write in flight is not counted into the next answer
    std::thread th_;
};

}  // namespace ce
