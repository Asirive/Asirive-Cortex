// OV5640 -> JPEG (the sensor compresses) -> USB video class, MJPEG over bulk. Frames are only grabbed while the
// host is streaming. Autofocus is not driven (the OV5640 needs an AF firmware upload esp32-camera does not do):
// the lens sits at its rest position until that is added and measured.
#include "app.h"
#include "board.h"
#include "esp_camera.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "tusb.h"

static const char *TAG = "camera";
static SemaphoreHandle_t s_done;

void tud_video_frame_xfer_complete_cb(uint_fast8_t ctl_idx, uint_fast8_t stm_idx)
{
    (void)ctl_idx;
    (void)stm_idx;
    xSemaphoreGive(s_done);
}

int tud_video_commit_cb(uint_fast8_t ctl_idx, uint_fast8_t stm_idx, video_probe_and_commit_control_t const *parameters)
{
    (void)ctl_idx;
    (void)stm_idx;
    (void)parameters;
    return VIDEO_ERROR_NONE;
}

static void camera_task(void *arg)
{
    (void)arg;
    for (;;) {
        if (!tud_video_n_streaming(0, 0)) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        xSemaphoreTake(s_done, 0);
        if (tud_video_n_frame_xfer(0, 0, fb->buf, fb->len)) {
            // the buffer must stay valid until TinyUSB is done with it
            if (!xSemaphoreTake(s_done, pdMS_TO_TICKS(2000))) {
                ESP_LOGW(TAG, "frame transfer stalled");
            }
        }
        esp_camera_fb_return(fb);
    }
}

void camera_start(void)
{
    camera_config_t c = {
        .pin_pwdn = CAM_PIN_PWDN,
        .pin_reset = CAM_PIN_RESET,
        .pin_xclk = CAM_PIN_XCLK,
        .pin_sccb_sda = CAM_PIN_SIOD,
        .pin_sccb_scl = CAM_PIN_SIOC,
        .pin_d7 = CAM_PIN_D7,
        .pin_d6 = CAM_PIN_D6,
        .pin_d5 = CAM_PIN_D5,
        .pin_d4 = CAM_PIN_D4,
        .pin_d3 = CAM_PIN_D3,
        .pin_d2 = CAM_PIN_D2,
        .pin_d1 = CAM_PIN_D1,
        .pin_d0 = CAM_PIN_D0,
        .pin_vsync = CAM_PIN_VSYNC,
        .pin_href = CAM_PIN_HREF,
        .pin_pclk = CAM_PIN_PCLK,
        .xclk_freq_hz = 20000000,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_JPEG,
        .frame_size = FRAMESIZE_VGA,  // matches the UVC descriptor (usb_desc.h VIDEO_WIDTH x VIDEO_HEIGHT)
        .jpeg_quality = 14,
        .fb_count = 2,
        .fb_location = CAMERA_FB_IN_PSRAM,
        .grab_mode = CAMERA_GRAB_LATEST,
        .sccb_i2c_port = 1,  // I2C0 is the ToF/IMU bus
    };
    s_done = xSemaphoreCreateBinary();
    esp_err_t err = esp_camera_init(&c);
    status_set(FLAG_CAM, err == ESP_OK);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "camera init failed: %s (video will stream nothing)", esp_err_to_name(err));
        return;
    }
    xTaskCreatePinnedToCore(camera_task, "camera", 4096, NULL, 4, NULL, 1);
}
