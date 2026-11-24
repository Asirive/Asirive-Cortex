#include "prep.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <vector>

namespace ce {

namespace {
constexpr int kPatch = 16, kMerge = 2, kTemporal = 2, kBlock = kPatch * kMerge;

// --- Pillow's resample (src/libImaging/Resample.c), 8 bits per channel, bicubic a = -0.5 ---
constexpr int kPrecisionBits = 32 - 8 - 2;

double bicubic(double x) {
    const double a = -0.5;
    if (x < 0.0) x = -x;
    if (x < 1.0) return ((a + 2.0) * x - (a + 3.0)) * x * x + 1;
    if (x < 2.0) return (((x - 5) * x + 8) * x - 4) * a;
    return 0.0;
}

struct Coeffs {
    int ksize = 0;
    std::vector<int> bounds;  // per output: xmin, xmax (count)
    std::vector<int> kk;      // fixed-point weights, ksize per output
};

Coeffs precompute(int in_size, int out_size) {
    const double in0 = 0, in1 = in_size;
    const double scale = (in1 - in0) / out_size;
    const double filterscale = scale < 1.0 ? 1.0 : scale;
    const double support = 2.0 * filterscale;
    Coeffs c;
    c.ksize = (int)std::ceil(support) * 2 + 1;
    c.bounds.resize((size_t)out_size * 2);
    std::vector<double> pre((size_t)out_size * c.ksize);
    for (int xx = 0; xx < out_size; xx++) {
        const double center = in0 + (xx + 0.5) * scale;
        const double ss = 1.0 / filterscale;
        int xmin = (int)(center - support + 0.5);
        if (xmin < 0) xmin = 0;
        int xmax = (int)(center + support + 0.5);
        if (xmax > in_size) xmax = in_size;
        xmax -= xmin;
        double* k = &pre[(size_t)xx * c.ksize];
        double ww = 0.0;
        int x = 0;
        for (; x < xmax; x++) {
            const double w = bicubic((x + xmin - center + 0.5) * ss);
            k[x] = w;
            ww += w;
        }
        for (x = 0; x < xmax; x++)
            if (ww != 0.0) k[x] /= ww;
        for (; x < c.ksize; x++) k[x] = 0;
        c.bounds[xx * 2] = xmin;
        c.bounds[xx * 2 + 1] = xmax;
    }
    c.kk.resize(pre.size());
    for (size_t i = 0; i < pre.size(); i++)
        c.kk[i] = pre[i] < 0 ? (int)(-0.5 + pre[i] * (1 << kPrecisionBits)) : (int)(0.5 + pre[i] * (1 << kPrecisionBits));
    return c;
}

inline uint8_t clip8(int v) {
    if (v >= (1 << kPrecisionBits) << 8) return 255;
    if (v <= 0) return 0;
    return (uint8_t)(v >> kPrecisionBits);
}

// rgb [h][w][3] -> [h][ow][3]
std::vector<uint8_t> resample_h(const std::vector<uint8_t>& in, int w, int h, int ow) {
    Coeffs c = precompute(w, ow);
    std::vector<uint8_t> out((size_t)h * ow * 3);
    for (int y = 0; y < h; y++)
        for (int xx = 0; xx < ow; xx++) {
            const int xmin = c.bounds[xx * 2], xmax = c.bounds[xx * 2 + 1];
            const int* k = &c.kk[(size_t)xx * c.ksize];
            int s0 = 1 << (kPrecisionBits - 1), s1 = s0, s2 = s0;
            for (int x = 0; x < xmax; x++) {
                const uint8_t* p = &in[((size_t)y * w + x + xmin) * 3];
                s0 += p[0] * k[x], s1 += p[1] * k[x], s2 += p[2] * k[x];
            }
            uint8_t* o = &out[((size_t)y * ow + xx) * 3];
            o[0] = clip8(s0), o[1] = clip8(s1), o[2] = clip8(s2);
        }
    return out;
}

// rgb [h][w][3] -> [oh][w][3]
std::vector<uint8_t> resample_v(const std::vector<uint8_t>& in, int w, int h, int oh) {
    Coeffs c = precompute(h, oh);
    std::vector<uint8_t> out((size_t)oh * w * 3);
    for (int yy = 0; yy < oh; yy++) {
        const int ymin = c.bounds[yy * 2], ymax = c.bounds[yy * 2 + 1];
        const int* k = &c.kk[(size_t)yy * c.ksize];
        for (int xx = 0; xx < w; xx++) {
            int s0 = 1 << (kPrecisionBits - 1), s1 = s0, s2 = s0;
            for (int y = 0; y < ymax; y++) {
                const uint8_t* p = &in[((size_t)(y + ymin) * w + xx) * 3];
                s0 += p[0] * k[y], s1 += p[1] * k[y], s2 += p[2] * k[y];
            }
            uint8_t* o = &out[((size_t)yy * w + xx) * 3];
            o[0] = clip8(s0), o[1] = clip8(s1), o[2] = clip8(s2);
        }
    }
    return out;
}
}  // namespace

std::pair<int, int> fit_box(int w, int h, int cw, int ch) {
    const double scale = std::min((double)cw / w, (double)ch / h);
    // Python's round() is round-half-to-even, like nearbyint in the default rounding mode
    const int nw = std::max(1, (int)std::nearbyint(w * scale)), nh = std::max(1, (int)std::nearbyint(h * scale));
    if (cw - nw < kBlock && ch - nh < kBlock) return {cw, ch};
    return {nw, nh};
}

bool prepare(const uint8_t* rgb, int w, int h, int cw, int ch, float* out, std::string* err) {
    if (w <= 0 || h <= 0) {
        if (err) *err = "frame size must be positive";
        return false;
    }
    if (cw <= 0 || ch <= 0 || cw % kBlock || ch % kBlock) {
        if (err) *err = "canvas sides must be positive multiples of 32";
        return false;
    }
    auto [nw, nh] = fit_box(w, h, cw, ch);
    std::vector<uint8_t> img(rgb, rgb + (size_t)w * h * 3);
    if (nw != w) img = resample_h(img, w, h, nw);  // Pillow does the horizontal pass first
    if (nh != h) img = resample_v(img, nw, h, nh);
    const int top = (ch - nh) / 2, left = (cw - nw) / 2;
    const int gh = ch / kPatch, gw = cw / kPatch, bh_n = gh / kMerge, bw_n = gw / kMerge;
    const size_t block = (size_t)3 * kTemporal * kPatch * kPatch;  // 1536
    for (int bh = 0; bh < bh_n; bh++)
        for (int bw = 0; bw < bw_n; bw++)
            for (int mh = 0; mh < kMerge; mh++)
                for (int mw = 0; mw < kMerge; mw++) {
                    float* o = out + ((((size_t)bh * bw_n + bw) * kMerge + mh) * kMerge + mw) * block;
                    for (int c = 0; c < 3; c++)
                        for (int py = 0; py < kPatch; py++)
                            for (int px = 0; px < kPatch; px++) {
                                const int y = (bh * kMerge + mh) * kPatch + py - top;
                                const int x = (bw * kMerge + mw) * kPatch + px - left;
                                float v = 0.0f;  // padding: neutral grey after normalising
                                if (y >= 0 && y < nh && x >= 0 && x < nw)
                                    v = ((float)img[((size_t)y * nw + x) * 3 + c] / 255.0f - 0.5f) / 0.5f;
                                for (int t = 0; t < kTemporal; t++)
                                    o[((size_t)(c * kTemporal + t) * kPatch + py) * kPatch + px] = v;
                            }
                }
    return true;
}

}  // namespace ce
