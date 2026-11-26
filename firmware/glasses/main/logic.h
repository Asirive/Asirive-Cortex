// The glasses' own decisions, kept free of ESP-IDF so they are tested on the host (test/logic_host.c):
// the haptic pattern player, the host-beat fail-safe and the button debouncer. Times are milliseconds.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "proto.h"

// ---- haptic player: a new pattern of equal or higher priority replaces the one playing; lower is dropped
typedef struct {
    haptic_msg_t msg;
    bool playing;
    uint8_t step;
    uint32_t step_end;
} player_t;

void player_init(player_t *p);
bool player_offer(player_t *p, const haptic_msg_t *m, uint32_t now);
// Advance to now; writes the motor duties to play and returns ms until the next change (UINT32_MAX when idle).
uint32_t player_poll(player_t *p, uint32_t now, uint8_t *left, uint8_t *right);

extern const haptic_msg_t PATTERN_TICK, PATTERN_DEGRADED;  // same as glasses.py pattern("tick"/"degraded")

// ---- fail-safe: once the box has sent a beat, silence for FAILSAFE_MS means the box's safety loop is gone
#define FAILSAFE_MS 1500
#define FAILSAFE_REPEAT_MS 5000
typedef struct {
    bool armed, active;
    uint32_t last_beat, last_alarm;
} failsafe_t;

void failsafe_init(failsafe_t *f);
void failsafe_beat(failsafe_t *f, uint32_t now);
bool failsafe_poll(failsafe_t *f, uint32_t now);  // true = vibrate "degraded" now

// ---- button: active-low level sampled every few ms; 30 ms debounce; held 600 ms = long press (sent once)
#define BUTTON_DEBOUNCE_MS 30
#define BUTTON_LONG_MS 600
typedef struct {
    bool raw, stable, long_sent;
    uint32_t raw_since, down_at;
} button_t;

void button_init(button_t *b);
uint8_t button_step(button_t *b, bool pressed, uint32_t now);  // 0, BUTTON_TAP or BUTTON_LONG
