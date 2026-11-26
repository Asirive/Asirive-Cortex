// Device, configuration and string descriptors for the composite device (see usb_desc.h).
#include <string.h>

#include "tusb.h"

static const tusb_desc_device_t dev_desc = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = TUSB_CLASS_MISC,  // IAD composite
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = USB_VID,
    .idProduct = USB_PID,
    .bcdDevice = 0x0100,
    .iManufacturer = STR_MANUF,
    .iProduct = STR_PRODUCT,
    .iSerialNumber = STR_SERIAL,
    .bNumConfigurations = 1,
};

const uint8_t usb_config_desc[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, USB_CONFIG_TOTAL_LEN, 0x00, 500),
    TUD_GLASSES_VIDEO_DESCRIPTOR(STR_VIDEO, EPNUM_VIDEO_IN, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
                                 CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE),
    TUD_GLASSES_AUDIO_DESCRIPTOR(STR_AUDIO, STR_MIC, STR_SPK, EPNUM_MIC_IN, EPNUM_SPK_OUT),
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, STR_CDC, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, CFG_TUD_CDC_EP_BUFSIZE),
};
_Static_assert(sizeof usb_config_desc == USB_CONFIG_TOTAL_LEN, "config descriptor length");

static char serial[17] = "0000000000000000";
static const char *const strings[STR_COUNT] = {
    [STR_MANUF] = "Asirive",
    [STR_PRODUCT] = "Asirive Glasses",
    [STR_SERIAL] = serial,
    [STR_VIDEO] = "Asirive Glasses Camera",
    [STR_AUDIO] = "Asirive Glasses Audio",
    [STR_MIC] = "Asirive Glasses Mic",
    [STR_SPK] = "Asirive Glasses Speaker",
    [STR_CDC] = "Asirive Glasses Safety",  // the box's udev rule matches this interface (deploy/udev)
};

void usb_set_serial(const char *s)
{
    strncpy(serial, s, sizeof serial - 1);
}

const uint8_t *tud_descriptor_device_cb(void)
{
    return (const uint8_t *)&dev_desc;
}

const uint8_t *tud_descriptor_configuration_cb(uint8_t index)
{
    (void)index;
    return usb_config_desc;
}

const uint16_t *tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
    (void)langid;
    static uint16_t buf[32];
    size_t n;
    if (index == STR_LANG) {
        buf[1] = 0x0409;
        n = 1;
    } else if (index < STR_COUNT && strings[index]) {
        const char *s = strings[index];
        n = strlen(s);
        if (n > 31) {
            n = 31;
        }
        for (size_t i = 0; i < n; i++) {
            buf[1 + i] = (uint8_t)s[i];
        }
    } else {
        return NULL;
    }
    buf[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * n + 2));
    return buf;
}
