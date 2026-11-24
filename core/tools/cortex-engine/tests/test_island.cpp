#include <cmath>
#include <cstdio>
#include <random>
#include <vector>

#include "../src/island.h"
#include "check.h"
#include "golden.h"

// softmax(Q Kt * s) V per head; layout [tok, heads, dim] in and out.
static void naive(const float* q, const float* k, const float* v, float* out, int T, int H, int D, float s) {
    std::vector<double> p(T);
    for (int h = 0; h < H; h++)
        for (int i = 0; i < T; i++) {
            double mx = -1e30;
            for (int j = 0; j < T; j++) {
                double d = 0;
                for (int c = 0; c < D; c++) d += (double)q[(i * H + h) * D + c] * k[(j * H + h) * D + c];
                p[j] = d * s;
                mx = std::max(mx, p[j]);
            }
            double z = 0;
            for (int j = 0; j < T; j++) z += (p[j] = std::exp(p[j] - mx));
            for (int c = 0; c < D; c++) {
                double o = 0;
                for (int j = 0; j < T; j++) o += p[j] / z * v[(j * H + h) * D + c];
                out[(i * H + h) * D + c] = (float)o;
            }
        }
}

TEST(island_matches_naive) {
    const int T = 32, H = 4, D = 64;
    std::mt19937 rng(7);
    std::normal_distribution<float> nd(0.f, 1.f);
    std::vector<float> q(T * H * D), k(q.size()), v(q.size()), want(q.size()), got(q.size());
    for (auto* x : {&q, &k, &v})
        for (auto& e : *x) e = nd(rng);
    naive(q.data(), k.data(), v.data(), want.data(), T, H, D, 0.125f);
    ce::Island isl(T, H, D, 0.125f, {4, 5, 6, 7}, 4);
    isl.run(q.data(), k.data(), v.data(), got.data());
    CHECK(golden::max_abs(want.data(), got.data(), want.size()) <= 2e-3);
}

// the small-core pool computes the same island (what the engine runs during an answer)
TEST(island_small_pool_matches_big) {
    auto q = golden::load_f32(golden::dir + "island1_q.f32"), k = golden::load_f32(golden::dir + "island1_k.f32"),
         v = golden::load_f32(golden::dir + "island1_v.f32");
    CHECK(q.size() == 880u * 16 * 64);
    if (q.size() != 880u * 16 * 64) return;
    std::vector<float> big(q.size()), small(q.size());
    ce::Island isl(880, 16, 64, 0.125f, {4, 5, 6, 7}, 4, {1, 2});
    isl.run(q.data(), k.data(), v.data(), big.data(), false);
    const double big_ms = isl.last_ms();
    isl.run(q.data(), k.data(), v.data(), small.data(), true);
    const double small_ms = isl.last_ms();
    const double d = golden::max_abs(big.data(), small.data(), big.size());
    std::printf("  island1: big cores %.1f ms, small cores %.1f ms, max |diff| %.2e\n", big_ms, small_ms, d);
    CHECK(d <= 1e-6);
}

TEST(island_matches_onnx_golden) {
    auto q = golden::load_f32(golden::dir + "island1_q.f32"), k = golden::load_f32(golden::dir + "island1_k.f32"),
         v = golden::load_f32(golden::dir + "island1_v.f32"), want = golden::load_f32(golden::dir + "island1_out.f32");
    CHECK(q.size() == 880u * 16 * 64 && want.size() == q.size());
    if (want.size() != q.size()) return;
    std::vector<float> got(want.size());
    ce::Island isl(880, 16, 64, 0.125f, {4, 5, 6, 7}, 4);
    isl.run(q.data(), k.data(), v.data(), got.data());
    double cos = golden::mean_row_cos(want.data(), got.data(), 880, 1024);
    double mx = golden::max_abs(want.data(), got.data(), want.size());
    std::printf("  island1 vs ONNX: cos %.6f max_abs %.2e\n", cos, mx);
    CHECK(cos >= 0.9999);
    CHECK(mx <= 1e-2);
}

TEST(island_timing) {
    auto q = golden::load_f32(golden::dir + "island1_q.f32"), k = golden::load_f32(golden::dir + "island1_k.f32"),
         v = golden::load_f32(golden::dir + "island1_v.f32");
    if (q.size() != 880u * 16 * 64) return;
    std::vector<float> out(q.size());
    struct Set { std::vector<int> cpus; const char* name; } sets[] = {{{1, 2, 3}, "small cpu1-3"}, {{4, 5, 6, 7}, "big cpu4-7"},
                                                                {{1, 2, 3, 4, 5, 6, 7}, "cpu1-7"}};
    for (auto& s : sets) {
        ce::Island isl(880, 16, 64, 0.125f, s.cpus, (int)s.cpus.size());
        isl.run(q.data(), k.data(), v.data(), out.data());  // warm
        std::vector<double> ms;
        for (int i = 0; i < 10; i++) {
            isl.run(q.data(), k.data(), v.data(), out.data());
            ms.push_back(isl.last_ms());
        }
        std::printf("  island median %s: %.1f ms\n", s.name, golden::median(ms));
    }
}
