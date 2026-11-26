// The safety channel to the box (USB CDC): ToF frames, button presses and status out; haptic patterns and the
// box's 0.5 s heartbeat in. If the heartbeat was seen and then stops for 1.5 s the glasses vibrate "degraded" on
// their own every 5 s: the box's safety loop is gone and the wearer must know.
#include <string.h>

#include "app.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "logic.h"
#include "tusb.h"

static const char *TAG = "link";
static SemaphoreHandle_t s_tx;
static uint8_t s_seq;
static failsafe_t s_fs;
static proto_rx_t s_rx;
static volatile bool s_hello_due = true;

static void send_frame(const uint8_t *buf, size_t n)
{
    if (!n) {
        return;
    }
    xSemaphoreTake(s_tx, portMAX_DELAY);
    if (tud_mounted() && tud_cdc_write_available() >= n) {
        tud_cdc_write(buf, (uint32_t)n);
        tud_cdc_write_flush();
    } else {
        atomic_fetch_add(&g_status.usb_drops, 1);
    }
    xSemaphoreGive(s_tx);
}

static uint8_t next_seq(void)
{
    return __atomic_fetch_add(&s_seq, 1, __ATOMIC_RELAXED);
}

void link_send_tof(const tof_msg_t *m)
{
    uint8_t buf[FRAME_MAX];
    send_frame(buf, proto_tof(m, next_seq(), buf));
}

void link_send_button(uint8_t kind, uint32_t t_us)
{
    uint8_t buf[FRAME_MAX];
    send_frame(buf, proto_button(t_us, kind, next_seq(), buf));
}

static void on_packet(uint8_t type, uint8_t seq, const uint8_t *p, size_t n, void *ctx)
{
    (void)seq;
    (void)ctx;
    if (type == T_BEAT) {
        if (!s_fs.armed || s_fs.active) {
            s_hello_due = true;  // (re)connected box: say who we are
        }
        failsafe_beat(&s_fs, now_ms());
    } else if (type == T_HAPTIC) {
        haptic_msg_t m;
        if (proto_parse_haptic(p, n, &m)) {
            haptic_play(&m);
        } else {
            s_rx.bad++;
        }
    }
}

// TinyUSB: host opened the port (DTR) -> greet it
void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts)
{
    (void)itf;
    (void)rts;
    if (dtr) {
        s_hello_due = true;
    }
}

static void link_task(void *arg)
{
    (void)arg;
    uint8_t in[64], buf[FRAME_MAX];
    uint32_t last_status = 0;
    for (;;) {
        while (tud_cdc_available()) {
            uint32_t k = tud_cdc_read(in, sizeof in);
            proto_rx_feed(&s_rx, in, k);
        }
        uint32_t now = now_ms();
        if (failsafe_poll(&s_fs, now)) {
            ESP_LOGW(TAG, "no heartbeat from the box for %u ms: degraded", (unsigned)(now - s_fs.last_beat));
            haptic_play(&PATTERN_DEGRADED);
        }
        status_set(FLAG_HOST, s_fs.armed && !s_fs.active);
        status_set(FLAG_FAILSAFE, s_fs.active);
        if (s_hello_due && tud_mounted()) {
            s_hello_due = false;
            send_frame(buf, proto_hello(FW_VERSION, FW_BUILD, next_seq(), buf));
        }
        if (now - last_status >= 1000) {
            last_status = now;
            status_msg_t st = {
                .fw_version = FW_VERSION,
                .flags = (uint16_t)atomic_load(&g_status.flags),
                .uptime_ms = now,
                .tof_errors = (uint16_t)atomic_load(&g_status.tof_errors),
                .imu_errors = (uint16_t)atomic_load(&g_status.imu_errors),
                .usb_drops = (uint16_t)atomic_load(&g_status.usb_drops),
            };
            send_frame(buf, proto_status(&st, next_seq(), buf));
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void link_start(void)
{
    s_tx = xSemaphoreCreateMutex();
    failsafe_init(&s_fs);
    proto_rx_init(&s_rx, on_packet, NULL);
    xTaskCreatePinnedToCore(link_task, "link", 4096, NULL, 8, NULL, 0);
}
