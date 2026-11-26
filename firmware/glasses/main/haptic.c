// Two coin ERM motors (left, right temple) on LEDC PWM through MOSFETs. Patterns come from the box (or locally:
// button tick, fail-safe); logic.c decides which one plays.
#include "app.h"
#include "board.h"
#include "driver/ledc.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "logic.h"

// LEDC timer 0 / channel 0 belong to the camera's XCLK.
#define MOTOR_TIMER LEDC_TIMER_1
#define MOTOR_CH_L LEDC_CHANNEL_2
#define MOTOR_CH_R LEDC_CHANNEL_3

static QueueHandle_t s_q;

void haptic_play(const haptic_msg_t *m)
{
    if (s_q) {
        xQueueSend(s_q, m, 0);
    }
}

static void set_duty(ledc_channel_t ch, uint8_t duty)
{
    ledc_set_duty(LEDC_LOW_SPEED_MODE, ch, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, ch);
}

static void haptic_task(void *arg)
{
    (void)arg;
    player_t p;
    player_init(&p);
    uint8_t cur_l = 0, cur_r = 0;
    for (;;) {
        uint8_t l, r;
        uint32_t wait = player_poll(&p, now_ms(), &l, &r);
        if (l != cur_l) {
            set_duty(MOTOR_CH_L, cur_l = l);
        }
        if (r != cur_r) {
            set_duty(MOTOR_CH_R, cur_r = r);
        }
        haptic_msg_t m;
        if (xQueueReceive(s_q, &m, wait == UINT32_MAX ? portMAX_DELAY : pdMS_TO_TICKS(wait))) {
            player_offer(&p, &m, now_ms());
        }
    }
}

void haptic_start(void)
{
    ledc_timer_config_t t = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_8_BIT,
        .timer_num = MOTOR_TIMER,
        .freq_hz = 20000,  // above hearing
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&t));
    const int pins[2] = {MOTOR_PIN_L, MOTOR_PIN_R};
    const ledc_channel_t chs[2] = {MOTOR_CH_L, MOTOR_CH_R};
    for (int i = 0; i < 2; i++) {
        ledc_channel_config_t c = {
            .gpio_num = pins[i],
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .channel = chs[i],
            .timer_sel = MOTOR_TIMER,
            .duty = 0,
        };
        ESP_ERROR_CHECK(ledc_channel_config(&c));
    }
    s_q = xQueueCreate(4, sizeof(haptic_msg_t));
    xTaskCreatePinnedToCore(haptic_task, "haptic", 3072, NULL, 9, NULL, 0);
}
