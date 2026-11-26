// LSM6DSO 6-axis IMU. Accel +-4 g and gyro +-500 dps at 208 Hz into the chip's FIFO; each ToF frame drains it into
// a mean specific force (g) and a summed rotation (rad), in chip axes. The box maps chip axes to head axes
// (glasses.py IMU_AXES, checked with `python -m cortex_core.safety.glasses --imu`).
#include <math.h>

#include "app.h"
#include "board.h"
#include "esp_log.h"

#define REG_FIFO_CTRL3 0x09
#define REG_FIFO_CTRL4 0x0A
#define REG_WHO_AM_I 0x0F
#define REG_CTRL1_XL 0x10
#define REG_CTRL2_G 0x11
#define REG_CTRL3_C 0x12
#define REG_FIFO_STATUS1 0x3A
#define REG_FIFO_TAG 0x78
#define WHO_AM_I_LSM6DSO 0x6C
#define TAG_GYRO 0x01
#define TAG_ACCEL 0x02

#define ODR_HZ 208.0f
#define ACCEL_G_PER_LSB 0.122e-3f
#define GYRO_RAD_PER_LSB (17.5e-3f * (float)M_PI / 180.0f)
#define MAX_WORDS 96  // ~2.3 frames' worth; more means we fell behind and the rest is dropped by the chip

static const char *TAG = "imu";
static i2c_master_dev_handle_t s_dev;
static bool s_ok;

static esp_err_t wr(uint8_t reg, uint8_t v)
{
    uint8_t b[2] = {reg, v};
    return i2c_master_transmit(s_dev, b, 2, 50);
}

static esp_err_t rd(uint8_t reg, uint8_t *v, size_t n)
{
    return i2c_master_transmit_receive(s_dev, &reg, 1, v, n, 50);
}

bool imu_init(i2c_master_bus_handle_t bus)
{
    if (!s_dev) {
        i2c_device_config_t d = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address = IMU_I2C_ADDR,
            .scl_speed_hz = IMU_I2C_HZ,
        };
        if (i2c_master_bus_add_device(bus, &d, &s_dev) != ESP_OK) {
            return false;
        }
    }
    uint8_t who = 0;
    s_ok = rd(REG_WHO_AM_I, &who, 1) == ESP_OK && who == WHO_AM_I_LSM6DSO
        && wr(REG_CTRL3_C, 0x01) == ESP_OK;  // software reset
    if (s_ok) {
        vTaskDelay(pdMS_TO_TICKS(10));
        s_ok = wr(REG_CTRL3_C, 0x44) == ESP_OK      // BDU, register auto-increment
            && wr(REG_CTRL1_XL, 0x58) == ESP_OK     // 208 Hz, +-4 g
            && wr(REG_CTRL2_G, 0x54) == ESP_OK      // 208 Hz, 500 dps
            && wr(REG_FIFO_CTRL3, 0x55) == ESP_OK   // batch both at 208 Hz
            && wr(REG_FIFO_CTRL4, 0x06) == ESP_OK;  // continuous mode
    }
    ESP_LOGI(TAG, "LSM6DSO %s (WHO_AM_I 0x%02x)", s_ok ? "ready" : "MISSING", who);
    status_set(FLAG_IMU, s_ok);
    return s_ok;
}

void imu_drain(float accel[3], float dtheta[3], uint16_t *n)
{
    float a[3] = {0}, g[3] = {0};
    int na = 0, ng = 0;
    uint8_t st[2];
    if (s_ok && rd(REG_FIFO_STATUS1, st, 2) == ESP_OK) {
        int words = st[0] | ((st[1] & 0x03) << 8);
        if (words > MAX_WORDS) {
            words = MAX_WORDS;
        }
        for (int w = 0; w < words; w++) {
            uint8_t b[7];
            if (rd(REG_FIFO_TAG, b, 7) != ESP_OK) {
                atomic_fetch_add(&g_status.imu_errors, 1);
                break;
            }
            float v[3];
            for (int i = 0; i < 3; i++) {
                v[i] = (float)(int16_t)(b[1 + 2 * i] | (b[2 + 2 * i] << 8));
            }
            switch (b[0] >> 3) {
            case TAG_ACCEL:
                for (int i = 0; i < 3; i++) a[i] += v[i] * ACCEL_G_PER_LSB;
                na++;
                break;
            case TAG_GYRO:
                for (int i = 0; i < 3; i++) g[i] += v[i] * GYRO_RAD_PER_LSB / ODR_HZ;
                ng++;
                break;
            default:
                break;
            }
        }
    } else if (s_ok) {
        atomic_fetch_add(&g_status.imu_errors, 1);
    }
    for (int i = 0; i < 3; i++) {
        accel[i] = na ? a[i] / (float)na : 0.0f;  // no samples: (0,0,0), which the box's tilt filter ignores
        dtheta[i] = g[i];
    }
    *n = (uint16_t)(na < ng ? na : ng);
}
