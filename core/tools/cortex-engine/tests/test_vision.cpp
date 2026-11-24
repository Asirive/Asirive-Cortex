#include <chrono>
#include <cstdio>
#include <string>
#include <vector>

#include "../src/vision.h"
#include "check.h"
#include "golden.h"

static const std::string kSplit = "/var/lib/cortex/bench/npu/split";
static const std::string kQnnLib = std::string(getenv("HOME") ? getenv("HOME") : "") + "/qnn-deb/x/usr/lib/aarch64-linux-gnu";

TEST(vision_open_missing_dir_is_clear_error) {
    std::string err;
    auto v = ce::Vision::open("/nope", kQnnLib, {4, 5, 6, 7}, 4, &err);
    CHECK(!v);
    CHECK(err.find("/nope") != std::string::npos);
}

TEST(vision_port_check) {
    std::string err;
    auto v = ce::Vision::open(kSplit, kQnnLib, {4, 5, 6, 7}, 4, &err);
    if (!v) std::printf("  open failed: %s\n", err.c_str());
    CHECK(v != nullptr);
    if (!v) return;
    CHECK(v->n_tokens() == 220 && v->n_embd() == 2048);
    const char* frames[] = {"t001", "t002", "t003", "t004", "t005", "t006", "t007",
                            "t008", "t009", "t010", "t011", "t012", "h008_1080p", "p001_portrait"};
    std::vector<float> feat;
    std::vector<double> all_ms;
    for (const char* f : frames) {
        auto pv = golden::load_f32(golden::dir + f + ".pv.f32");
        auto want = golden::load_f32(golden::npu_feats + f + ".npu.f32");
        CHECK(pv.size() == 11u * 20 * 2 * 2 * 1536 && want.size() == 220u * 2048);
        if (want.size() != 220u * 2048) continue;
        CHECK(v->encode(pv.data(), &feat, &err));
        std::vector<double> ms;
        for (int i = 0; i < 10; i++) {
            auto t = std::chrono::steady_clock::now();
            v->encode(pv.data(), &feat, &err);
            ms.push_back(golden::ms_since(t));
        }
        const double cos = golden::mean_row_cos(want.data(), feat.data(), 220, 2048);
        const double med = golden::median(ms);
        all_ms.push_back(med);
        std::printf("  %-14s cos %.5f  encode median %.1f ms\n", f, cos, med);
        if (std::string(f) != "p001_portrait") CHECK(cos >= 0.999);  // portrait is out of scope
    }
    std::printf("  stages (last frame):");
    double npu = 0, cpu = 0, q = 0, x = 0, d = 0;
    for (auto& [k, ms] : v->last_ms()) {
        std::printf(" %s %.1f", k.c_str(), ms);
        if (k.find(':') != std::string::npos) {
            (k.back() == 'q' ? q : k.back() == 'x' ? x : d) += ms;
            continue;
        }
        (k[0] == 'n' ? npu : cpu) += ms;
    }
    std::printf("\n  npu split: quantise %.1f, execute %.1f, dequantise %.1f ms", q, x, d);
    std::printf("\n  npu %.1f ms, islands %.1f ms, encode median over frames %.1f ms\n", npu, cpu, golden::median(all_ms));
    // Regression guard. Python ran 257 ms with ORT on all 8 cores incl. cpu0 (safety); the engine keeps the
    // islands on cpu4-7 and measured 282 ms (ruling, 2026-11-24).
    CHECK(golden::median(all_ms) <= 290.0);
}

// Runs after a successful open in this process: the NPU is never reopened (fastrpc reset, 2026-11-24).
TEST(vision_open_twice_refused) {
    std::string err;
    auto v = ce::Vision::open(kSplit, kQnnLib, {4, 5, 6, 7}, 4, &err);
    CHECK(!v);
    CHECK(err.find("already opened") != std::string::npos);
}
