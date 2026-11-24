#include "fixed.h"

#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <map>
#include <stdexcept>

namespace ce {

size_t qtype_bytes(QType t) {
    switch (t) {
        case QType::F32: return 4;
        case QType::U16: return 2;
        case QType::U8: return 1;
    }
    throw std::runtime_error("unsupported QNN dtype");
}

template <typename T>
static void quant(const float* x, size_t n, float scale, int offset, T* out) {
    const float maxv = (float)((1u << (8 * sizeof(T))) - 1);
    for (size_t i = 0; i < n; i++) {
        float q = std::nearbyint(x[i] / scale) - (float)offset;  // default rounding mode = half to even
        out[i] = (T)(q < 0.f ? 0.f : (q > maxv ? maxv : q));
    }
}

void to_fixed(const float* x, size_t n, QType t, float scale, int offset, void* out) {
    switch (t) {
        case QType::F32: std::memcpy(out, x, n * sizeof(float)); return;
        case QType::U16: quant(x, n, scale, offset, static_cast<uint16_t*>(out)); return;
        case QType::U8: quant(x, n, scale, offset, static_cast<uint8_t*>(out)); return;
    }
    throw std::runtime_error("unsupported QNN dtype");
}

template <typename T>
static void dequant(const T* q, size_t n, float scale, int offset, float* out) {
    for (size_t i = 0; i < n; i++) out[i] = ((float)q[i] + (float)offset) * scale;
}

void from_fixed(const void* q, size_t n, QType t, float scale, int offset, float* out) {
    switch (t) {
        case QType::F32: std::memcpy(out, q, n * sizeof(float)); return;
        case QType::U16: dequant(static_cast<const uint16_t*>(q), n, scale, offset, out); return;
        case QType::U8: dequant(static_cast<const uint8_t*>(q), n, scale, offset, out); return;
    }
    throw std::runtime_error("unsupported QNN dtype");
}

std::string sanitize(const std::string& name) {
    std::string s = name;
    for (char& c : s)
        if (!std::isalnum((unsigned char)c)) c = '_';
    size_t i = s.find_first_not_of('_');
    return i == std::string::npos ? std::string() : s.substr(i);
}

std::vector<std::string> match_names(const std::vector<std::string>& qnn, const std::vector<std::string>& onnx) {
    std::map<std::string, std::string> by;
    for (const auto& n : onnx) by[sanitize(n)] = n;
    std::vector<std::string> out;
    for (const auto& q : qnn) {
        auto it = by.find(sanitize(q));
        if (it == by.end()) throw std::runtime_error("QNN tensor '" + q + "' matches no ONNX name");
        out.push_back(it->second);
    }
    return out;
}

}  // namespace ce
