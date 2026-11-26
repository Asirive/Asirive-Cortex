// TinyUSB configuration: composite UVC (MJPEG, bulk) + UAC2 (stereo mic in, mono speaker out) + CDC (safety channel).
// ESP32-S3 is USB full speed only (12 Mbit/s) with 6 endpoints besides EP0, at most 5 IN including EP0's.
// Used: IN 0x81 video, 0x82 mic, 0x83 CDC notify, 0x84 CDC data; OUT 0x02 speaker, 0x04 CDC data.
#pragma once

#ifndef CFG_TUSB_MCU
#define CFG_TUSB_MCU OPT_MCU_ESP32S3
#endif
#ifndef CFG_TUSB_OS
#define CFG_TUSB_OS OPT_OS_FREERTOS
#endif
#define CFG_TUSB_RHPORT0_MODE OPT_MODE_DEVICE
#define CFG_TUD_ENABLED 1
#define CFG_TUD_MAX_SPEED OPT_MODE_FULL_SPEED
#define CFG_TUSB_DEBUG 0
#define CFG_TUD_ENDPOINT0_SIZE 64
#define CFG_TUSB_MEM_ALIGN __attribute__((aligned(4)))

#define CFG_TUD_CDC 1
#define CFG_TUD_AUDIO 1
#define CFG_TUD_VIDEO 1
#define CFG_TUD_VIDEO_STREAMING 1
#define CFG_TUD_MSC 0
#define CFG_TUD_HID 0
#define CFG_TUD_MIDI 0
#define CFG_TUD_VENDOR 0

// ---- CDC: ToF frames are ~240 B at 15 Hz; the TX FIFO holds several so a slow host read never blocks the sensor
#define CFG_TUD_CDC_RX_BUFSIZE 512
#define CFG_TUD_CDC_TX_BUFSIZE 2048
#define CFG_TUD_CDC_EP_BUFSIZE 64

// ---- Video: bulk on full speed
#define CFG_TUD_VIDEO_STREAMING_BULK 1
#define CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE 64

// ---- Audio: 16 kHz, 16 bit; mic 2 channels (mouth, ambient), speaker 1 channel, one format each
#define AUDIO_SAMPLE_RATE 16000
#define CFG_TUD_AUDIO_FUNC_1_DESC_LEN TUD_GLASSES_AUDIO_DESC_LEN
#define CFG_TUD_AUDIO_FUNC_1_N_AS_INT 2
#define CFG_TUD_AUDIO_FUNC_1_CTRL_BUF_SZ 64
#define CFG_TUD_AUDIO_FUNC_1_MAX_SAMPLE_RATE AUDIO_SAMPLE_RATE
#define CFG_TUD_AUDIO_FUNC_1_N_CHANNELS_TX 2
#define CFG_TUD_AUDIO_FUNC_1_N_CHANNELS_RX 1
#define CFG_TUD_AUDIO_FUNC_1_N_BYTES_PER_SAMPLE_TX 2
#define CFG_TUD_AUDIO_FUNC_1_N_BYTES_PER_SAMPLE_RX 2

#define CFG_TUD_AUDIO_ENABLE_EP_IN 1
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX \
    TUD_AUDIO_EP_SIZE(0, AUDIO_SAMPLE_RATE, CFG_TUD_AUDIO_FUNC_1_N_BYTES_PER_SAMPLE_TX, CFG_TUD_AUDIO_FUNC_1_N_CHANNELS_TX)
#define CFG_TUD_AUDIO_FUNC_1_EP_IN_SW_BUF_SZ (16 * CFG_TUD_AUDIO_FUNC_1_EP_IN_SZ_MAX)
#define CFG_TUD_AUDIO_ENABLE_EP_OUT 1
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX \
    TUD_AUDIO_EP_SIZE(0, AUDIO_SAMPLE_RATE, CFG_TUD_AUDIO_FUNC_1_N_BYTES_PER_SAMPLE_RX, CFG_TUD_AUDIO_FUNC_1_N_CHANNELS_RX)
#define CFG_TUD_AUDIO_FUNC_1_EP_OUT_SW_BUF_SZ (32 * CFG_TUD_AUDIO_FUNC_1_EP_OUT_SZ_MAX)
#define CFG_TUD_AUDIO_ENABLE_FEEDBACK_EP 0   // adaptive speaker: no feedback endpoint (no IN endpoint to spare)

#include "usb_desc.h"
