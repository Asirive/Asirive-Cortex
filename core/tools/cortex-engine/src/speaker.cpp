#include "speaker.h"

#include <dlfcn.h>
#include <pthread.h>
#include <sched.h>

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <type_traits>

namespace ce {
namespace {

using clk = std::chrono::steady_clock;

double now_ms() { return std::chrono::duration<double, std::milli>(clk::now().time_since_epoch()).count(); }

void pin(const std::vector<int>& cpus) {
    if (cpus.empty()) return;
    cpu_set_t set;
    CPU_ZERO(&set);
    for (int c : cpus) CPU_SET(c, &set);
    pthread_setaffinity_np(pthread_self(), sizeof set, &set);
}

// Real-time pacing for the sinks that have no device clock.
struct Pacer {
    int rate;
    clk::time_point next{};
    explicit Pacer(int r) : rate(r) {}
    void after(int n) {
        auto t = clk::now();
        if (next < t) next = t;  // idle since the last write: start from now
        next += std::chrono::microseconds((long)n * 1000000 / rate);
        std::this_thread::sleep_until(next);
    }
    void reset() { next = {}; }
};

struct NullSink : Sink {
    Pacer p;
    explicit NullSink(int rate) : p(rate) {}
    int write(const int16_t*, int n) override { return p.after(n), n; }
    void drop() override { p.reset(); }
};

struct WavSink : Sink {
    std::FILE* f;
    int rate;
    uint32_t bytes = 0;
    Pacer p;
    WavSink(std::FILE* fp, int r) : f(fp), rate(r), p(r) { header(); }
    ~WavSink() override {
        header();
        std::fclose(f);
    }
    void header() {
        auto u32 = [](unsigned char* b, uint32_t v) { std::memcpy(b, &v, 4); };
        auto u16 = [](unsigned char* b, uint16_t v) { std::memcpy(b, &v, 2); };
        unsigned char h[44];
        std::memcpy(h, "RIFF", 4), u32(h + 4, 36 + bytes), std::memcpy(h + 8, "WAVEfmt ", 8);
        u32(h + 16, 16), u16(h + 20, 1), u16(h + 22, 1), u32(h + 24, rate), u32(h + 28, rate * 2);
        u16(h + 32, 2), u16(h + 34, 16), std::memcpy(h + 36, "data", 4), u32(h + 40, bytes);
        std::fseek(f, 0, SEEK_SET);
        std::fwrite(h, 1, 44, f);
        std::fseek(f, 0, SEEK_END);
    }
    int write(const int16_t* s, int n) override {
        std::fwrite(s, 2, n, f);
        bytes += 2 * n;
        p.after(n);
        return n;
    }
    void drop() override { p.reset(); }
};

// ---- ALSA through dlopen: the box has libasound.so.2 but no headers, so the few calls are declared here.
struct snd_pcm_t;
struct snd_use_case_mgr_t;
struct snd_ctl_t;
struct snd_ctl_elem_id_t;
struct snd_ctl_elem_value_t;
constexpr int kPlayback = 0, kS16LE = 2, kRwInterleaved = 3, kIfaceMixer = 2;

struct Alsa {
    void* lib = nullptr;
    int (*pcm_open)(snd_pcm_t**, const char*, int, int);
    int (*pcm_set_params)(snd_pcm_t*, int, int, unsigned, unsigned, int, unsigned);
    long (*pcm_writei)(snd_pcm_t*, const void*, unsigned long);
    int (*pcm_recover)(snd_pcm_t*, int, int);
    int (*pcm_drop)(snd_pcm_t*);
    int (*pcm_prepare)(snd_pcm_t*);
    int (*pcm_close)(snd_pcm_t*);
    const char* (*strerror)(int);
    int (*ucm_open)(snd_use_case_mgr_t**, const char*);
    int (*ucm_set)(snd_use_case_mgr_t*, const char*, const char*);
    int (*ucm_close)(snd_use_case_mgr_t*);
    int (*ctl_open)(snd_ctl_t**, const char*, int);
    int (*ctl_close)(snd_ctl_t*);
    int (*id_malloc)(snd_ctl_elem_id_t**);
    void (*id_free)(snd_ctl_elem_id_t*);
    void (*id_set_interface)(snd_ctl_elem_id_t*, int);
    void (*id_set_name)(snd_ctl_elem_id_t*, const char*);
    int (*val_malloc)(snd_ctl_elem_value_t**);
    void (*val_free)(snd_ctl_elem_value_t*);
    void (*val_set_id)(snd_ctl_elem_value_t*, const snd_ctl_elem_id_t*);
    void (*val_set_integer)(snd_ctl_elem_value_t*, unsigned, long);
    int (*elem_read)(snd_ctl_t*, snd_ctl_elem_value_t*);
    int (*elem_write)(snd_ctl_t*, snd_ctl_elem_value_t*);

