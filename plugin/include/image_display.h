#ifndef __IMAGE_DISPLAY_H__
#define __IMAGE_DISPLAY_H__

#include <stdint.h>

/**
 * Load a raw RGBA8888 image from file and render it directly into an ABGR8888
 * VRAM framebuffer (blended over black).
 *
 * @param framebuffer Uncached VRAM destination framebuffer
 * @param buffer_stride Framebuffer stride in pixels (512 on PSP)
 * @param filename Path to the raw image file
 * @param width Image width in pixels (<= 480)
 * @param height Image height in pixels (<= 272)
 * @return 1 if the full image was read and rendered, 0 otherwise
 */
int loadImageToFramebuffer(
    uint32_t *framebuffer,
    int buffer_stride,
    const char *filename,
    int width,
    int height);

#endif
