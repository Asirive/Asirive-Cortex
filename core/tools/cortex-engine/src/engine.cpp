// The engine's scheduler behind the C API.
//
//   control thread (vision_cpus)  frame -> prepare -> NPU + islands -> skip check -> Lm::read_view (background)
//   LM worker      (lm_cpus)      asks, one at a time; an ask preempts a background read (Lm) and holds the big cores
//                                 for its whole answer (BigCores gate): islands that come meanwhile run on
//                                 island_small_cpus instead of waiting, so the view keeps moving while Cortex speaks.
//                                 Also decodes the audio rows of an utterance into S while the user talks.
//   audio thread   (audio_cpus)   pushed PCM -> VAD (Listener) -> audio encoder (AudioIn) -> rows to the worker.
//                                 It never calls llama_decode, so it is never pinned to an LM core.
//   codec thread   (codec_cpus)   speech codes -> PCM behind the LM, on its own mtmd context (Lm's CodecThread).
//   speaker thread (speaker_cpus) PCM ring -> headphone jack, paced by the device (Speaker).
// Every answer is spoken (speak): the mic is muted from the answer's start until echo_lag + mute_tail_ms after its
// sound ends, and ce_cancel / a new answer cut the sound at once. echo_lag is how late the mic hears Cortex's own
// voice (device buffer + earbuds + capture path, ~450 ms on the box); the audio thread measures it at every answer
// (the first loud mic chunk after the answer's first loud sample is played), so the user is heard as soon as the
// echo is over, and never the echo.
//
// Each thread opens its own part (Vision::shared on control, Lm::open on the worker) because ggml pins the thread
// that creates or drives a threadpool to the pool's first core; the caller of ce_open is never pinned.
#include "cortex_engine.h"

#include <pthread.h>
#include <sched.h>
#include <sys/syscall.h>
#include <unistd.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <nlohmann/json.hpp>
#include <string>
#include <thread>
#include <vector>

#include "audio_in.h"
#include "big_cores.h"
#include "lm.h"
#include "prep.h"
#include "speaker.h"
#include "vad.h"
#include "vision.h"

using nlohmann::json;

