// cortex-engine --config C.json --frames DIR --ask "..." [--repeat N]
// For each JPEG/PNG in DIR (sorted): push it, refresh, wait for its view, ask, wait for the answer. Prints every
// event line. With --repeat N the whole directory is played N times.
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

#include "cortex_engine.h"

namespace {
std::mutex mu;
std::condition_variable cv;
int n_view = 0, n_done = 0, n_error = 0;

void on_event(const char* line, void*) {
    std::lock_guard<std::mutex> g(mu);
    std::printf("%s\n", line);
    std::fflush(stdout);
    if (std::strstr(line, "\"type\":\"view\"")) n_view++;
    if (std::strstr(line, "\"type\":\"done\"")) n_done++;
    if (std::strstr(line, "\"type\":\"error\"")) n_error++;
    cv.notify_all();
}

// waits until *counter passes target or an error arrives after err0
bool wait_for(int* counter, int target, int err0) {
    std::unique_lock<std::mutex> l(mu);
    return cv.wait_for(l, std::chrono::seconds(60), [&] { return *counter >= target || n_error > err0; }) &&
           *counter >= target;
}

int usage() {
    std::fprintf(stderr, "usage: cortex-engine --config C.json --frames DIR --ask TEXT [--repeat N]\n");
    return 2;
}
}  // namespace

int main(int argc, char** argv) {
    std::string config, frames, ask;
    int repeat = 1;
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::string k = argv[i], v = argv[i + 1];
        if (k == "--config") config = v;
        else if (k == "--frames") frames = v;
        else if (k == "--ask") ask = v;
        else if (k == "--repeat") repeat = std::max(1, std::atoi(v.c_str()));
        else return usage();
    }
    if (config.empty() || frames.empty() || ask.empty()) return usage();
    std::stringstream cfg;
    cfg << std::ifstream(config).rdbuf();
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
