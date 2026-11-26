// VL53L7CX ULD platform layer over the ESP-IDF i2c_master driver (16-bit register addresses, big-endian).
// The ULD's init uploads ~84 kB of sensor firmware in chunks of up to 32 kB, so writes go out as two buffers
// (address + data) instead of being copied.
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "platform.h"
#include "platform_esp.h"

#define TIMEOUT_MS 1000

static i2c_master_dev_handle_t s_dev;

void vl53l7cx_platform_bind(i2c_master_dev_handle_t dev)
{
    s_dev = dev;
}

uint8_t VL53L7CX_RdMulti(VL53L7CX_Platform *p, uint16_t reg, uint8_t *values, uint32_t size)
{
    (void)p;
    uint8_t a[2] = {(uint8_t)(reg >> 8), (uint8_t)reg};
    return i2c_master_transmit_receive(s_dev, a, 2, values, size, TIMEOUT_MS) == ESP_OK ? 0 : 1;
}

uint8_t VL53L7CX_WrMulti(VL53L7CX_Platform *p, uint16_t reg, uint8_t *values, uint32_t size)
{
    (void)p;
    uint8_t a[2] = {(uint8_t)(reg >> 8), (uint8_t)reg};
    i2c_master_transmit_multi_buffer_info_t parts[2] = {{.write_buffer = a, .buffer_size = 2},
                                                        {.write_buffer = values, .buffer_size = size}};
    return i2c_master_multi_buffer_transmit(s_dev, parts, 2, TIMEOUT_MS) == ESP_OK ? 0 : 1;
}

uint8_t VL53L7CX_RdByte(VL53L7CX_Platform *p, uint16_t reg, uint8_t *value)
{
    return VL53L7CX_RdMulti(p, reg, value, 1);
}

uint8_t VL53L7CX_WrByte(VL53L7CX_Platform *p, uint16_t reg, uint8_t value)
{
    return VL53L7CX_WrMulti(p, reg, &value, 1);
}

void VL53L7CX_SwapBuffer(uint8_t *buffer, uint16_t size)
{
    for (uint32_t i = 0; i + 3 < size; i += 4) {
        uint8_t t0 = buffer[i], t1 = buffer[i + 1];
        buffer[i] = buffer[i + 3];
        buffer[i + 1] = buffer[i + 2];
        buffer[i + 2] = t1;
        buffer[i + 3] = t0;
    }
}

uint8_t VL53L7CX_WaitMs(VL53L7CX_Platform *p, uint32_t ms)
{
    (void)p;
    vTaskDelay(pdMS_TO_TICKS(ms) ? pdMS_TO_TICKS(ms) : 1);
    return 0;
}