namespace ce {
namespace {

using clk = std::chrono::steady_clock;
double ms_since(clk::time_point t) { return std::chrono::duration<double, std::milli>(clk::now() - t).count(); }
double now_steady_ms() { return std::chrono::duration<double, std::milli>(clk::now().time_since_epoch()).count(); }

thread_local std::string t_last_error;
constexpr int kCanvasW = 640, kCanvasH = 352;

struct Config {
    std::string model, mmproj, split_dir, qnn_lib_dir, system_prompt;
    std::vector<int> lm_cpus{4, 5, 6, 7}, vision_cpus{1, 2, 3}, island_cpus{4, 5, 6, 7}, audio_cpus{1, 2, 3};
    std::vector<int> island_small_cpus{1, 2};  // islands during an answer
    double skip_cos = 0.98;
    int max_tokens = 512, max_history_tokens = 1536;  // an answer ends at its own end (eog); this only stops a runaway
    std::string vad_weights = "/var/lib/cortex/models/silero_vad_v4.bin";
    ListenConfig listen;
    int fail_encode_after = 0;  // test-only fault injection: encodes after this many fail
    // speech out
    bool speak = true, codec_inline = false;
    std::string voice = "female";
    SpeakerConfig speaker;  // device, UCM route, mixer, prebuffer_ms, cpus (speaker_cpus)
    int mute_tail_ms = 300, max_speech_s = 60, codec_threads = 1;
    int echo_lag_ms = 500;  // the echo delay assumed until an answer has been measured (0..1500)
    std::vector<int> codec_cpus{3};
};

Config parse_config(const char* text) {
    json j = json::parse(text ? text : "");
    Config c;
    for (const char* k : {"model", "mmproj", "split_dir", "qnn_lib_dir"})
        if (!j.contains(k) || !j[k].is_string()) throw std::runtime_error(std::string("config needs \"") + k + "\"");
    c.model = j["model"], c.mmproj = j["mmproj"], c.split_dir = j["split_dir"], c.qnn_lib_dir = j["qnn_lib_dir"];
    c.system_prompt = j.value("system_prompt", "");
    c.lm_cpus = j.value("lm_cpus", c.lm_cpus);
    c.vision_cpus = j.value("vision_cpus", c.vision_cpus);
    c.island_cpus = j.value("island_cpus", c.island_cpus);
    c.island_small_cpus = j.value("island_small_cpus", c.island_small_cpus);
    c.skip_cos = j.value("skip_cos", c.skip_cos);
    c.max_tokens = j.value("max_tokens", c.max_tokens);
    c.max_history_tokens = j.value("max_history_tokens", c.max_history_tokens);
    c.fail_encode_after = j.value("fail_encode_after", 0);
    c.audio_cpus = j.value("audio_cpus", c.audio_cpus);
    c.vad_weights = j.value("vad_weights", c.vad_weights);
    c.listen.on = j.value("vad_on", c.listen.on);
    c.listen.off = j.value("vad_off", c.listen.off);
    c.listen.hangover_ms = j.value("vad_hangover_ms", c.listen.hangover_ms);
    c.speak = j.value("speak", c.speak);
    c.voice = j.value("voice", c.voice);
    c.codec_inline = j.value("codec_inline", c.codec_inline);
    c.codec_cpus = j.value("codec_cpus", c.codec_cpus);
    c.codec_threads = j.value("codec_threads", c.codec_threads);
    c.max_speech_s = j.value("max_speech_s", c.max_speech_s);
    c.mute_tail_ms = j.value("mute_tail_ms", c.mute_tail_ms);
    c.echo_lag_ms = j.value("echo_lag_ms", c.echo_lag_ms);
    SpeakerConfig& s = c.speaker;
    s.device = j.value("speaker_device", s.device);
    s.ucm_card = j.value("ucm_card", s.ucm_card);
    s.ucm_verb = j.value("ucm_verb", s.ucm_verb);
    s.ucm_device = j.value("ucm_device", s.ucm_device);
    s.prebuffer_ms = j.value("prebuffer_ms", s.prebuffer_ms);
    s.rebuffer_ms = j.value("rebuffer_ms", s.rebuffer_ms);
    s.cpus = j.value("speaker_cpus", s.cpus);
    if (j.contains("mixer")) {
        if (!j["mixer"].is_object()) throw std::runtime_error("config: mixer is {\"control\": value, ...}");
        s.mixer.clear();
        for (auto& [k, v] : j["mixer"].items()) s.mixer.emplace_back(k, v.get<int>());
    }
    if (c.max_speech_s < 0 || c.max_speech_s > 90) throw std::runtime_error("config: max_speech_s is 0..90");
    if (c.echo_lag_ms < 0 || c.echo_lag_ms > 1500) throw std::runtime_error("config: echo_lag_ms is 0..1500");
    if (c.mute_tail_ms < 0 || s.prebuffer_ms < 0 || s.rebuffer_ms < 0 || c.codec_threads < 1)
        throw std::runtime_error("config: mute_tail_ms, prebuffer_ms and rebuffer_ms are >= 0, codec_threads >= 1");
    for (auto* set : {&c.lm_cpus, &c.vision_cpus, &c.island_cpus, &c.audio_cpus, &c.island_small_cpus, &c.codec_cpus,
                      &s.cpus}) {
        if (set->empty()) throw std::runtime_error("config: a cpu set is empty");
        for (int cpu : *set)
            if (cpu <= 0 || cpu >= CPU_SETSIZE)
                throw std::runtime_error("config: cpu " + std::to_string(cpu) + " not allowed (cpu0 is the safety core)");
    }
    return c;
}

void pin_self(const std::vector<int>& cpus) {
    cpu_set_t set;
    CPU_ZERO(&set);
    for (int c : cpus) CPU_SET(c, &set);
    pthread_setaffinity_np(pthread_self(), sizeof set, &set);
}

double mean_row_cos(const std::vector<float>& a, const std::vector<float>& b, int rows) {
    if (a.size() != b.size() || rows <= 0) return 0;
    const size_t cols = a.size() / rows;
    double sum = 0;
    for (int r = 0; r < rows; r++) {
        double ab = 0, aa = 0, bb = 0;
        for (size_t i = r * cols; i < (r + 1) * cols; i++) ab += a[i] * b[i], aa += a[i] * a[i], bb += b[i] * b[i];
        sum += aa > 0 && bb > 0 ? ab / std::sqrt(aa * bb) : 0;
    }
    return sum / rows;
}

struct Engine {
    Config cfg;
    ce_event_cb cb = nullptr;
    void* user = nullptr;
    std::mutex emit_mu;

