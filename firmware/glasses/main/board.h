// Asirive glasses (ESP32-S3-N16R8 on the right temple arm) pin map. Proposed 2026-11, not yet wired: the README
// (firmware/glasses/README.md) has the same table plus wiring notes. Avoid: 19/20 USB, 26-32 flash, 33-37 octal PSRAM,
// 43/44 UART0 console. Spare: 0 (strap), 3 (strap), 45 (strap), 46 (strap).
#pragma once

// OV5640 over DVP (ESP32-S3-EYE layout). PWDN and RESET not wired: the module's own pull-ups hold it on.
#define CAM_PIN_PWDN   -1
#define CAM_PIN_RESET  -1
#define CAM_PIN_XCLK   15
#define CAM_PIN_SIOD   4
#define CAM_PIN_SIOC   5
#define CAM_PIN_D7     16
#define CAM_PIN_D6     17
#define CAM_PIN_D5     18
#define CAM_PIN_D4     12
#define CAM_PIN_D3     10
#define CAM_PIN_D2     8
#define CAM_PIN_D1     9
#define CAM_PIN_D0     11
#define CAM_PIN_VSYNC  6
#define CAM_PIN_HREF   7
#define CAM_PIN_PCLK   13

// VL53L7CX (nose bridge, 78 mm flex) and LSM6DSO share I2C0. ToF LPn tied high (always enabled, address 0x29).
#define I2C_PIN_SDA    1
#define I2C_PIN_SCL    2
#define TOF_PIN_INT    21     // open drain, active low on data ready; 10k pull-up on the board
#define TOF_I2C_HZ     1000000
#define IMU_I2C_HZ     400000
#define IMU_I2C_ADDR   0x6A   // LSM6DSO SDO/SA0 to GND

// 2x MP34DT01 PDM mics: mouth (L/R pin to GND = left slot), ambient (L/R to VDD = right slot), shared clock/data.
#define PDM_PIN_CLK    38
#define PDM_PIN_DATA   39

// MAX98357A: SD_MODE tied high through 1M (left channel) -> we send the same sample in both slots anyway.
#define AMP_PIN_BCLK   40
#define AMP_PIN_WS     41
#define AMP_PIN_DOUT   42

// Coin ERM motors, each through a logic-level N-MOSFET (e.g. AO3400) with a flyback diode (1N4148/BAT54) across it.
#define MOTOR_PIN_L    47
#define MOTOR_PIN_R    48

// Listen button to GND, internal pull-up.
#define BUTTON_PIN     14
