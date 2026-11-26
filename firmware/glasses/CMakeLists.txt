cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(asirive_glasses)

# TinyUSB (espressif/tinyusb, used directly, not through esp_tinyusb) compiles against our tusb_config.h.
idf_component_get_property(tusb_lib espressif__tinyusb COMPONENT_LIB)
target_include_directories(${tusb_lib} PRIVATE "${CMAKE_CURRENT_LIST_DIR}/main")