    std::shared_ptr<Vision> vision;
    std::unique_ptr<Lm> lm;
    BigCores big;

    std::mutex mu;  // guards everything below
    std::condition_variable cv;
    bool stop = false;
    int ready = 0;  // threads finished opening their part
    std::string open_error;
    // latest frame
    std::vector<uint8_t> frame;
    int fw = 0, fh = 0;
    long fid = -1;
    bool refresh_pending = false, commit_pending = false;
    // ask queue (one slot)
    bool ask_pending = false;
    std::string ask_text;
    int ask_max = 0;
    std::atomic<bool> asking{false};
    // view state (control thread)
    std::vector<float> last_read;  // features of the view in the LM
    int n_encodes = 0;
    std::atomic<long> view_id{-1};
    std::atomic<bool> force_read{false};
    // voice handoff, audio thread -> worker (guarded by mu)
    std::atomic<bool> speaking{false};  // an utterance is open: host refreshes wait, typed asks are busy
    std::vector<float> v_rows;          // encoded rows not yet given to the LM
    bool v_end = false, v_drop = false;
    clk::time_point v_end_time{};
    double v_speech_ms = 0;

    // listening (audio thread); amu guards aq, listening, listen_gen, astop
    std::unique_ptr<Listener> listener;
    std::unique_ptr<AudioIn> audio_in;
    std::string listen_error;
    std::mutex amu;
    std::condition_variable acv;
    std::vector<float> aq;
    bool listening = false, astop = false;
    long listen_gen = 0;

    // speech out. talking: sound is coming out. muted: the mic is off (an answer is being made or heard), and stays
    // off until mute_until (steady ms) after the sound ends.
    std::unique_ptr<Speaker> speaker;
    std::atomic<bool> talking{false}, muted{false}, sound_voice{false};
    std::atomic<double> mute_until{0}, sound_start_at{0};
    // echo: the answer's first loud sample (ms into its sound, -1 none yet; set by on_pcm) and the measured delay
    std::atomic<double> loud_off_ms{-1}, echo_lag{0};
    long pcm_n = 0;  // samples of this answer through on_pcm
    bool muted_now() const { return muted || now_steady_ms() < mute_until + echo_lag; }

    void on_sound(const SoundEvent& s) {  // speaker thread or a cutting caller, under the speaker's lock
        json j = {{"type", s.type}, {"at_ms", s.at_ms}};
        if (s.type == "sound_start") {
            talking = true;
            sound_start_at = s.at_ms;
        } else {
            talking = false;
            mute_until = s.at_ms + cfg.mute_tail_ms;
            muted = false;
            j["sound_ms"] = s.sound_ms, j["gaps"] = s.gaps, j["cut"] = s.cut;
        }
        if (sound_voice) j["voice"] = true;
        if (s.type == "sound_start" && sound_voice) j["end_to_sound_ms"] = s.at_ms - end_at_ms;
        emit(j);
    }
    std::atomic<double> end_at_ms{0};  // steady ms of the spoken question's end

    void on_pcm(const float* pcm, int n, bool end) {  // codec thread (or the LM thread with codec_inline)
        if (n > 0) {
            if (loud_off_ms < 0) {
                for (int i = 0; i < n; i++)
                    if (std::fabs(pcm[i]) > 0.03f) {  // ~-30 dBFS: speech, not the codec's near-silence
                        loud_off_ms = (pcm_n + i) / 24.0;
                        break;
                    }
            }
            pcm_n += n;
            speaker->push(pcm, n);
        }
        if (end) speaker->end();
    }

