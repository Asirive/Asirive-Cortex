# ST's VL53L7CX ULD (fetched by scripts/fetch_uld.sh into st/, not committed) plus our ESP-IDF platform layer.
# Only ST's API file is built: its porting/platform.c is replaced by platform_esp.c.
if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/st/modules/vl53l7cx_api.c")
    message(FATAL_ERROR "VL53L7CX driver missing: run firmware/glasses/scripts/fetch_uld.sh")
endif()
idf_component_register(SRCS "st/modules/vl53l7cx_api.c" "platform_esp.c"
                       INCLUDE_DIRS "st/modules" "st/porting" "."
                       REQUIRES esp_driver_i2c freertos)
# Results we do not use are not read over I2C at all (shorter transfer per frame).
target_compile_definitions(${COMPONENT_LIB} PUBLIC
    VL53L7CX_DISABLE_AMBIENT_PER_SPAD VL53L7CX_DISABLE_NB_SPADS_ENABLED VL53L7CX_DISABLE_SIGNAL_PER_SPAD
    VL53L7CX_DISABLE_RANGE_SIGMA_MM VL53L7CX_DISABLE_REFLECTANCE_PERCENT VL53L7CX_DISABLE_MOTION_INDICATOR)
