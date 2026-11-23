#include <stdint.h>
#include "atlas_data.h"
#include "ui_atlas.h"

#define ATLAS_WIDTH 256
#define ATLAS_CELL_SIZE 16
#define ATLAS_COLS (ATLAS_WIDTH / ATLAS_CELL_SIZE)

extern unsigned char atlas_bin[]; // 256x256 8-bit alpha coverage (64KB)

static uint32_t next_utf8_char(const char **s) {
    const unsigned char *p = (const unsigned char *)*s;
    if (p[0] < 0x80u) {
        *s += 1;
        return p[0];
    }
    if ((p[0] & 0xE0u) == 0xC0u && p[1] != 0 && (p[1] & 0xC0u) == 0x80u) {
        uint32_t res = ((uint32_t)(p[0] & 0x1Fu) << 6) | (uint32_t)(p[1] & 0x3Fu);
        *s += 2;
        return res;
    }
    if ((p[0] & 0xF0u) == 0xE0u &&
        p[1] != 0 && p[2] != 0 &&
        (p[1] & 0xC0u) == 0x80u && (p[2] & 0xC0u) == 0x80u) {
        uint32_t res = ((uint32_t)(p[0] & 0x0Fu) << 12) |
                       ((uint32_t)(p[1] & 0x3Fu) << 6) |
                       (uint32_t)(p[2] & 0x3Fu);
        *s += 3;
        return res;
    }
    *s += 1;
    return '?';
}

static int get_char_info(uint32_t code, int *width) {
    int low = 0;
    int high = ATLAS_CHAR_COUNT - 1;
    while (low <= high) {
        int mid = (low + high) / 2;
        if (atlas_index[mid].code == code) {
            *width = atlas_index[mid].width;
            return mid;
        }
        if (atlas_index[mid].code < code) {
            low = mid + 1;
        } else {
            high = mid - 1;
        }
    }
    return -1;
}

static inline uint32_t blend_abgr8888(uint32_t dst, uint32_t src_color, uint8_t coverage) {
    uint32_t src_a = (src_color >> 24) & 0xFFu;
    uint32_t a = (src_a * (uint32_t)coverage + 127u) / 255u;
    if (a == 0u) {
        return dst;
    }
    if (a == 255u) {
        return 0xFF000000u | (src_color & 0x00FFFFFFu);
    }

    uint32_t inv_a = 255u - a;
    uint32_t sr = src_color & 0xFFu;
    uint32_t sg = (src_color >> 8) & 0xFFu;
    uint32_t sb = (src_color >> 16) & 0xFFu;
    uint32_t dr = dst & 0xFFu;
    uint32_t dg = (dst >> 8) & 0xFFu;
    uint32_t db = (dst >> 16) & 0xFFu;
    uint32_t rr = (sr * a + dr * inv_a + 127u) / 255u;
    uint32_t rg = (sg * a + dg * inv_a + 127u) / 255u;
    uint32_t rb = (sb * a + db * inv_a + 127u) / 255u;
    return 0xFF000000u | rr | (rg << 8) | (rb << 16);
}

int uiTextWidth(const char *str) {
    const char *p = str;
    int width = 0;
    while (*p) {
        int char_w = 0;
        if (get_char_info(next_utf8_char(&p), &char_w) >= 0) {
            width += char_w + 1;
        }
    }
    return width;
}

void uiPrint(
    uint32_t *framebuffer,
    int buffer_stride,
    int screen_width,
    int screen_height,
    int x,
    int y,
    const char *str,
    uint32_t color) {
    const char *p = str;
    int cur_x = x;

    if (!framebuffer || !str) {
        return;
    }

    while (*p) {
        int char_w = 0;
        int idx = get_char_info(next_utf8_char(&p), &char_w);
        if (idx < 0) {
            continue;
        }

        int u = (idx % ATLAS_COLS) * ATLAS_CELL_SIZE;
        int v = (idx / ATLAS_COLS) * ATLAS_CELL_SIZE;

        for (int gy = 0; gy < ATLAS_CELL_SIZE; ++gy) {
            int py = y + gy;
            if (py < 0 || py >= screen_height) {
                continue;
            }
            const unsigned char *glyph_row = atlas_bin + (v + gy) * ATLAS_WIDTH + u;
            uint32_t *dst_row = framebuffer + py * buffer_stride;

            for (int gx = 0; gx < ATLAS_CELL_SIZE; ++gx) {
                int px = cur_x + gx;
                if (px < 0 || px >= screen_width) {
                    continue;
                }
                uint8_t coverage = glyph_row[gx];
                if (coverage == 0) {
                    continue;
                }
                dst_row[px] = blend_abgr8888(dst_row[px], color, coverage);
            }
        }

        cur_x += char_w + 1;
    }
}