    bool load(std::string* err) {
        lib = dlopen("libasound.so.2", RTLD_NOW | RTLD_LOCAL);
        if (!lib) return *err = std::string("dlopen libasound.so.2: ") + dlerror(), false;
        bool ok = true;
        auto sym = [&](auto& fn, const char* name) {
            fn = reinterpret_cast<std::remove_reference_t<decltype(fn)>>(dlsym(lib, name));
            if (!fn) ok = false, *err = std::string("libasound: no ") + name;
        };
        sym(pcm_open, "snd_pcm_open"), sym(pcm_set_params, "snd_pcm_set_params");
        sym(pcm_writei, "snd_pcm_writei"), sym(pcm_recover, "snd_pcm_recover"), sym(pcm_drop, "snd_pcm_drop");
        sym(pcm_prepare, "snd_pcm_prepare"), sym(pcm_close, "snd_pcm_close"), sym(strerror, "snd_strerror");
        sym(ucm_open, "snd_use_case_mgr_open"), sym(ucm_set, "snd_use_case_set");
        sym(ucm_close, "snd_use_case_mgr_close");
        sym(ctl_open, "snd_ctl_open"), sym(ctl_close, "snd_ctl_close");
        sym(id_malloc, "snd_ctl_elem_id_malloc"), sym(id_free, "snd_ctl_elem_id_free");
        sym(id_set_interface, "snd_ctl_elem_id_set_interface"), sym(id_set_name, "snd_ctl_elem_id_set_name");
        sym(val_malloc, "snd_ctl_elem_value_malloc"), sym(val_free, "snd_ctl_elem_value_free");
        sym(val_set_id, "snd_ctl_elem_value_set_id"), sym(val_set_integer, "snd_ctl_elem_value_set_integer");
        sym(elem_read, "snd_ctl_elem_read"), sym(elem_write, "snd_ctl_elem_write");
        return ok;
    }
};

struct AlsaSink : Sink {
    Alsa a;
    snd_pcm_t* pcm = nullptr;
    snd_use_case_mgr_t* ucm = nullptr;
    ~AlsaSink() override {
        if (pcm) a.pcm_close(pcm);
        if (ucm) a.ucm_close(ucm);
        if (a.lib) dlclose(a.lib);
    }
    // Route and volume first (best effort: a card without UCM still plays), then the PCM.
    bool open(const SpeakerConfig& c, std::string* err) {
        if (!a.load(err)) return false;
        std::string notes;
        if (!c.ucm_card.empty() && !c.ucm_verb.empty()) {
            int r = a.ucm_open(&ucm, c.ucm_card.c_str());
            if (r < 0) notes += " ucm open: " + std::string(a.strerror(r)) + ";", ucm = nullptr;
            if (ucm && (r = a.ucm_set(ucm, "_verb", c.ucm_verb.c_str())) < 0)
                notes += " ucm verb: " + std::string(a.strerror(r)) + ";";
            if (ucm && !c.ucm_device.empty() && (r = a.ucm_set(ucm, "_enadev", c.ucm_device.c_str())) < 0)
                notes += " ucm device: " + std::string(a.strerror(r)) + ";";
        }
        if (!c.mixer.empty()) {
            snd_ctl_t* ctl = nullptr;
            const std::string card = c.ucm_card.empty() ? "hw:0" : c.ucm_card;
            if (a.ctl_open(&ctl, card.c_str(), 0) >= 0) {
                snd_ctl_elem_id_t* id;
                snd_ctl_elem_value_t* v;
                a.id_malloc(&id), a.val_malloc(&v);
                for (auto& [name, value] : c.mixer) {
                    a.id_set_interface(id, kIfaceMixer);
                    a.id_set_name(id, name.c_str());
                    a.val_set_id(v, id);
                    int r = a.elem_read(ctl, v);
                    if (r >= 0) {
                        for (unsigned ch = 0; ch < 2; ch++) a.val_set_integer(v, ch, value);
                        r = a.elem_write(ctl, v);
                    }
                    if (r < 0) notes += " mixer " + name + ": " + a.strerror(r) + ";";
                }
                a.val_free(v), a.id_free(id);
                a.ctl_close(ctl);
            }
        }
        int r = a.pcm_open(&pcm, c.device.c_str(), kPlayback, 0);
        if (r < 0) return pcm = nullptr, *err = c.device + ": " + a.strerror(r) + notes, false;
        r = a.pcm_set_params(pcm, kS16LE, kRwInterleaved, 1, c.rate, 1, 80000);
        if (r < 0) return *err = c.device + " set_params: " + a.strerror(r) + notes, false;
        if (!notes.empty()) std::fprintf(stderr, "speaker:%s\n", notes.c_str());
        return true;
    }
    int write(const int16_t* s, int n) override {
        int done = 0;
        while (done < n) {
            long r = a.pcm_writei(pcm, s + done, n - done);
            if (r < 0) {
                r = a.pcm_recover(pcm, (int)r, 1);  // an underrun (EPIPE) between answers or after a gap
                if (r < 0) return (int)r;
                continue;
            }
            done += (int)r;
        }
        return done;
    }
    void drop() override {
        a.pcm_drop(pcm);
        a.pcm_prepare(pcm);
    }
};

}  // namespace

std::unique_ptr<Sink> open_sink(const SpeakerConfig& c, std::string* err) {
    if (c.device == "null") return std::make_unique<NullSink>(c.rate);
    if (c.device.rfind("wav:", 0) == 0) {
        std::FILE* f = std::fopen(c.device.c_str() + 4, "wb");
        if (!f) return *err = c.device + ": " + std::strerror(errno), nullptr;
        return std::make_unique<WavSink>(f, c.rate);
    }
    auto s = std::make_unique<AlsaSink>();
    if (!s->open(c, err)) return nullptr;
    return s;
}

Speaker::Speaker(const SpeakerConfig& c, std::unique_ptr<Sink> sink, std::function<void(const SoundEvent&)> on_event)
    : c_(c), sink_(std::move(sink)), on_event_(std::move(on_event)), ring_((size_t)c.rate * 30),
      prebuffer_ms_(c.prebuffer_ms) {
    th_ = std::thread([this] { run(); });
}

Speaker::~Speaker() {
    {
        std::lock_guard<std::mutex> g(mu_);
        quit_ = true;
    }
    cv_.notify_all();
    th_.join();
}

// Events are emitted under mu_ so they keep their order; on_event must not call back into the Speaker.
void Speaker::emit(const std::vector<SoundEvent>& evs) {
    for (auto& e : evs)
        if (on_event_) on_event_(e);
}

void Speaker::cut_locked(std::vector<SoundEvent>* out) {
    if (!active_) return;
    SoundEvent e{"sound_end", now_ms(), written_ * 1000.0 / c_.rate, gaps_, true};
    out->push_back(e);
    if (gaps_ > 0) prebuffer_ms_ = std::min(800, prebuffer_ms_ + 100), clean_ = 0;
    drop_ = drop_ || started_;
    active_ = started_ = false;
    head_ = n_ = 0;
    ++gen_;
}

void Speaker::finish_locked(std::vector<SoundEvent>* out) {
    out->push_back({"sound_end", now_ms(), written_ * 1000.0 / c_.rate, gaps_, false});
    if (gaps_ > 0) {
        prebuffer_ms_ = std::min(800, prebuffer_ms_ + 100), clean_ = 0;
    } else if (++clean_ >= 3) {
        prebuffer_ms_ = std::max(c_.prebuffer_ms, prebuffer_ms_ - 50), clean_ = 0;
    }
    active_ = started_ = false;
}

void Speaker::begin() {
    std::lock_guard<std::mutex> g(mu_);
    std::vector<SoundEvent> evs;
    cut_locked(&evs);
    emit(evs);
    active_ = true;
    started_ = ended_ = dry_ = false;
    written_ = 0, gaps_ = 0;
    head_ = n_ = 0;
    cv_.notify_all();
}

void Speaker::push(const float* pcm, int n) {
    std::lock_guard<std::mutex> g(mu_);
    if (!active_ || ended_) return;
    const size_t cap = ring_.size();
    for (int i = 0; i < n && n_ < cap; i++, n_++) {
        float x = std::max(-1.0f, std::min(1.0f, pcm[i]));
        ring_[(head_ + n_) % cap] = (int16_t)std::lrintf(x * 32767.0f);
    }
    cv_.notify_all();
}

void Speaker::end() {
    std::lock_guard<std::mutex> g(mu_);
    if (active_) ended_ = true;
    cv_.notify_all();
}

void Speaker::stop() {
    std::lock_guard<std::mutex> g(mu_);
    std::vector<SoundEvent> evs;
    cut_locked(&evs);
    emit(evs);
    cv_.notify_all();
}

bool Speaker::playing() const {
    std::lock_guard<std::mutex> g(mu_);
    return active_ && started_;
}

int Speaker::prebuffer_ms() const {
    std::lock_guard<std::mutex> g(mu_);
    return prebuffer_ms_;
}

void Speaker::run() {
    pin(c_.cpus);
    const int period = c_.rate / 50;  // 20 ms
    std::vector<int16_t> buf(period);
    std::unique_lock<std::mutex> l(mu_);
    while (!quit_) {
        if (drop_) {
            drop_ = false;
            l.unlock();
            sink_->drop();
            l.lock();
            continue;
        }
        if (!active_) {
            cv_.wait(l);
            continue;
        }
        std::vector<SoundEvent> evs;
        if (!started_) {
            if (n_ < (size_t)prebuffer_ms_ * c_.rate / 1000 && !ended_) {
                cv_.wait(l);
                continue;
            }
            if (n_ == 0) {  // complete and empty: an answer with no audio
                finish_locked(&evs);
                emit(evs);
                continue;
            }
            started_ = true;
            evs.push_back({"sound_start", now_ms(), 0, 0, false});
            emit(evs);
        }
        if (n_ == 0) {
            if (ended_) {
                finish_locked(&evs);
                emit(evs);
                continue;
            }
            if (!dry_) dry_ = true, ++gaps_;
            cv_.wait(l);
            continue;
        }
        if (dry_) {  // ran dry: wait for a lead again, so a slow producer is a rare pause, not a stutter
            const size_t lead = (size_t)std::max(c_.rebuffer_ms, prebuffer_ms_) * c_.rate / 1000;
            if (n_ < lead && !ended_) {
                cv_.wait(l);
                continue;
            }
            dry_ = false;
        }
        const int k = (int)std::min<size_t>(n_, period);
        const size_t cap = ring_.size();
        for (int i = 0; i < k; i++) buf[i] = ring_[(head_ + i) % cap];
        head_ = (head_ + k) % cap, n_ -= k;
        const long g = gen_;
        l.unlock();
        int r = sink_->write(buf.data(), k);
        l.lock();
        if (g == gen_ && r > 0) written_ += r;
        if (r < 0) std::fprintf(stderr, "speaker: write failed (%d)\n", r);
    }
}

}  // namespace ce
