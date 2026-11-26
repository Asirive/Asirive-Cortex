// Host harness: prints the composite configuration descriptor as hex so tests can parse it (TinyUSB headers only;
// built with CFG_TUSB_MCU=OPT_MCU_NONE, CFG_TUSB_OS=OPT_OS_NONE by core/tests/test_glasses_firmware.py).
#include <stdio.h>

#include "tusb.h"

int main(void)
{
    const uint8_t *d = tud_descriptor_configuration_cb(0);
    unsigned n = (unsigned)(d[2] | (d[3] << 8));
    for (unsigned i = 0; i < n; i++) {
        printf("%02x", d[i]);
    }
    printf("\n");
    const uint16_t *s = tud_descriptor_string_cb(STR_CDC, 0x0409);
    for (unsigned i = 1; i < (s[0] & 0xFF) / 2u; i++) {
        putchar((char)s[i]);
    }
    printf("\n");
    return 0;
}
