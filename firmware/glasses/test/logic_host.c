// Host harness for main/logic.c. Reads commands on stdin, one per line, and prints one result line each:
//   offer T PRIO L,R,MS [L,R,MS ...]  -> accept | reject
//   out T                              -> L R WAIT   (WAIT = ms to the next change, -1 idle)
//   beat T                             -> ok
//   fs T                               -> alarm | quiet
//   btn T 0|1                          -> 0 | 1 (tap) | 2 (long)
//   pat 0 tick|degraded                -> PRIO L,R,MS ...  (the patterns the glasses play on their own)
#include <stdio.h>
#include <string.h>

#include "logic.h"

int main(void)
{
    player_t p;
    failsafe_t f;
    button_t b;
    player_init(&p);
    failsafe_init(&f);
    button_init(&b);
    char line[512];
    while (fgets(line, sizeof line, stdin)) {
        char cmd[8];
        unsigned t;
        int off;
        if (sscanf(line, "%7s %u%n", cmd, &t, &off) < 2) {
            continue;
        }
        const char *rest = line + off;
        if (!strcmp(cmd, "offer")) {
            haptic_msg_t m = {0};
            unsigned prio, l, r, ms;
            int k;
            sscanf(rest, " %u%n", &prio, &k);
            rest += k;
            m.prio = (uint8_t)prio;
            while (m.n < HAPTIC_MAX_STEPS && sscanf(rest, " %u,%u,%u%n", &l, &r, &ms, &k) == 3) {
                m.steps[m.n++] = (haptic_step_t){(uint8_t)l, (uint8_t)r, (uint16_t)ms};
                rest += k;
            }
            puts(player_offer(&p, &m, t) ? "accept" : "reject");
        } else if (!strcmp(cmd, "out")) {
            uint8_t l, r;
            uint32_t w = player_poll(&p, t, &l, &r);
            printf("%u %u %ld\n", l, r, w == UINT32_MAX ? -1L : (long)w);
        } else if (!strcmp(cmd, "beat")) {
            failsafe_beat(&f, t);
            puts("ok");
        } else if (!strcmp(cmd, "fs")) {
            puts(failsafe_poll(&f, t) ? "alarm" : "quiet");
        } else if (!strcmp(cmd, "pat")) {
            const haptic_msg_t *m = strstr(rest, "degraded") ? &PATTERN_DEGRADED : &PATTERN_TICK;
            printf("%u", m->prio);
            for (int i = 0; i < m->n; i++) {
                printf(" %u,%u,%u", m->steps[i].left, m->steps[i].right, m->steps[i].ms);
            }
            printf("\n");
        } else if (!strcmp(cmd, "btn")) {
            int lvl = 0;
            sscanf(rest, " %d", &lvl);
            printf("%u\n", button_step(&b, lvl != 0, t));
        }
        fflush(stdout);
    }
    return 0;
}
