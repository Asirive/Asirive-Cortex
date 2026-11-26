#include "logic.h"

#include <string.h>

#define ON 220
const haptic_msg_t PATTERN_TICK = {.prio = 0, .n = 1, .steps = {{ON, ON, 30}}};
const haptic_msg_t PATTERN_DEGRADED = {
    .prio = 2, .n = 5, .steps = {{ON, ON, 400}, {0, 0, 150}, {ON, ON, 120}, {0, 0, 150}, {ON, ON, 400}}};

void player_init(player_t *p)
{
    memset(p, 0, sizeof *p);
}

bool player_offer(player_t *p, const haptic_msg_t *m, uint32_t now)
{
    if (m->n == 0 || m->n > HAPTIC_MAX_STEPS || (p->playing && m->prio < p->msg.prio)) {
        return false;
    }
    p->msg = *m;
    p->playing = true;
    p->step = 0;
    p->step_end = now + m->steps[0].ms;
    return true;
}

uint32_t player_poll(player_t *p, uint32_t now, uint8_t *left, uint8_t *right)
{
    while (p->playing && (int32_t)(now - p->step_end) >= 0) {
        if (++p->step >= p->msg.n) {
            p->playing = false;
            break;
        }
        p->step_end += p->msg.steps[p->step].ms;
    }
    if (!p->playing) {
        *left = *right = 0;
        return UINT32_MAX;
    }
    *left = p->msg.steps[p->step].left;
    *right = p->msg.steps[p->step].right;
    return p->step_end - now;
}

void failsafe_init(failsafe_t *f)
{
    memset(f, 0, sizeof *f);
}

void failsafe_beat(failsafe_t *f, uint32_t now)
{
    f->armed = true;
    f->active = false;
    f->last_beat = now;
}

bool failsafe_poll(failsafe_t *f, uint32_t now)
{
    if (!f->armed || now - f->last_beat < FAILSAFE_MS) {
        return false;
    }
    if (!f->active || now - f->last_alarm >= FAILSAFE_REPEAT_MS) {
        f->active = true;
        f->last_alarm = now;
        return true;
    }
    return false;
}

void button_init(button_t *b)
{
    memset(b, 0, sizeof *b);
}

uint8_t button_step(button_t *b, bool pressed, uint32_t now)
{
    if (pressed != b->raw) {
        b->raw = pressed;
        b->raw_since = now;
    }
    if (b->raw != b->stable && now - b->raw_since >= BUTTON_DEBOUNCE_MS) {
        b->stable = b->raw;
        if (b->stable) {
            b->down_at = b->raw_since;
            b->long_sent = false;
        } else if (!b->long_sent) {
            return BUTTON_TAP;
        }
    }
    if (b->stable && !b->long_sent && now - b->down_at >= BUTTON_LONG_MS) {
        b->long_sent = true;
        return BUTTON_LONG;
    }
    return 0;
}
