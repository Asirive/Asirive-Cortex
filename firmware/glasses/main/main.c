// Asirive glasses firmware (ESP32-S3). A bridge, no AI: it streams the camera, mics and ToF/IMU to the box over
// one USB cable and plays what the box sends (speaker, haptics). The only decision it makes alone is the
// fail-safe: if the box's safety loop stops beating, vibrate "degraded" (link.c).
#include <stdio.h>

#include "app.h"
#include "board.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_ota_ops.h"
#include "esp_private/usb_phy.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"

app_status_t g_status;

uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

uint32_t now_us(void)
{
    return (uint32_t)esp_timer_get_time();
}

static void usb_task(void *arg)
{
    (void)arg;
    for (;;) {
        tud_task();  // blocks until there is USB work
    }
}

static void usb_start(void)
{
    uint8_t mac[6];
    char serial[17];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(serial, sizeof serial, "%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    usb_set_serial(serial);

    static usb_phy_handle_t phy;
    usb_phy_config_t pc = {
        .controller = USB_PHY_CTRL_OTG,
        .target = USB_PHY_TARGET_INT,
        .otg_mode = USB_OTG_MODE_DEVICE,
    };
    ESP_ERROR_CHECK(usb_new_phy(&pc, &phy));
    tusb_rhport_init_t init = {.role = TUSB_ROLE_DEVICE, .speed = TUSB_SPEED_FULL};
    if (!tusb_init(0, &init)) {
        ESP_LOGE("main", "TinyUSB init failed");
        abort();
    }
    xTaskCreatePinnedToCore(usb_task, "usb", 4096, NULL, 12, NULL, 0);
}

void app_main(void)
{
    ESP_LOGI("main", "Asirive glasses fw %d (%s)", FW_VERSION, FW_BUILD);
    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    haptic_start();  // first: the fail-safe needs the motors whatever else fails
    usb_start();
    link_start();
    button_start();

    i2c_master_bus_config_t bc = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = I2C_PIN_SDA,
        .scl_io_num = I2C_PIN_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = false,  // 2.2k external pull-ups for 1 MHz
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bc, &bus));
    tof_start(bus);

    camera_start();
    audio_start();

    // Reaching here means the image boots and the fail-safe path (motors, USB) is up: keep it. A new image that
    // crashes before this point is rolled back to the previous slot by the bootloader.
    esp_ota_mark_app_valid_cancel_rollback();
}