    // a new answer (LM worker): what the codec still holds of earlier answers is dropped, so none of it reaches this
    // answer; their sound is cut; the mic goes off
    void sound_begin(bool voice, clk::time_point end_time) {
        lm->drop_sound();  // the codec holds nothing of earlier answers now: on_pcm is quiet until this one's sound
        pcm_n = 0, loud_off_ms = -1;
        speaker->begin();
        sound_voice = voice;
        end_at_ms = std::chrono::duration<double, std::milli>(end_time.time_since_epoch()).count();
        muted = true;
    }

    std::thread control, worker, audio;
    std::atomic<long> control_tid{0}, worker_tid{0}, audio_tid{0};
    std::string status_buf;

    void emit(const json& j) {
        const std::string line = j.dump();
        std::lock_guard<std::mutex> g(emit_mu);
        if (cb) cb(line.c_str(), user);
    }
    void error(const std::string& what) { emit({{"type", "error"}, {"what", what}}); }

    void opened(const std::string& err) {
        std::lock_guard<std::mutex> g(mu);
        if (!err.empty() && open_error.empty()) open_error = err;
        ready++;
        cv.notify_all();
    }

    void control_main() {
        control_tid = (long)syscall(SYS_gettid);
        pin_self(cfg.vision_cpus);
        std::string err;
        vision = Vision::shared(cfg.split_dir, cfg.qnn_lib_dir, cfg.island_cpus, (int)cfg.island_cpus.size(),
                                cfg.island_small_cpus, &err);
        if (vision) {
            if ((int)vision->pixel_count() != kCanvasW / 32 * (kCanvasH / 32) * 4 * 1536)
                err = "split encoder input does not match the 640x352 canvas", vision.reset();
            else
                vision->set_island_gate([this] { return big.island_enter(); }, [this](bool b) { big.island_exit(b); });
        }
        opened(vision ? "" : "vision: " + err);
        if (!vision) return;
        std::vector<float> pv(vision->pixel_count()), feat;
        for (;;) {
            std::vector<uint8_t> px;
            int w, h;
            long id;
            {
                std::unique_lock<std::mutex> l(mu);
                cv.wait(l, [&] {
                    return stop || refresh_pending || (commit_pending && !asking && !ask_pending && !v_end);
                });
                if (stop) return;
                if (!refresh_pending) {
                    // background: the last answer joins the history now, off the next refresh's critical path
                    commit_pending = false;
                    l.unlock();
                    std::string err;
                    if (!lm->commit_turns(&err) && err != "preempted") error("history: " + err);
                    continue;
                }
                refresh_pending = false;
                if (fid < 0) {
                    l.unlock();
                    error("refresh: no frame pushed");
                    continue;
                }
                px = frame, w = fw, h = fh, id = fid;
            }
            refresh(px, w, h, id, pv, feat);
        }
    }

    void refresh(const std::vector<uint8_t>& px, int w, int h, long id, std::vector<float>& pv, std::vector<float>& feat) {
        std::string err;
        auto t = clk::now();
        if (!prepare(px.data(), w, h, kCanvasW, kCanvasH, pv.data(), &err)) return error("prepare: " + err);
        const double prep_ms = ms_since(t);
        t = clk::now();
        bool ok = cfg.fail_encode_after > 0 && n_encodes >= cfg.fail_encode_after
                      ? (err = "injected encode failure", false)
                      : vision->encode(pv.data(), &feat, &err);
        if (!ok) return error("encode: " + err);
        n_encodes++;
        const double encode_ms = ms_since(t);
        json ev = {{"type", "view"}, {"frame_id", id}, {"prep_ms", prep_ms}, {"encode_ms", encode_ms}};
        if (force_read.exchange(false)) last_read.clear();  // the view was dropped (reset_history): read it again
        const double cos = last_read.empty() ? 0.0 : mean_row_cos(last_read, feat, vision->n_tokens());
        ev["cos"] = cos;
        if (!last_read.empty() && cos >= cfg.skip_cos) {
            ev["skipped"] = true;  // same scene: the view in the LM stays
            return emit(ev);
        }
        int preempted = 0;
        t = clk::now();
        for (;;) {
            if (lm->read_view(feat.data(), vision->n_tokens(), id, &err)) break;
            if (err != "preempted") return error("read view: " + err);
            preempted++;
            // an ask (typed or spoken) took the LM: read again once it is answered
            std::unique_lock<std::mutex> l(mu);
            cv.wait(l, [&] { return stop || (!asking && !ask_pending && !v_end); });
            if (stop) return;
        }
        last_read = feat;
        view_id = id;
        ev["skipped"] = false;
        ev["read_ms"] = lm->last_read_ms();
        ev["preempted"] = preempted;
        emit(ev);
    }

