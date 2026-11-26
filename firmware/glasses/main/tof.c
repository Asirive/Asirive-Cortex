// VL53L7CX 8x8 ToF on the nose bridge, 15 Hz continuous, closest target first. Each frame goes to the box with
// the IMU drained over the same interval. Sensor or bus failure: retried every second, the box sees FLAG_TOF clear
// and no frames, and its safety service reports "degraded" on its own.
#include <string.h>

#include "app.h"
#include "board.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "platform_esp.h"
#include "vl53l7cx_api.h"

#define TOF_HZ 15

static const char *TAG = "tof";
static TaskHandle_t s_task;
static i2c_master_bus_handle_t s_bus;

static void IRAM_ATTR on_int(void *arg)
{
    (void)arg;
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(s_task, &woken);
    portYIELD_FROM_ISR(woken);
}

static bool tof_setup(VL53L7CX_Configuration *dev)
{
    uint8_t alive = 0;
    if (vl53l7cx_is_alive(dev, &alive) || !alive) {
        return false;
    }
    return vl53l7cx_init(dev) == VL53L7CX_STATUS_OK
        && vl53l7cx_set_resolution(dev, VL53L7CX_RESOLUTION_8X8) == VL53L7CX_STATUS_OK
        && vl53l7cx_set_ranging_frequency_hz(dev, TOF_HZ) == VL53L7CX_STATUS_OK
        && vl53l7cx_set_target_order(dev, VL53L7CX_TARGET_ORDER_CLOSEST) == VL53L7CX_STATUS_OK
        && vl53l7cx_set_ranging_mode(dev, VL53L7CX_RANGING_MODE_CONTINUOUS) == VL53L7CX_STATUS_OK
        && vl53l7cx_start_ranging(dev) == VL53L7CX_STATUS_OK;
}

static void tof_task(void *arg)
{
    (void)arg;
    static VL53L7CX_Configuration dev;  // ~1.5 kB plus the ranging buffers: not on the stack
    static VL53L7CX_ResultsData res;
    i2c_master_dev_handle_t h;
    i2c_device_config_t d = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = VL53L7CX_DEFAULT_I2C_ADDRESS >> 1,
        .scl_speed_hz = TOF_I2C_HZ,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(s_bus, &d, &h));
    vl53l7cx_platform_bind(h);
    memset(&dev, 0, sizeof dev);
    dev.platform.address = VL53L7CX_DEFAULT_I2C_ADDRESS;

    for (;;) {
        status_set(FLAG_TOF, false);
        if (!imu_init(s_bus)) {
            atomic_fetch_add(&g_status.imu_errors, 1);
        }
        if (!tof_setup(&dev)) {
            ESP_LOGE(TAG, "VL53L7CX not answering; retry in 1 s");
            atomic_fetch_add(&g_status.tof_errors, 1);
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        ESP_LOGI(TAG, "ranging 8x8 at %d Hz", TOF_HZ);
        status_set(FLAG_TOF, true);
        float a[3], g[3];
        uint16_t n;
        imu_drain(a, g, &n);  // start the first frame's IMU window now
        int misses = 0;
        while (misses < 5) {
            ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(150));  // INT, or poll if the line is not wired / missed
            uint8_t ready = 0;
            if (vl53l7cx_check_data_ready(&dev, &ready)) {
                misses++;
                atomic_fetch_add(&g_status.tof_errors, 1);
                continue;
            }
            if (!ready) {
                continue;
            }
            uint32_t t = now_us();
            if (vl53l7cx_get_ranging_data(&dev, &res)) {
                misses++;
                atomic_fetch_add(&g_status.tof_errors, 1);
                continue;
            }
            misses = 0;
            tof_msg_t m = {.t_us = t};
            imu_drain(m.accel, m.dtheta, &m.imu_n);
            for (int i = 0; i < ZONES; i++) {
                int16_t mm = res.distance_mm[i];
                m.mm[i] = (res.nb_target_detected[i] && mm > 0) ? (uint16_t)mm : 0;
                m.status[i] = res.target_status[i];
            }
            link_send_tof(&m);
        }
        ESP_LOGE(TAG, "sensor stopped answering; reinitialising");
        vl53l7cx_stop_ranging(&dev);
    }
}

void tof_start(i2c_master_bus_handle_t bus)
{
    s_bus = bus;
    gpio_config_t c = {
        .pin_bit_mask = 1ULL << TOF_PIN_INT,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .intr_type = GPIO_INTR_NEGEDGE,
    };
    ESP_ERROR_CHECK(gpio_config(&c));
    xTaskCreatePinnedToCore(tof_task, "tof", 6144, NULL, 10, &s_task, 1);
    ESP_ERROR_CHECK(gpio_isr_handler_add(TOF_PIN_INT, on_int, NULL));
}
