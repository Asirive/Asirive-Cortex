// Glasses <-> box safety channel (USB CDC). Spec: docs/architecture/GLASSES-USB.md.
// Box side: core/cortex_core/safety/glasses.py. Portable C (no ESP-IDF): compiled on the host by the cross test.
#pragma once
#include <stddef.h>
#include <stdint.h>

#define PROTO_VERSION 1

enum {
    T_TOF = 0x01, T_STATUS = 0x02, T_BUTTON = 0x03, T_HELLO = 0x04,  // glasses -> box
    T_HAPTIC = 0x10, T_BEAT = 0x11,                                   // box -> glasses
};

enum {
    FLAG_TOF = 1 << 0, FLAG_IMU = 1 << 1, FLAG_CAM = 1 << 2, FLAG_MIC = 1 << 3,
    FLAG_AMP = 1 << 4, FLAG_HOST = 1 << 5, FLAG_FAILSAFE = 1 << 6,
};

enum { BUTTON_TAP = 1, BUTTON_LONG = 2 };

#define ZONES 64
#define HAPTIC_MAX_STEPS 12
#define FRAME_MAX 512   // largest encoded frame (ToF: 2 + 222 + 2 bytes, COBS + delimiter < 240)

typedef struct {
    uint32_t t_us;
    float accel[3];      // g, mean over the frame, chip axes
    float dtheta[3];     // rad, gyro summed over the frame, chip axes
    uint16_t imu_n;      // IMU samples in the sums
    uint16_t mm[ZONES];  // ULD zone order; 0 = no target
    uint8_t status[ZONES];
} tof_msg_t;

typedef struct {
    uint16_t fw_version, flags;
    uint32_t uptime_ms;
    uint16_t tof_errors, imu_errors, usb_drops;
} status_msg_t;

typedef struct {
    uint8_t left, right;  // PWM duty 0-255
    uint16_t ms;
} haptic_step_t;

typedef struct {
    uint8_t prio;  // 0 info (tick), 1 warning, 2 degraded; equal or higher replaces what is playing
    uint8_t n;
    haptic_step_t steps[HAPTIC_MAX_STEPS];
} haptic_msg_t;

uint16_t proto_crc16(const uint8_t *p, size_t n);
size_t proto_cobs_encode(const uint8_t *in, size_t n, uint8_t *out);           // out >= n + n/254 + 1
size_t proto_cobs_decode(const uint8_t *in, size_t n, uint8_t *out);           // 0 = corrupt

// Build one wire frame (COBS + 0x00) of type/seq/payload into out (>= FRAME_MAX). Returns its length, 0 if too big.
size_t proto_frame(uint8_t type, uint8_t seq, const uint8_t *payload, size_t n, uint8_t *out);

size_t proto_tof(const tof_msg_t *m, uint8_t seq, uint8_t *out);
size_t proto_status(const status_msg_t *m, uint8_t seq, uint8_t *out);
size_t proto_button(uint32_t t_us, uint8_t kind, uint8_t seq, uint8_t *out);
size_t proto_hello(uint16_t fw_version, const char *build, uint8_t seq, uint8_t *out);

// Receiving: feed bytes as they come; on_packet runs for every frame whose CRC is good.
typedef void (*proto_cb_t)(uint8_t type, uint8_t seq, const uint8_t *payload, size_t n, void *ctx);
typedef struct {
    uint8_t buf[FRAME_MAX];
    size_t len;
    uint8_t skip;     // inside an oversized frame
    uint32_t bad;     // corrupt or oversized frames dropped
    proto_cb_t cb;
    void *ctx;
} proto_rx_t;

void proto_rx_init(proto_rx_t *rx, proto_cb_t cb, void *ctx);
void proto_rx_feed(proto_rx_t *rx, const uint8_t *data, size_t n);

// Payload parsers (box -> glasses). Return 0 if malformed.
int proto_parse_haptic(const uint8_t *p, size_t n, haptic_msg_t *out);