    void worker_main() {
        worker_tid = (long)syscall(SYS_gettid);
        pin_self(cfg.lm_cpus);
        LmConfig lc;
        lc.model = cfg.model, lc.mmproj = cfg.mmproj, lc.system_prompt = cfg.system_prompt;
        lc.cpus = cfg.lm_cpus, lc.n_threads = (int)cfg.lm_cpus.size();
        lc.max_history_tokens = cfg.max_history_tokens;
        if (speaker) {
            lc.speak = true, lc.voice = cfg.voice, lc.max_speech_s = cfg.max_speech_s;
            lc.codec_inline = cfg.codec_inline, lc.codec_cpus = cfg.codec_cpus, lc.codec_threads = cfg.codec_threads;
            lc.on_pcm = [this](const float* pcm, int n, bool end) { on_pcm(pcm, n, end); };
        }
        std::string err;
        lm = Lm::open(lc, &err);
        opened(lm ? "" : "lm: " + err);
        if (!lm) return;
        const int n_embd = lm->n_embd_inp();
        for (;;) {
            std::string text;
            int max = cfg.max_tokens;
            std::vector<float> rows;
            bool drop = false, end = false, typed = false;
            clk::time_point end_time;
            double speech_ms = 0;
            {
                std::unique_lock<std::mutex> l(mu);
                cv.wait(l, [&] { return stop || ask_pending || v_drop || v_end || !v_rows.empty(); });
                if (stop) return;
                drop = v_drop, v_drop = false;
                rows.swap(v_rows);
                if (v_end) {
                    end = true, v_end = false, asking = true;  // asking from here on, so background reads keep waiting
                    end_time = v_end_time, speech_ms = v_speech_ms;
                } else if (!drop && rows.empty()) {
                    typed = true;
                    text = ask_text, max = ask_max;
                    ask_pending = false;
                }
            }
            if (drop) lm->voice_drop();
            std::string err;
            if (!rows.empty() && !lm->voice_feed(rows.data(), (int)(rows.size() / n_embd), &err)) error("voice: " + err);
            if (!end && !typed) continue;
            if (speaker) sound_begin(end, end_time);
            big.ask_enter();
            bool first = true;
            double end_to_first = 0;
            auto on_token = [&](const std::string& piece) {
                if (first && end) end_to_first = ms_since(end_time);
                first = false;
                json tok = {{"type", "token"}, {"text", piece}};
                if (end) tok["voice"] = true;  // so a client can route spoken answers apart from typed asks
                emit(tok);
            };
            AskResult r;
            const double wait_ms = end ? ms_since(end_time) : 0;  // last rows decoded + gate, before the answer
            if (end) {
                lm->clear_cancel();
                r = lm->voice_answer(max, on_token);
            } else {
                r = lm->ask(text, max, on_token);
            }
            big.ask_exit();
            if (!r.error.empty()) error((end ? "voice: " : "ask: ") + r.error);
            json done = {{"type", "done"},
                         {"ttft_ms", r.ttft_ms},
                         {"total_ms", r.total_ms},
                         {"n_out", r.n_out},
                         {"view_frame_id", r.view_frame_id},
                         {"view_age_ms", r.view_age_ms},
                         {"cancelled", r.cancelled},
                         {"stop", r.stop},
                         {"frames", r.frames},
                         {"frame_ms", r.frame_ms},
                         {"codec_ms", r.codec_ms},
                         {"sound_ms", r.sound_ms}};
            if (end) {
                done["voice"] = true, done["end_to_first_ms"] = end_to_first, done["speech_ms"] = speech_ms;
                done["wait_ms"] = wait_ms;
                const double s0 = sound_start_at;
                if (speaker && s0 >= end_at_ms) done["end_to_sound_ms"] = s0 - end_at_ms;  // sound began already
            }
            {  // free before done goes out: a client that asks on done is not told "busy" (this thread emits done
               // before it can take the next ask, so the order of events holds)
                std::lock_guard<std::mutex> g(mu);
                asking = false;
                commit_pending = true;
            }
            cv.notify_all();
            emit(done);
        }
    }

