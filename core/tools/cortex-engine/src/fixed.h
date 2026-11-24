// QNN fixed-point conversion and tensor-name matching, the C++ twin of cortex_core/npu/qnn.py.
// QNN convention: float = (q + offset) * scale.
#pragma once
#include <cstddef>
#include <string>
#include <vector>

namespace ce {

enum class QType { F32 = 0x0232, U8 = 0x0408, U16 = 0x0416 };

size_t qtype_bytes(QType t);
// q = rint(x / scale) - offset (round half to even, like numpy), clipped to the type's range.
void to_fixed(const float* x, size_t n, QType t, float scale, int offset, void* out);
void from_fixed(const void* q, size_t n, QType t, float scale, int offset, float* out);

// QNN converters replace punctuation in names: non-alnum -> '_', leading '_' stripped.
std::string sanitize(const std::string& onnx_name);
// Maps each QNN name back to its ONNX name; throws std::runtime_error naming an unmatched one.
std::vector<std::string> match_names(const std::vector<std::string>& qnn, const std::vector<std::string>& onnx);

}  // namespace ce
