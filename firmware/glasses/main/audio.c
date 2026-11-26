// USB audio class 2: two PDM mics (mouth, ambient) -> 16 kHz stereo in; 16 kHz mono out -> MAX98357A.
// The speaker endpoint is adaptive without feedback (no IN endpoint left for it), so host and I2S clocks drift
// against each other; the output buffer absorbs it and an under/overrun drops or pads a few ms, inaudible in speech.
#include <math.h>
#include <string.h>

#include "app.h"
#include "board.h"
#include "driver/i2s_pdm.h"
#include "driver/i2s_std.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"

static const char *TAG = "audio";
static i2s_chan_handle_t s_rx, s_tx;
static volatile bool s_mic_on, s_spk_on;
static volatile bool s_mute;
static volatile int16_t s_volume_db256;  // 1/256 dB, 0 = full
static volatile float s_gain = 1.0f;

// ---------------------------------------------------------------- UAC2 class requests (clock, speaker FU)
static bool clock_get(uint8_t rhport, tusb_control_request_t const *r)
{
    uint8_t sel = TU_U16_HIGH(r->wValue);
    if (sel == AUDIO20_CS_CTRL_SAM_FREQ && r->bRequest == AUDIO20_CS_REQ_CUR) {
        audio20_control_cur_4_t cur = {.bCur = (int32_t)tu_htole32(AUDIO_SAMPLE_RATE)};
        return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &cur, sizeof cur);
    }
    if (sel == AUDIO20_CS_CTRL_SAM_FREQ && r->bRequest == AUDIO20_CS_REQ_RANGE) {
        audio20_control_range_4_n_t(1) range = {.wNumSubRanges = tu_htole16(1)};
        range.subrange[0].bMin = AUDIO_SAMPLE_RATE;
        range.subrange[0].bMax = AUDIO_SAMPLE_RATE;
        range.subrange[0].bRes = 0;
        return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &range, sizeof range);
    }
    if (sel == AUDIO20_CS_CTRL_CLK_VALID && r->bRequest == AUDIO20_CS_REQ_CUR) {
        audio20_control_cur_1_t valid = {.bCur = 1};
        return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &valid, sizeof valid);
    }
    return false;
}

static bool clock_set(tusb_control_request_t const *r, uint8_t const *buf)
{
    // one fixed rate: accept the host setting it to that rate, refuse anything else
    return TU_U16_HIGH(r->wValue) == AUDIO20_CS_CTRL_SAM_FREQ && r->bRequest == AUDIO20_CS_REQ_CUR
        && r->wLength == sizeof(audio20_control_cur_4_t)
        && ((audio20_control_cur_4_t const *)buf)->bCur == AUDIO_SAMPLE_RATE;
}

static bool fu_get(uint8_t rhport, tusb_control_request_t const *r)
{
    uint8_t sel = TU_U16_HIGH(r->wValue);
    if (sel == AUDIO20_FU_CTRL_MUTE && r->bRequest == AUDIO20_CS_REQ_CUR) {
        audio20_control_cur_1_t m = {.bCur = s_mute};
        return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &m, sizeof m);
    }
    if (sel == AUDIO20_FU_CTRL_VOLUME && r->bRequest == AUDIO20_CS_REQ_RANGE) {
        audio20_control_range_2_n_t(1) range = {.wNumSubRanges = tu_htole16(1)};
        range.subrange[0].bMin = tu_htole16(-50 * 256);
        range.subrange[0].bMax = 0;
        range.subrange[0].bRes = tu_htole16(256);
        return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &range, sizeof range);
    }
    if (sel == AUDIO20_FU_CTRL_VOLUME && r->bRequest == AUDIO20_CS_REQ_CUR) {
        audio20_control_cur_2_t v = {.bCur = tu_htole16(s_volume_db256)};
        return tud_audio_buffer_and_schedule_control_xfer(rhport, r, &v, sizeof v);
    }
    return false;
}

static bool fu_set(tusb_control_request_t const *r, uint8_t const *buf)
{
    uint8_t sel = TU_U16_HIGH(r->wValue);
    if (r->bRequest != AUDIO20_CS_REQ_CUR) {
        return false;
    }
    if (sel == AUDIO20_FU_CTRL_MUTE && r->wLength == sizeof(audio20_control_cur_1_t)) {
        s_mute = ((audio20_control_cur_1_t const *)buf)->bCur != 0;
        return true;
    }
    if (sel == AUDIO20_FU_CTRL_VOLUME && r->wLength == sizeof(audio20_control_cur_2_t)) {
        int16_t v = ((audio20_control_cur_2_t const *)buf)->bCur;
        s_volume_db256 = v;
        s_gain = powf(10.0f, (float)v / 256.0f / 20.0f);
        return true;
    }
    return false;
}