    // ---- listening
    void audio_main() {
        audio_tid = (long)syscall(SYS_gettid);
        pin_self(cfg.audio_cpus);  // the audio encoder's threads start from this thread and inherit its cores
        std::vector<float> buf, rows;
        std::vector<VadEvent> evs;
        long gen_seen = 0;
        int64_t base = 0;  // first sample of the current listening period, in the Listener's count
        bool in_utt = false, was_muted = false;
        // echo measurement: the room's level while the mic is live, and the answer being measured
        double floor_db = -60, measured_for = -1;
        auto drop_utt = [&] {  // an open utterance is dropped, the VAD starts clean
            if (in_utt) {
                audio_in->drop();
                {
                    std::lock_guard<std::mutex> g(mu);
                    speaking = false;
                    v_rows.clear();
                    v_drop = true;
                }
                cv.notify_all();
                in_utt = false;
            }
            listener->reset();
            base = 0;
        };
        for (;;) {
            bool on;
            {
                std::unique_lock<std::mutex> l(amu);
                acv.wait(l, [&] { return astop || !aq.empty() || listen_gen != gen_seen; });
                if (astop) return;
                if (listen_gen != gen_seen) {  // toggled
                    gen_seen = listen_gen;
                    drop_utt();
                }
                on = listening;
                buf.swap(aq);
                aq.clear();
            }
            // Cortex is talking (or its sound just ended): the mic hears the answer, not the user
            const double now = now_steady_ms();
            if (!buf.empty()) {
                double e2 = 0;
                for (float x : buf) e2 += (double)x * x;
                const double db = std::max(-100.0, 10 * std::log10(e2 / buf.size() + 1e-12));
                // The echo's onset: the answer's first loud sample went out at s0 + loud_off; the mic hears it lag
                // ms later as a jump of 12 dB over the room. A later lag is taken at once (the echo outlasting the
                // mute is the failure), an earlier one a quarter of the way (one early noise is not the echo).
                const double s0 = sound_start_at, off = loud_off_ms;
                if (speaker && talking && s0 != measured_for && off >= 0) {
                    const double ref = s0 + off;
                    if (now > ref + 1500) {
                        measured_for = s0;  // no echo heard: the estimate stands
                    } else if (now >= ref && db > floor_db + 12) {
                        const double lag = now - ref, est = echo_lag;
                        echo_lag = lag > est ? lag : est + 0.25 * (lag - est);
                        measured_for = s0;
                    }
                }
                // the room's floor, never Cortex's voice: it follows quiet at once and speech only slowly
                if (!muted_now()) floor_db += (db < floor_db ? 0.3 : 0.02) * (db - floor_db);
            }
            const bool mute = muted_now();
            if (mute != was_muted) {
                was_muted = mute;
                drop_utt();  // either edge: what the VAD held is from the other side of the mute
            }
            if (!on || mute) {
                buf.clear();
                continue;
            }
            evs.clear();
            listener->push(buf.data(), buf.size(), &evs);
            buf.clear();
            for (auto& e : evs) {
                const double at_ms = (e.sample - base) / 16.0;
                std::string err;
                if (e.kind == VadEvent::Start) {
                    in_utt = audio_in->begin(&err);
                    if (!in_utt) {
                        error("audio: " + err);
                        continue;
                    }
                    {
                        std::lock_guard<std::mutex> g(mu);
                        speaking = true;
                        if (asking) lm->cancel();     // barge-in: the user talks over the answer
                        if (fid >= 0) refresh_pending = true;  // the view the question is about
                    }
                    cv.notify_all();
                    emit({{"type", "speech_start"}, {"at_ms", at_ms}});
                    utt_start_ms_ = at_ms;
                } else if (e.kind == VadEvent::Audio) {
                    if (!in_utt) continue;
                    rows.clear();
                    if (audio_in->push(e.pcm.data(), e.pcm.size(), &rows) < 0) error("audio: encode failed");
                    if (rows.empty()) continue;
                    {
                        std::lock_guard<std::mutex> g(mu);
                        v_rows.insert(v_rows.end(), rows.begin(), rows.end());
                    }
                    cv.notify_all();
                } else {
                    if (!in_utt) continue;
                    in_utt = false;
                    rows.clear();
                    if (audio_in->end(&rows) < 0) error("audio: encode failed");
                    {
                        std::lock_guard<std::mutex> g(mu);
                        v_rows.insert(v_rows.end(), rows.begin(), rows.end());
                        v_end = true;
                        v_end_time = clk::now();
                        v_speech_ms = at_ms - utt_start_ms_;
                        speaking = false;
                    }
                    lm->preempt();  // a background read gives way now, not after its whole image
                    cv.notify_all();
                    emit({{"type", "speech_end"}, {"at_ms", at_ms}, {"speech_ms", at_ms - utt_start_ms_}});
                }
            }
        }
    }
    double utt_start_ms_ = 0;  // audio thread only

