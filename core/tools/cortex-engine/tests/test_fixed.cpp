#include <cstdint>
#include <stdexcept>

#include "../src/fixed.h"
#include "check.h"

using ce::QType;

TEST(fixed_u16_round_trip) {
    const float x[] = {-1.5f, 0.f, 0.25f, 0.99f};
    const float scale = 1.f / 16384, off = -32768;
    uint16_t q[4];
    float back[4];
    ce::to_fixed(x, 4, QType::U16, scale, (int)off, q);
    ce::from_fixed(q, 4, QType::U16, scale, (int)off, back);
    for (int i = 0; i < 4; i++) CHECK_NEAR(back[i], x[i], scale / 2 + 1e-7);
}

TEST(fixed_u8_clips) {
    const float x[] = {-1e6f, 1e6f};
    uint8_t q[2];
    ce::to_fixed(x, 2, QType::U8, 0.01f, -128, q);
    CHECK(q[0] == 0);
    CHECK(q[1] == 255);
}

// Expected values printed by cortex_core.npu.qnn.to_fixed (numpy rint = round half to even).
TEST(fixed_matches_python_values) {
    const float x16[] = {0.1f, -0.2f, 0.7f, 0.5f};
    uint16_t q16[4];
    ce::to_fixed(x16, 4, QType::U16, 3.0517578e-05f, -16384, q16);
    const uint16_t want16[] = {19661, 9830, 39322, 32768};
    for (int i = 0; i < 4; i++) CHECK(q16[i] == want16[i]);
    const float x8[] = {0.025f, 0.035f, -0.005f};
    uint8_t q8[3];
    ce::to_fixed(x8, 3, QType::U8, 0.01f, -128, q8);
    const uint8_t want8[] = {130, 132, 128};
    for (int i = 0; i < 3; i++) CHECK(q8[i] == want8[i]);
}

TEST(fixed_f32_is_copy) {
    const float x[] = {1.25f, -3.f};
    float q[2], back[2];
    ce::to_fixed(x, 2, QType::F32, 0, 0, q);
    ce::from_fixed(q, 2, QType::F32, 0, 0, back);
    CHECK(back[0] == 1.25f && back[1] == -3.f);
}

TEST(sanitize_names) {
    CHECK(ce::sanitize("/vision_encoder/layers.2/attn/Reshape_209") == "vision_encoder_layers_2_attn_Reshape_209");
}

TEST(match_names_maps_back) {
    auto m = ce::match_names({"vision_encoder_layers_1_Add_2_output_0", "pixel_values"},
                             {"pixel_values", "/vision_encoder/layers.1/Add_2/output_0"});
    CHECK(m.size() == 2);
    CHECK(m[0] == "/vision_encoder/layers.1/Add_2/output_0");
    CHECK(m[1] == "pixel_values");
}

TEST(match_names_throws_on_missing) {
    bool threw = false;
    try {
        ce::match_names({"nope"}, {"pixel_values"});
    } catch (const std::runtime_error& e) {
        threw = std::string(e.what()).find("nope") != std::string::npos;
    }
    CHECK(threw);
}
