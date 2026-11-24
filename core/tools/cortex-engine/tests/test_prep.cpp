#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "../src/prep.h"
#include "check.h"
#include "golden.h"

// <stem>.rgb = int32 w, int32 h, then h*w*3 uint8 (PIL-decoded pixels, written by make_goldens.py)
static bool load_rgb(const std::string& stem, std::vector<uint8_t>* px, int* w, int* h) {
    std::ifstream f(golden::dir + stem + ".rgb", std::ios::binary);
    int32_t wh[2];
    if (!f.read(reinterpret_cast<char*>(wh), 8)) return false;
    *w = wh[0], *h = wh[1];
    px->resize((size_t)*w * *h * 3);
    return (bool)f.read(reinterpret_cast<char*>(px->data()), (std::streamsize)px->size());
}

TEST(prepare_matches_python) {
    const char* frames[] = {"t001", "t002", "t003", "t004", "t005", "t006", "t007",
                            "t008", "t009", "t010", "t011", "t012", "h008_1080p", "p001_portrait"};
    std::vector<float> out(11u * 20 * 2 * 2 * 1536);
    for (const char* f : frames) {
        std::vector<uint8_t> px;
        int w = 0, h = 0;
        CHECK(load_rgb(f, &px, &w, &h));
        auto want = golden::load_f32(golden::dir + f + ".pv.f32");
        CHECK(want.size() == out.size());
        if (want.size() != out.size()) continue;
        std::string err;
        const auto t = std::chrono::steady_clock::now();
        CHECK(ce::prepare(px.data(), w, h, 640, 352, out.data(), &err));
        const double ms = golden::ms_since(t);
        double mx = golden::max_abs(want.data(), out.data(), out.size());
        std::printf("  %-14s %dx%d  max_abs %.2e  %.1f ms\n", f, w, h, mx, ms);
        CHECK(mx <= 1e-6);
    }
}

TEST(prepare_refuses_bad_input) {
    std::vector<uint8_t> px(16 * 16 * 3, 0);
    std::vector<float> out(11u * 20 * 2 * 2 * 1536);
    std::string err;
    CHECK(!ce::prepare(px.data(), 0, 16, 640, 352, out.data(), &err));
    CHECK(!err.empty());
    err.clear();
    CHECK(!ce::prepare(px.data(), 16, 16, 650, 352, out.data(), &err));
    CHECK(err.find("32") != std::string::npos);
}