    void shutdown() {
        {
            std::lock_guard<std::mutex> g(mu);
            stop = true;
        }
        {
            std::lock_guard<std::mutex> g(amu);
            astop = true;
        }
        acv.notify_all();
        if (audio.joinable()) audio.join();
        if (lm) lm->cancel();
        cv.notify_all();
        if (control.joinable()) control.join();
        if (worker.joinable()) worker.join();
        if (vision) vision->set_island_gate(nullptr, nullptr);
        audio_in.reset();  // uses the LM's mtmd context
        lm.reset();        // its codec thread pushes into the speaker
        speaker.reset();
    }
};

json thread_info(const char* name, long tid) {
    json cpus = json::array();
    cpu_set_t set;
    CPU_ZERO(&set);
    if (tid > 0 && sched_getaffinity((pid_t)tid, sizeof set, &set) == 0)
        for (int c = 0; c < CPU_SETSIZE; c++)
            if (CPU_ISSET(c, &set)) cpus.push_back(c);
    return {{"name", name}, {"tid", tid}, {"cpus", cpus}};
}

}  // namespace
}  // namespace ce

using ce::Engine;

extern "C" {

void* ce_open(const char* config_json, ce_event_cb cb, void* user) {
    auto* e = new Engine();
    try {
        e->cfg = ce::parse_config(config_json);
        e->echo_lag = e->cfg.echo_lag_ms;
    } catch (const std::exception& ex) {
        ce::t_last_error = ex.what();
        delete e;
        return nullptr;
    }
    e->cb = cb, e->user = user;
    if (e->cfg.speak) {  // a speaker that will not open leaves Cortex answering in text, never silent and broken
        std::string err;
        if (auto sink = ce::open_sink(e->cfg.speaker, &err))
            e->speaker.reset(new ce::Speaker(e->cfg.speaker, std::move(sink),
                                             [e](const ce::SoundEvent& s) { e->on_sound(s); }));
        else
            e->error("speaker: " + err + " (answers in text only)");
    }
    e->control = std::thread([e] { e->control_main(); });
    e->worker = std::thread([e] { e->worker_main(); });
    std::string err;
    {
        std::unique_lock<std::mutex> l(e->mu);
        e->cv.wait(l, [&] { return e->ready == 2 || !e->open_error.empty(); });
        err = e->open_error;
    }
    if (!err.empty()) {
        ce::t_last_error = err;
        e->shutdown();
        delete e;
        return nullptr;
    }
    // Listening is optional: without the VAD weights or an audio encoder the engine still serves typed asks, and
    // ce_set_listening says why it cannot listen.
    e->listener.reset(new ce::Listener());
    if (!e->listener->open(e->cfg.vad_weights, e->cfg.listen, &err)) {
        e->listen_error = "vad: " + err;
        e->listener.reset();
    } else if (!(e->audio_in = e->lm->audio_in(&err))) {
        e->listen_error = "audio: " + err;
        e->listener.reset();
    } else {
        e->audio = std::thread([e] { e->audio_main(); });
    }
    return e;
}

const char* ce_last_error(void) { return ce::t_last_error.c_str(); }

int ce_push_frame(void* h, const uint8_t* rgb, int w, int hgt, long frame_id) {
    auto* e = static_cast<Engine*>(h);
    if (!e || !rgb || w <= 0 || hgt <= 0) return -1;
    std::lock_guard<std::mutex> g(e->mu);
    e->frame.assign(rgb, rgb + (size_t)w * hgt * 3);
    e->fw = w, e->fh = hgt, e->fid = frame_id;
    return 0;
}

int ce_refresh(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return -1;
    {
        std::lock_guard<std::mutex> g(e->mu);
        if (e->speaking) return 0;  // the view stays the one taken when the user started talking
        e->refresh_pending = true;
    }
    e->cv.notify_all();
    return 0;
}

int ce_ask(void* h, const char* text, int max_tokens) {
    auto* e = static_cast<Engine*>(h);
    if (!e || !text) return -1;
    {
        std::unique_lock<std::mutex> g(e->mu);
        if (e->asking || e->speaking || e->v_end) {
            g.unlock();
            e->error("busy");
            return -1;
        }
        e->asking = true;
        e->lm->clear_cancel();
        e->ask_text = text;
        e->ask_max = max_tokens > 0 ? max_tokens : e->cfg.max_tokens;
        e->ask_pending = true;
    }
    e->cv.notify_all();
    return 0;
}

int ce_cancel(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return -1;
    {
        std::lock_guard<std::mutex> g(e->mu);
        if (e->asking) e->lm->cancel();
    }
    if (e->speaker) e->speaker->stop();  // the sound stops now, also an answer already made and still playing
    return 0;
}

int ce_reset_history(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return -1;
    // The view in the LM was read on the old history and goes too; asks are text-only until the next refresh,
    // which reads the scene again even if it has not changed.
    e->force_read = true;
    e->lm->reset_history();
    e->view_id = -1;
    return 0;
}

int ce_set_listening(void* h, int on) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return -1;
    if (!e->listener) {
        ce::t_last_error = e->listen_error;
        e->error("listen: " + e->listen_error);
        return -1;
    }
    {
        std::lock_guard<std::mutex> g(e->amu);
        if (e->listening == (on != 0)) return 0;
        e->listening = on != 0;
        e->listen_gen++;
        e->aq.clear();
    }
    e->acv.notify_all();
    return 0;
}

