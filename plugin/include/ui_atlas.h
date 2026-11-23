#ifndef __UI_ATLAS_H__
#define __UI_ATLAS_H__

#include <stdint.h>

// Render UTF-8 text directly into an ABGR8888 framebuffer in VRAM.
void uiPrint(
    uint32_t *framebuffer,
    int buffer_stride,
    int screen_width,
    int screen_height,
    int x,
    int y,
    const char *str,
    uint32_t color);
int uiTextWidth(const char *str);

#endif
