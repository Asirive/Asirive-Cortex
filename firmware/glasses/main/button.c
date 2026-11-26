// The listen button: tap or long press goes to the box (the brain decides what it means); the glasses tick the
// motors themselves so the wearer feels the press even if the box is slow.
#include "app.h"
#include "board.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "logic.h"

static void button_task(void *arg)
{
    (void)arg;
    button_t b;
    button_init(&b);
    for (;;) {
        uint8_t ev = button_step(&b, gpio_get_level(BUTTON_PIN) == 0, now_ms());
        if (ev) {
            haptic_play(&PATTERN_TICK);
            link_send_button(ev, now_us());
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

void button_start(void)
{
    gpio_config_t c = {
        .pin_bit_mask = 1ULL << BUTTON_PIN,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&c));
    xTaskCreatePinnedToCore(button_task, "button", 3072, NULL, 6, NULL, 0);
}
