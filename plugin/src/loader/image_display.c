#include <pspiofilemgr.h>
#include <pspkernel.h>
#include <stdint.h>
#include "image_display.h"

#define MAX_IMAGE_WIDTH 480
#define MAX_IMAGE_HEIGHT 272

// Single scanline scratch buffer (1,920 bytes) keeps kernel-partition footprint tiny.
static uint32_t row_buffer[MAX_IMAGE_WIDTH] __attribute__((aligned(16)));

static inline uint32_t blend_over_black(uint32_t pixel) {
    uint32_t a = (pixel >> 24) & 0xFFu;
    if (a == 0xFFu) {
        return pixel;
    }
    if (a == 0u) {
        return 0xFF000000u;
    }
    uint32_t r = ((pixel & 0xFFu) * a + 127u) / 255u;
    uint32_t g = (((pixel >> 8) & 0xFFu) * a + 127u) / 255u;
    uint32_t b = (((pixel >> 16) & 0xFFu) * a + 127u) / 255u;
    return 0xFF000000u | r | (g << 8) | (b << 16);
}

int loadImageToFramebuffer(
    uint32_t *framebuffer,
    int buffer_stride,
    const char *filename,
    int width,
    int height) {
    if (!framebuffer || !filename ||
        width <= 0 || width > MAX_IMAGE_WIDTH ||
        height <= 0 || height > MAX_IMAGE_HEIGHT ||
        buffer_stride < width) {
        return 0;
    }

    SceUID fd = sceIoOpen(filename, PSP_O_RDONLY, 0777);
    if (fd < 0) {
        return 0;
    }

    int row_bytes = width * (int)sizeof(uint32_t);
    for (int y = 0; y < height; ++y) {
        int bytes_read = sceIoRead(fd, row_buffer, row_bytes);
        if (bytes_read != row_bytes) {
            sceIoClose(fd);
            return 0;
        }
        uint32_t *dst_row = framebuffer + y * buffer_stride;
        for (int x = 0; x < width; ++x) {
            dst_row[x] = blend_over_black(row_buffer[x]);
        }
    }

    sceIoClose(fd);
    return 1;
}
