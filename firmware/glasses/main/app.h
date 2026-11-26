// Shared between the glasses' tasks. Each task owns its hardware; they only meet here.
#pragma once
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "proto.h"

#define FW_VERSION 1
#define FW_BUILD "a1"  // 15 chars max; HELLO carries it

typedef struct {
    atomic_uint_least16_t flags;  // FLAG_* from proto.h
    atomic_uint_least16_t tof_errors, imu_errors, usb_drops;
} app_status_t;
extern app_status_t g_status;

static inline void status_set(uint16_t flag, bool on)
{
    if (on) {
        atomic_fetch_or(&g_status.flags, flag);
    } else {
        atomic_fetch_and(&g_status.flags, (uint16_t)~flag);
    }
}

uint32_t now_ms(void);
uint32_t now_us(void);

// link.c: the CDC safety channel. link_send never blocks; a full TX buffer drops the frame (counted).
void link_start(void);
void link_send_tof(const tof_msg_t *m);
void link_send_button(uint8_t kind, uint32_t t_us);

// haptic.c
void haptic_start(void);
void haptic_play(const haptic_msg_t *m);  // from any task; never blocks

// button.c
void button_start(void);

// imu.c (called from the ToF task only, which owns the I2C bus traffic)
bool imu_init(i2c_master_bus_handle_t bus);
void imu_drain(float accel[3], float dtheta[3], uint16_t *n);

// tof.c
void tof_start(i2c_master_bus_handle_t bus);

// camera.c, audio.c (USB video / audio)
void camera_start(void);
void audio_start(void);
