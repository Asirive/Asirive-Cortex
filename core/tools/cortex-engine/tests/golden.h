// Helpers for tests that read reference data from /var/lib/cortex/bench/engine/golden (box only, not in git).
#pragma once
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <string>
#include <vector>

namespace golden {
inline const std::string dir = "/var/lib/cortex/bench/engine/golden/";
inline const std::string review = "/var/lib/cortex/bench/npu/test_review/";

inline std::vector<float> load_f32(const std::string& path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) return {};
    std::vector<float> v((size_t)f.tellg() / sizeof(float));
    f.seekg(0);
    f.read(reinterpret_cast<char*>(v.data()), (std::streamsize)(v.size() * sizeof(float)));
    return v;
}

// mean over rows of the cosine between matching rows of width w
inline double mean_row_cos(const float* a, const float* b, size_t rows, size_t w) {
    double s = 0;
    for (size_t r = 0; r < rows; r++) {
        double d = 0, na = 0, nb = 0;
        for (size_t i = 0; i < w; i++) {
            d += (double)a[r * w + i] * b[r * w + i];
            na += (double)a[r * w + i] * a[r * w + i];
            nb += (double)b[r * w + i] * b[r * w + i];
        }
        s += d / (std::sqrt(na * nb) + 1e-12);
    }
    return s / rows;
}

inline double max_abs(const float* a, const float* b, size_t n) {
    double m = 0;
    for (size_t i = 0; i < n; i++) m = std::max(m, (double)std::fabs(a[i] - b[i]));
    return m;
}

inline double median(std::vector<double> v) {
    std::sort(v.begin(), v.end());
    return v.empty() ? 0 : v[v.size() / 2];
}

inline double ms_since(std::chrono::steady_clock::time_point t) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t).count();
}
}  // namespace golden
