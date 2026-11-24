// Frame -> pixel_values for the vision encoder, the C++ twin of cortex_core/npu/vision_prep.prepare:
// fit inside the canvas keeping aspect (a leftover under 32 px is stretched away, a bigger one is centre-padded
// with 0.0 = neutral grey), resize with Pillow's BICUBIC (same 8-bit fixed-point algorithm, so the output is
// identical), normalise (x/255 - 0.5)/0.5, and lay out [ch/32, cw/32, 2, 2, 1536] with the frame repeated in both
// time slots.
#pragma once
#include <cstdint>
#include <string>
#include <utility>

namespace ce {

std::pair<int, int> fit_box(int w, int h, int canvas_w, int canvas_h);
// rgb: h*w*3 uint8. out: (canvas_h/32)*(canvas_w/32)*2*2*1536 floats.
bool prepare(const uint8_t* rgb, int w, int h, int canvas_w, int canvas_h, float* out, std::string* err);

}  // namespace ce