int ce_push_audio(void* h, const float* pcm, int n) {
    auto* e = static_cast<Engine*>(h);
    if (!e || !pcm || n < 0) return -1;
    {
        std::lock_guard<std::mutex> g(e->amu);
        if (!e->listening) return 0;
        if (e->aq.size() + (size_t)n > 10 * 16000) {  // the audio thread is 10 s behind: drop the backlog
            e->aq.clear();
            e->error("audio: backlog dropped");
        }
        e->aq.insert(e->aq.end(), pcm, pcm + n);
    }
    e->acv.notify_one();
    return 0;
}

const char* ce_status(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return "{}";
    nlohmann::json st;
    {
        std::lock_guard<std::mutex> g(e->mu);
        st["asking"] = e->asking.load();
        st["frame_id"] = e->fid;
        st["speaking"] = e->speaking.load();
    }
    {
        std::lock_guard<std::mutex> g(e->amu);
        st["listening"] = e->listening;
    }
    if (!e->listen_error.empty()) st["listen_error"] = e->listen_error;
    st["speak"] = e->speaker != nullptr;
    st["talking"] = e->talking.load();
    st["muted"] = e->muted_now();
    if (e->speaker) st["echo_lag_ms"] = std::lround(e->echo_lag.load());
    if (e->speaker) st["prebuffer_ms"] = e->speaker->prebuffer_ms();
    st["view_frame_id"] = e->view_id.load();
    st["history_tokens"] = e->lm->history_tokens();
    st["threads"] = {ce::thread_info("control", e->control_tid), ce::thread_info("lm", e->worker_tid)};
    if (e->audio_tid) st["threads"].push_back(ce::thread_info("audio", e->audio_tid));
    e->status_buf = st.dump();
    return e->status_buf.c_str();
}

void ce_close(void* h) {
    auto* e = static_cast<Engine*>(h);
    if (!e) return;
    e->shutdown();
    delete e;
}

}  // extern "C"
