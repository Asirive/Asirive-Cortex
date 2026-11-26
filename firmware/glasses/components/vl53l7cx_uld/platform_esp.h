#pragma once
#include "driver/i2c_master.h"
// The ULD's platform struct has no room for a driver handle; the one sensor on the glasses uses this one.
void vl53l7cx_platform_bind(i2c_master_dev_handle_t dev);
