// Glasses <-> box safety channel framing. Little-endian on the wire (the ESP32-S3 is little-endian; written out byte
// by byte anyway so the host test is the same on any machine).
#include "proto.h"

#include <string.h>

uint16_t proto_crc16(const uint8_t *p, size_t n)
{
    uint16_t crc = 0xFFFF;
    while (n--) {
        crc ^= (uint16_t)(*p++) << 8;
        for (int i = 0; i < 8; i++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

size_t proto_cobs_encode(const uint8_t *in, size_t n, uint8_t *out)
{
    size_t code_i = 0, o = 1;
    uint8_t code = 1;
    for (size_t i = 0; i < n; i++) {
        if (in[i] == 0) {
            out[code_i] = code;
            code_i = o++;
            code = 1;
            continue;
        }
        out[o++] = in[i];
        if (++code == 0xFF) {
            out[code_i] = code;
            code_i = o++;
            code = 1;
        }
    }
    out[code_i] = code;
    return o;
}

size_t proto_cobs_decode(const uint8_t *in, size_t n, uint8_t *out)
{
    size_t i = 0, o = 0;
    while (i < n) {
        uint8_t code = in[i];
        if (code == 0 || i + code > n) {
            return 0;
        }
        for (size_t k = i + 1; k < i + code; k++) {
            if (in[k] == 0) {
                return 0;
            }
            out[o++] = in[k];
        }
        i += code;
        if (code != 0xFF && i < n) {
            out[o++] = 0;
        }
    }
    return o;
}

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, uint32_t v) { put16(p, (uint16_t)v); put16(p + 2, (uint16_t)(v >> 16)); }
static void putf(uint8_t *p, float f) { uint32_t v; memcpy(&v, &f, 4); put32(p, v); }

size_t proto_frame(uint8_t type, uint8_t seq, const uint8_t *payload, size_t n, uint8_t *out)
{
    uint8_t raw[FRAME_MAX];
    if (n + 4 > FRAME_MAX - FRAME_MAX / 254 - 2) {
        return 0;
    }
    raw[0] = type;
    raw[1] = seq;
    if (n) {
        memcpy(raw + 2, payload, n);
    }
    put16(raw + 2 + n, proto_crc16(raw, 2 + n));
    size_t k = proto_cobs_encode(raw, n + 4, out);
    out[k++] = 0;
    return k;
}

#define TOF_PAYLOAD (4 + 12 + 12 + 2 + 2 * ZONES + ZONES)

size_t proto_tof(const tof_msg_t *m, uint8_t seq, uint8_t *out)
{
    uint8_t p[TOF_PAYLOAD], *q = p;
    put32(q, m->t_us); q += 4;
    for (int i = 0; i < 3; i++, q += 4) putf(q, m->accel[i]);
    for (int i = 0; i < 3; i++, q += 4) putf(q, m->dtheta[i]);
    put16(q, m->imu_n); q += 2;
    for (int i = 0; i < ZONES; i++, q += 2) put16(q, m->mm[i]);
    memcpy(q, m->status, ZONES);
    return proto_frame(T_TOF, seq, p, sizeof p, out);
}

size_t proto_status(const status_msg_t *m, uint8_t seq, uint8_t *out)
{
    uint8_t p[14];
    put16(p, m->fw_version);
    put16(p + 2, m->flags);
    put32(p + 4, m->uptime_ms);
    put16(p + 8, m->tof_errors);
    put16(p + 10, m->imu_errors);
    put16(p + 12, m->usb_drops);
    return proto_frame(T_STATUS, seq, p, sizeof p, out);
}

size_t proto_button(uint32_t t_us, uint8_t kind, uint8_t seq, uint8_t *out)
{
    uint8_t p[5];
    put32(p, t_us);
    p[4] = kind;
    return proto_frame(T_BUTTON, seq, p, sizeof p, out);
}

size_t proto_hello(uint16_t fw_version, const char *build, uint8_t seq, uint8_t *out)
{
    uint8_t p[20] = {0};
    put16(p, PROTO_VERSION);
    put16(p + 2, fw_version);
    strncpy((char *)p + 4, build ? build : "", 16);
    return proto_frame(T_HELLO, seq, p, sizeof p, out);
}

void proto_rx_init(proto_rx_t *rx, proto_cb_t cb, void *ctx)
{
    memset(rx, 0, sizeof *rx);
    rx->cb = cb;
    rx->ctx = ctx;
}

static void rx_frame(proto_rx_t *rx)
{
    uint8_t raw[FRAME_MAX];
    size_t n = proto_cobs_decode(rx->buf, rx->len, raw);
    if (n < 4) {
        rx->bad++;
        return;
    }
    uint16_t crc = (uint16_t)(raw[n - 2] | (raw[n - 1] << 8));
    if (proto_crc16(raw, n - 2) != crc) {
        rx->bad++;
        return;
    }
    rx->cb(raw[0], raw[1], raw + 2, n - 4, rx->ctx);
}

void proto_rx_feed(proto_rx_t *rx, const uint8_t *data, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        uint8_t b = data[i];
        if (b == 0) {
            if (rx->len && !rx->skip) {
                rx_frame(rx);
            }
            rx->len = 0;
            rx->skip = 0;
        } else if (rx->skip) {
            continue;
        } else if (rx->len < sizeof rx->buf) {
            rx->buf[rx->len++] = b;
        } else {
            rx->bad++;  // oversized: drop everything up to the next delimiter
            rx->skip = 1;
            rx->len = 0;
        }
    }
}

int proto_parse_haptic(const uint8_t *p, size_t n, haptic_msg_t *out)
{
    if (n < 2 || p[1] > HAPTIC_MAX_STEPS || n != 2 + 4 * (size_t)p[1]) {
        return 0;
    }
    out->prio = p[0];
    out->n = p[1];
    for (int i = 0; i < out->n; i++) {
        const uint8_t *s = p + 2 + 4 * i;
        out->steps[i].left = s[0];
        out->steps[i].right = s[1];
        out->steps[i].ms = (uint16_t)(s[2] | (s[3] << 8));
    }
    return 1;
}
