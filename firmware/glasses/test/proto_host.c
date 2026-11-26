// Host harness for the cross test (core/tests/test_glasses_link.py): the firmware's own framing code, run on the
// server. "encode" writes known frames to stdout; "decode" reads frames from stdin and prints what it parsed.
#include <stdio.h>
#include <string.h>

#include "../main/proto.h"

static void on_packet(uint8_t type, uint8_t seq, const uint8_t *p, size_t n, void *ctx)
{
    (void)ctx;
    printf("%u %u", type, seq);
    if (type == T_HAPTIC) {
        haptic_msg_t h;
        if (!proto_parse_haptic(p, n, &h)) {
            printf(" bad\n");
            return;
        }
        printf(" prio=%u", h.prio);
        for (int i = 0; i < h.n; i++) {
            printf(" %u,%u,%u", h.steps[i].left, h.steps[i].right, h.steps[i].ms);
        }
    } else {
        printf(" ");
        for (size_t i = 0; i < n; i++) {
            printf("%02x", p[i]);
        }
    }
    printf("\n");
}

int main(int argc, char **argv)
{
    uint8_t out[FRAME_MAX];
    if (argc > 1 && strcmp(argv[1], "encode") == 0) {
        size_t k = proto_hello(7, "a1-test", 1, out);
        fwrite(out, 1, k, stdout);
        tof_msg_t m = {.t_us = 4294967000u, .accel = {0.01f, -0.25f, 0.97f}, .dtheta = {0.002f, -0.001f, 0.05f}, .imu_n = 14};
        for (int i = 0; i < ZONES; i++) {
            m.mm[i] = (uint16_t)(i == 5 ? 0 : 100 * i + (i % 3 == 0 ? 0 : 256));  // includes zero bytes on purpose
            m.status[i] = (uint8_t)(i % 7 == 0 ? 255 : 5);
        }
        k = proto_tof(&m, 2, out);
        fwrite(out, 1, k, stdout);
        status_msg_t s = {.fw_version = 7, .flags = FLAG_TOF | FLAG_IMU | FLAG_HOST, .uptime_ms = 123456,
                          .tof_errors = 1, .imu_errors = 0, .usb_drops = 3};
        k = proto_status(&s, 3, out);
        fwrite(out, 1, k, stdout);
        k = proto_button(1000000, BUTTON_TAP, 4, out);
        fwrite(out, 1, k, stdout);
        return 0;
    }
    proto_rx_t rx;
    proto_rx_init(&rx, on_packet, NULL);
    uint8_t buf[256];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, stdin)) > 0) {
        proto_rx_feed(&rx, buf, n);
    }
    printf("bad %u\n", (unsigned)rx.bad);
    return 0;
}