bool tud_audio_get_req_entity_cb(uint8_t rhport, tusb_control_request_t const *r)
{
    uint8_t entity = TU_U16_HIGH(r->wIndex);
    if (entity == UAC2_ENTITY_CLOCK) {
        return clock_get(rhport, r);
    }
    if (entity == UAC2_ENTITY_SPK_FEATURE_UNIT) {
        return fu_get(rhport, r);
    }
    return false;
}

bool tud_audio_set_req_entity_cb(uint8_t rhport, tusb_control_request_t const *r, uint8_t *buf)
{
    (void)rhport;
    uint8_t entity = TU_U16_HIGH(r->wIndex);
    if (entity == UAC2_ENTITY_CLOCK) {
        return clock_set(r, buf);
    }
    if (entity == UAC2_ENTITY_SPK_FEATURE_UNIT) {
        return fu_set(r, buf);
    }
    return false;
}

static void set_alt(tusb_control_request_t const *r, bool closing)
{
    uint8_t itf = tu_u16_low(r->wIndex), alt = tu_u16_low(r->wValue);
    bool on = !closing && alt != 0;
    if (itf == ITF_NUM_AUDIO_STREAMING_MIC) {
        s_mic_on = on;
    } else if (itf == ITF_NUM_AUDIO_STREAMING_SPK) {
        s_spk_on = on;
    }
}

bool tud_audio_set_itf_cb(uint8_t rhport, tusb_control_request_t const *r)
{
    (void)rhport;
    set_alt(r, false);
    return true;
}

bool tud_audio_set_itf_close_ep_cb(uint8_t rhport, tusb_control_request_t const *r)
{
    (void)rhport;
    set_alt(r, true);
    return true;
}

// ---------------------------------------------------------------- data paths
static void mic_task(void *arg)
{
    (void)arg;
    static int16_t buf[AUDIO_SAMPLE_RATE / 100 * 2];  // 10 ms stereo
    for (;;) {
        size_t got = 0;
        if (i2s_channel_read(s_rx, buf, sizeof buf, &got, portMAX_DELAY) == ESP_OK && got && s_mic_on) {
            tud_audio_write(buf, (uint16_t)got);  // a full FIFO (host not reading) drops the rest
        }
    }
}

static void spk_task(void *arg)
{
    (void)arg;
    static int16_t buf[AUDIO_SAMPLE_RATE / 100];  // 10 ms mono
    for (;;) {
        size_t n = 0;
        if (s_spk_on && tud_audio_available() >= sizeof buf) {
            n = tud_audio_read(buf, sizeof buf);
        }
        if (n < sizeof buf || s_mute) {
            memset((uint8_t *)buf + (s_mute ? 0 : n), 0, sizeof buf - (s_mute ? 0 : n));  // keep the amp fed: no pops
        } else if (s_gain < 0.999f) {
            for (size_t i = 0; i < n / 2; i++) {
                buf[i] = (int16_t)((float)buf[i] * s_gain);
            }
        }
        size_t wrote;
        i2s_channel_write(s_tx, buf, sizeof buf, &wrote, portMAX_DELAY);  // paces this loop at the I2S rate
    }
}

void audio_start(void)
{
    // mics: PDM RX exists on I2S0 only
    i2s_chan_config_t rc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    i2s_pdm_rx_config_t pdm = {
        .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE),
        .slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.clk = PDM_PIN_CLK, .din = PDM_PIN_DATA},
    };
    bool mic = i2s_new_channel(&rc, NULL, &s_rx) == ESP_OK && i2s_channel_init_pdm_rx_mode(s_rx, &pdm) == ESP_OK
        && i2s_channel_enable(s_rx) == ESP_OK;
    status_set(FLAG_MIC, mic);

    // amp: standard I2S on I2S1, ~40 ms of buffering
    i2s_chan_config_t tc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    tc.dma_desc_num = 4;
    tc.dma_frame_num = AUDIO_SAMPLE_RATE / 100;
    tc.auto_clear = true;
    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {.mclk = I2S_GPIO_UNUSED, .bclk = AMP_PIN_BCLK, .ws = AMP_PIN_WS, .dout = AMP_PIN_DOUT,
                     .din = I2S_GPIO_UNUSED},
    };
    std.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;  // same sample on both slots: the amp's channel strap doesn't matter
    bool amp = i2s_new_channel(&tc, &s_tx, NULL) == ESP_OK && i2s_channel_init_std_mode(s_tx, &std) == ESP_OK
        && i2s_channel_enable(s_tx) == ESP_OK;
    status_set(FLAG_AMP, amp);
    ESP_LOGI(TAG, "mics %s, amp %s", mic ? "ok" : "FAILED", amp ? "ok" : "FAILED");

    if (mic) {
        xTaskCreatePinnedToCore(mic_task, "mic", 3072, NULL, 7, NULL, 1);
    }
    if (amp) {
        xTaskCreatePinnedToCore(spk_task, "spk", 3072, NULL, 7, NULL, 1);
    }
}
