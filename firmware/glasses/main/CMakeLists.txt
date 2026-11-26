idf_component_register(
    SRCS "main.c" "usb_desc.c" "link.c" "haptic.c" "button.c" "imu.c" "tof.c" "camera.c" "audio.c"
         "proto.c" "logic.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_i2c esp_driver_i2s esp_driver_ledc esp_driver_gpio esp_timer esp_hw_support usb app_update
             vl53l7cx_uld)
