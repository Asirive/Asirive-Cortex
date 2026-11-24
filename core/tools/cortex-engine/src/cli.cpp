// cortex-engine --config C.json --frames DIR --ask "..." [--repeat N]
// For each JPEG/PNG in DIR (sorted): push it, refresh, wait for its view, ask, wait for the answer. Prints every
// event line. With --repeat N the whole directory is played N times.
//
// cortex-engine --config C.json --wav FILE.wav [--frames DIR]
// Hands-free: shows the first image in DIR (if given), turns listening on and plays the 16 kHz mono WAV into the
// engine at real-time pace as a microphone would, then waits for the last spoken answer. Prints every event line.
#define STB_IMAGE_STATIC
#define STB_IMAGE_IMPLEMENTATION
#include "stb/stb_image.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <dirent.h>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include <thread>

#include "cortex_engine.h"
#include "vad.h"

namespace {
std::mutex mu;
std::condition_variable cv;
int n_view = 0, n_done = 0, n_error = 0, n_start = 0;

void on_event(const char* line, void*) {
    std::lock_guard<std::mutex> g(mu);
    std::printf("%s\n", line);
    std::fflush(stdout);
    if (std::strstr(line, "\"type\":\"view\"")) n_view++;
    if (std::strstr(line, "\"type\":\"done\"")) n_done++;
    if (std::strstr(line, "\"type\":\"error\"")) n_error++;
    if (std::strstr(line, "\"type\":\"speech_start\"")) n_start++;
    cv.notify_all();
}

// waits until *counter passes target or an error arrives after err0
bool wait_for(int* counter, int target, int err0) {
    std::unique_lock<std::mutex> l(mu);
    return cv.wait_for(l, std::chrono::seconds(60), [&] { return *counter >= target || n_error > err0; }) &&
           *counter >= target;
}

int usage() {
    std::fprintf(stderr,
                 "usage: cortex-engine --config C.json --frames DIR --ask TEXT [--repeat N]\n"
                 "       cortex-engine --config C.json --wav FILE.wav [--frames DIR]\n");
    return 2;
}

// Plays the WAV into the engine in 20 ms pieces at real-time pace, then 1.5 s of silence so the last utterance ends.
// Waits until every utterance the VAD found has its done event.
int listen_wav(void* h, const std::string& wav) {
    std::vector<float> pcm;
    int rate = 0;
    std::string err;
    if (!ce::read_wav_s16(wav, &pcm, &rate, &err)) {
        std::fprintf(stderr, "cortex-engine: %s\n", err.c_str());
        return 1;
    }
    if (rate != 16000) {
        std::fprintf(stderr, "cortex-engine: %s is %d Hz, need 16000 Hz mono\n", wav.c_str(), rate);
        return 1;
    }
    if (ce_set_listening(h, 1) != 0) {
        std::fprintf(stderr, "cortex-engine: listening unavailable: %s\n", ce_status(h));
        return 1;
    }
    pcm.resize(pcm.size() + 24000, 0.0f);
    const size_t piece = 320;
    auto next = std::chrono::steady_clock::now();
    for (size_t i = 0; i < pcm.size(); i += piece) {
        ce_push_audio(h, pcm.data() + i, (int)std::min(piece, pcm.size() - i));
        next += std::chrono::milliseconds(20);
        std::this_thread::sleep_until(next);
    }
    std::unique_lock<std::mutex> l(mu);
    const bool ok = cv.wait_for(l, std::chrono::seconds(60), [] { return n_done >= n_start; });
    return ok && n_start > 0 ? 0 : 1;
}

std::vector<std::string> images(const std::string& frames);
}  // namespace

int main(int argc, char** argv) {
    std::string config, frames, ask, wav;
    int repeat = 1;
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::string k = argv[i], v = argv[i + 1];
        if (k == "--config") config = v;
        else if (k == "--frames") frames = v;
        else if (k == "--ask") ask = v;
        else if (k == "--wav") wav = v;
        else if (k == "--repeat") repeat = std::max(1, std::atoi(v.c_str()));
        else return usage();
    }
    if (config.empty() || (wav.empty() && (frames.empty() || ask.empty()))) return usage();
    std::stringstream cfg;
    cfg << std::ifstream(config).rdbuf();
    if (!wav.empty()) {
        void* h = ce_open(cfg.str().c_str(), on_event, nullptr);
        if (!h) {
            std::fprintf(stderr, "cortex-engine: %s\n", ce_last_error());
            return 1;
        }
        if (!frames.empty()) {  // a view for the questions to be about
            const auto files = images(frames);
            int w = 0, hh = 0, ch = 0;
            if (unsigned char* px = files.empty() ? nullptr : stbi_load(files[0].c_str(), &w, &hh, &ch, 3)) {
                int views;
                {
                    std::lock_guard<std::mutex> g(mu);
                    views = n_view;
                }
                ce_push_frame(h, px, w, hh, 1);
                stbi_image_free(px);
                ce_refresh(h);
                wait_for(&n_view, views + 1, n_error);
            }
        }
        const int rc = listen_wav(h, wav);
        std::printf("%s\n", ce_status(h));
        ce_close(h);
        return rc;
    }
    const auto files = images(frames);
    if (files.empty()) {
        std::fprintf(stderr, "cortex-engine: no images in %s\n", frames.c_str());
        return 1;
    }
    void* h = ce_open(cfg.str().c_str(), on_event, nullptr);
    if (!h) {
        std::fprintf(stderr, "cortex-engine: %s\n", ce_last_error());
        return 1;
    }
    long id = 0;
    int rc = 0;
    for (int r = 0; r < repeat && rc == 0; r++)
        for (const auto& f : files) {
            int w = 0, hh = 0, ch = 0;
            unsigned char* px = stbi_load(f.c_str(), &w, &hh, &ch, 3);
            if (!px) {
                std::fprintf(stderr, "cortex-engine: cannot read %s\n", f.c_str());
                continue;
            }
            int views, dones, errs;
            {
                std::lock_guard<std::mutex> g(mu);
                views = n_view, dones = n_done, errs = n_error;
                std::printf("{\"type\":\"frame\",\"file\":\"%s\",\"frame_id\":%ld}\n", f.c_str(), ++id);
            }
            ce_push_frame(h, px, w, hh, id);
            stbi_image_free(px);
            ce_refresh(h);
            if (!wait_for(&n_view, views + 1, errs)) continue;
            ce_ask(h, ask.c_str(), 0);
            if (!wait_for(&n_done, dones + 1, errs)) rc = 1;
        }
    std::printf("%s\n", ce_status(h));
    ce_close(h);
    return rc;
}

namespace {
std::vector<std::string> images(const std::string& frames) {
    std::vector<std::string> files;
    if (DIR* d = opendir(frames.c_str())) {
        while (dirent* de = readdir(d)) {
            std::string n = de->d_name, low = n;
            std::transform(low.begin(), low.end(), low.begin(), ::tolower);
            for (const char* ext : {".jpg", ".jpeg", ".png"})
                if (low.size() > std::strlen(ext) && low.compare(low.size() - std::strlen(ext), std::string::npos, ext) == 0)
                    files.push_back(frames + "/" + n);
        }
        closedir(d);
    }
    std::sort(files.begin(), files.end());
    return files;
}
}  // namespace
