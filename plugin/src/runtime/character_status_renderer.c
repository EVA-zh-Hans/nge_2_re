#include "character_status_overlay.h"

#define OVERLAY_PANEL_X 2
#define OVERLAY_PANEL_Y 2
#define OVERLAY_PANEL_WIDTH 476
#define OVERLAY_PANEL_HEIGHT 268
#define OVERLAY_TABLE_TOP 32
#define OVERLAY_LABEL_WIDTH 76
#define OVERLAY_COLUMN_WIDTH 100
#define OVERLAY_HEADER_HEIGHT 20
#define OVERLAY_ROW_HEIGHT 18

static uint8_t expand_4(uint32_t value)
{
    return (uint8_t)((value << 4) | value);
}

static uint8_t expand_5(uint32_t value)
{
    return (uint8_t)((value << 3) | (value >> 2));
}

static uint8_t expand_6(uint32_t value)
{
    return (uint8_t)((value << 2) | (value >> 4));
}

static int framebuffer_valid(const Eva2FrameBuffer *framebuffer)
{
    return framebuffer && framebuffer->pixels && framebuffer->width > 0 &&
        framebuffer->height > 0 && framebuffer->stride >= framebuffer->width &&
        framebuffer->pixel_format >= EVA2_PIXEL_FORMAT_565 &&
        framebuffer->pixel_format <= EVA2_PIXEL_FORMAT_8888;
}

static Eva2Color unpack_pixel(const Eva2FrameBuffer *framebuffer, size_t offset)
{
    Eva2Color color;

    if (framebuffer->pixel_format == EVA2_PIXEL_FORMAT_8888) {
        uint32_t pixel = ((const uint32_t *)framebuffer->pixels)[offset];
        color.red = (uint8_t)pixel;
        color.green = (uint8_t)(pixel >> 8);
        color.blue = (uint8_t)(pixel >> 16);
        color.alpha = (uint8_t)(pixel >> 24);
    } else {
        uint16_t pixel = ((const uint16_t *)framebuffer->pixels)[offset];
        if (framebuffer->pixel_format == EVA2_PIXEL_FORMAT_565) {
            color.red = expand_5(pixel & 0x1fu);
            color.green = expand_6((pixel >> 5) & 0x3fu);
            color.blue = expand_5((pixel >> 11) & 0x1fu);
            color.alpha = 255;
        } else if (framebuffer->pixel_format == EVA2_PIXEL_FORMAT_5551) {
            color.red = expand_5(pixel & 0x1fu);
            color.green = expand_5((pixel >> 5) & 0x1fu);
            color.blue = expand_5((pixel >> 10) & 0x1fu);
            color.alpha = (pixel & 0x8000u) ? 255 : 0;
        } else {
            color.red = expand_4(pixel & 0x0fu);
            color.green = expand_4((pixel >> 4) & 0x0fu);
            color.blue = expand_4((pixel >> 8) & 0x0fu);
            color.alpha = expand_4((pixel >> 12) & 0x0fu);
        }
    }
    return color;
}

static void pack_pixel(Eva2FrameBuffer *framebuffer, size_t offset, Eva2Color color)
{
    if (framebuffer->pixel_format == EVA2_PIXEL_FORMAT_8888) {
        ((uint32_t *)framebuffer->pixels)[offset] =
            (uint32_t)color.red |
            ((uint32_t)color.green << 8) |
            ((uint32_t)color.blue << 16) |
            ((uint32_t)color.alpha << 24);
    } else if (framebuffer->pixel_format == EVA2_PIXEL_FORMAT_565) {
        ((uint16_t *)framebuffer->pixels)[offset] = (uint16_t)(
            ((uint16_t)(color.red >> 3)) |
            ((uint16_t)(color.green >> 2) << 5) |
            ((uint16_t)(color.blue >> 3) << 11));
    } else if (framebuffer->pixel_format == EVA2_PIXEL_FORMAT_5551) {
        ((uint16_t *)framebuffer->pixels)[offset] = (uint16_t)(
            ((uint16_t)(color.red >> 3)) |
            ((uint16_t)(color.green >> 3) << 5) |
            ((uint16_t)(color.blue >> 3) << 10) |
            ((uint16_t)(color.alpha >= 128) << 15));
    } else {
        ((uint16_t *)framebuffer->pixels)[offset] = (uint16_t)(
            ((uint16_t)(color.red >> 4)) |
            ((uint16_t)(color.green >> 4) << 4) |
            ((uint16_t)(color.blue >> 4) << 8) |
            ((uint16_t)(color.alpha >> 4) << 12));
    }
}

static void blend_pixel_at_offset(
    Eva2FrameBuffer *framebuffer,
    size_t offset,
    Eva2Color color)
{
    Eva2Color destination;
    uint32_t inverse_alpha;

    if (color.alpha == 0) {
        return;
    }
    if (color.alpha == 255) {
        pack_pixel(framebuffer, offset, color);
        return;
    }

    destination = unpack_pixel(framebuffer, offset);
    inverse_alpha = 255u - color.alpha;
    destination.red = (uint8_t)(
        ((uint32_t)color.red * color.alpha +
         (uint32_t)destination.red * inverse_alpha + 127u) / 255u);
    destination.green = (uint8_t)(
        ((uint32_t)color.green * color.alpha +
         (uint32_t)destination.green * inverse_alpha + 127u) / 255u);
    destination.blue = (uint8_t)(
        ((uint32_t)color.blue * color.alpha +
         (uint32_t)destination.blue * inverse_alpha + 127u) / 255u);
    destination.alpha = (uint8_t)(
        color.alpha + ((uint32_t)destination.alpha * inverse_alpha + 127u) / 255u);
    pack_pixel(framebuffer, offset, destination);
}

void Eva2SoftwareRenderer_BlendPixel(
    Eva2FrameBuffer *framebuffer,
    int x,
    int y,
    Eva2Color color)
{
    size_t offset;

    if (!framebuffer_valid(framebuffer) || x < 0 || y < 0 ||
        x >= framebuffer->width || y >= framebuffer->height) {
        return;
    }

    offset = (size_t)y * (size_t)framebuffer->stride + (size_t)x;
    blend_pixel_at_offset(framebuffer, offset, color);
}

Eva2Color Eva2SoftwareRenderer_ReadPixel(
    const Eva2FrameBuffer *framebuffer,
    int x,
    int y)
{
    static const Eva2Color transparent = {0, 0, 0, 0};
    size_t offset;

    if (!framebuffer_valid(framebuffer) || x < 0 || y < 0 ||
        x >= framebuffer->width || y >= framebuffer->height) {
        return transparent;
    }
    offset = (size_t)y * (size_t)framebuffer->stride + (size_t)x;
    return unpack_pixel(framebuffer, offset);
}

void Eva2SoftwareRenderer_FillRect(
    Eva2FrameBuffer *framebuffer,
    int x,
    int y,
    int width,
    int height,
    Eva2Color color)
{
    int clipped_left;
    int clipped_top;
    int clipped_right;
    int clipped_bottom;
    int draw_x;
    int draw_y;

    if (!framebuffer_valid(framebuffer) || width <= 0 || height <= 0) {
        return;
    }

    clipped_left = x < 0 ? 0 : x;
    clipped_top = y < 0 ? 0 : y;
    clipped_right = x + width > framebuffer->width ? framebuffer->width : x + width;
    clipped_bottom = y + height > framebuffer->height ? framebuffer->height : y + height;
    if (color.alpha == 255) {
        for (draw_y = clipped_top; draw_y < clipped_bottom; ++draw_y) {
            for (draw_x = clipped_left; draw_x < clipped_right; ++draw_x) {
                size_t offset =
                    (size_t)draw_y * (size_t)framebuffer->stride + (size_t)draw_x;
                pack_pixel(framebuffer, offset, color);
            }
        }
        return;
    }
    for (draw_y = clipped_top; draw_y < clipped_bottom; ++draw_y) {
        for (draw_x = clipped_left; draw_x < clipped_right; ++draw_x) {
            size_t offset =
                (size_t)draw_y * (size_t)framebuffer->stride + (size_t)draw_x;
            blend_pixel_at_offset(framebuffer, offset, color);
        }
    }
}

static uint32_t next_utf8_character(const char **text)
{
    const uint8_t *bytes = (const uint8_t *)*text;
    uint32_t code;

    if (bytes[0] < 0x80u) {
        *text += 1;
        return bytes[0];
    }
    if ((bytes[0] & 0xe0u) == 0xc0u && bytes[1] != 0 &&
        (bytes[1] & 0xc0u) == 0x80u) {
        code = ((uint32_t)(bytes[0] & 0x1fu) << 6) | (bytes[1] & 0x3fu);
        *text += 2;
        return code;
    }
    if ((bytes[0] & 0xf0u) == 0xe0u && bytes[1] != 0 && bytes[2] != 0 &&
        (bytes[1] & 0xc0u) == 0x80u && (bytes[2] & 0xc0u) == 0x80u) {
        code = ((uint32_t)(bytes[0] & 0x0fu) << 12) |
            ((uint32_t)(bytes[1] & 0x3fu) << 6) | (bytes[2] & 0x3fu);
        *text += 3;
        return code;
    }
    *text += 1;
    return '?';
}

static int atlas_glyph_index(const Eva2GlyphAtlas *atlas, uint32_t code)
{
    int low = 0;
    int high = (int)atlas->glyph_count - 1;

    while (low <= high) {
        int middle = low + (high - low) / 2;
        if (atlas->glyphs[middle].code == code) {
            return middle;
        }
        if (atlas->glyphs[middle].code < code) {
            low = middle + 1;
        } else {
            high = middle - 1;
        }
    }
    return -1;
}

static int atlas_valid(const Eva2GlyphAtlas *atlas)
{
    return atlas && atlas->pixels && atlas->glyphs && atlas->glyph_count != 0 &&
        atlas->width > 0 && atlas->height > 0 && atlas->cell_size > 0 &&
        atlas->columns > 0;
}

static int draw_glyph(
    Eva2FrameBuffer *framebuffer,
    const Eva2GlyphAtlas *atlas,
    int glyph_index,
    int x,
    int y,
    Eva2Color color)
{
    int source_x = (glyph_index % atlas->columns) * atlas->cell_size;
    int source_y = (glyph_index / atlas->columns) * atlas->cell_size;
    int glyph_x;
    int glyph_y;

    for (glyph_y = 0; glyph_y < atlas->cell_size; ++glyph_y) {
        if (y + glyph_y < 0 || y + glyph_y >= framebuffer->height ||
            source_y + glyph_y >= atlas->height) {
            continue;
        }
        for (glyph_x = 0; glyph_x < atlas->cell_size; ++glyph_x) {
            Eva2Color pixel_color = color;
            uint8_t atlas_alpha;
            if (x + glyph_x < 0 || x + glyph_x >= framebuffer->width ||
                source_x + glyph_x >= atlas->width) {
                continue;
            }
            atlas_alpha = atlas->pixels[
                (size_t)(source_y + glyph_y) * (size_t)atlas->width +
                (size_t)(source_x + glyph_x)];
            if (atlas_alpha == 0) {
                continue;
            }
            pixel_color.alpha = (uint8_t)(
                ((uint32_t)color.alpha * atlas_alpha + 127u) / 255u);
            blend_pixel_at_offset(
                framebuffer,
                (size_t)(y + glyph_y) * (size_t)framebuffer->stride +
                    (size_t)(x + glyph_x),
                pixel_color);
        }
    }
    return atlas->glyphs[glyph_index].width + 1;
}

int Eva2SoftwareRenderer_MeasureText(const Eva2GlyphAtlas *atlas, const char *text)
{
    int width = 0;
    const char *cursor = text;

    if (!atlas_valid(atlas) || !text) {
        return 0;
    }
    while (*cursor) {
        int glyph_index = atlas_glyph_index(atlas, next_utf8_character(&cursor));
        if (glyph_index >= 0) {
            width += atlas->glyphs[glyph_index].width + 1;
        }
    }
    return width > 0 ? width - 1 : 0;
}

int Eva2SoftwareRenderer_DrawText(
    Eva2FrameBuffer *framebuffer,
    const Eva2GlyphAtlas *atlas,
    int x,
    int y,
    const char *text,
    Eva2Color color)
{
    int cursor_x = x;
    const char *cursor = text;

    if (!framebuffer_valid(framebuffer) || !atlas_valid(atlas) || !text) {
        return x;
    }
    while (*cursor) {
        int glyph_index = atlas_glyph_index(atlas, next_utf8_character(&cursor));
        if (glyph_index >= 0) {
            cursor_x += draw_glyph(framebuffer, atlas, glyph_index, cursor_x, y, color);
        }
    }
    return cursor_x;
}

static void draw_centered_text(
    Eva2FrameBuffer *framebuffer,
    const Eva2GlyphAtlas *atlas,
    int cell_x,
    int cell_width,
    int y,
    const char *text,
    Eva2Color color)
{
    int text_width = Eva2SoftwareRenderer_MeasureText(atlas, text);
    int x = cell_x + (cell_width - text_width) / 2;
    Eva2SoftwareRenderer_DrawText(framebuffer, atlas, x, y, text, color);
}

void Eva2CharacterStatusOverlay_Draw(
    Eva2FrameBuffer *framebuffer,
    const Eva2GlyphAtlas *atlas,
    const volatile Eva2CharacterStats *characters,
    uint8_t page)
{
    static const Eva2Color panel_color = {12, 14, 18, 188};
    static const Eva2Color grid_color = {220, 224, 230, 72};
    static const Eva2Color title_color = {255, 210, 96, 255};
    static const Eva2Color header_color = {137, 222, 255, 255};
    static const Eva2Color label_color = {215, 218, 224, 255};
    static const Eva2Color value_color = {255, 255, 255, 255};
    char value_buffer[11];
    char page_buffer[4];
    size_t page_start;
    int row;
    int column;

    if (!framebuffer_valid(framebuffer) || !atlas_valid(atlas) || !characters) {
        return;
    }

    page = (uint8_t)(page % EVA2_CHARACTER_PAGE_COUNT);
    page_start = Eva2CharacterStatus_PageStart(page);
    page_buffer[0] = (char)('1' + page);
    page_buffer[1] = '/';
    page_buffer[2] = '4';
    page_buffer[3] = '\0';

    Eva2SoftwareRenderer_FillRect(
        framebuffer,
        OVERLAY_PANEL_X,
        OVERLAY_PANEL_Y,
        OVERLAY_PANEL_WIDTH,
        OVERLAY_PANEL_HEIGHT,
        panel_color);
    Eva2SoftwareRenderer_DrawText(framebuffer, atlas, 10, 9, "角色状态", title_color);
    Eva2SoftwareRenderer_DrawText(framebuffer, atlas, 444, 9, page_buffer, title_color);

    Eva2SoftwareRenderer_FillRect(
        framebuffer, OVERLAY_PANEL_X, OVERLAY_TABLE_TOP, OVERLAY_PANEL_WIDTH, 1, grid_color);
    Eva2SoftwareRenderer_FillRect(
        framebuffer,
        OVERLAY_PANEL_X,
        OVERLAY_TABLE_TOP + OVERLAY_HEADER_HEIGHT,
        OVERLAY_PANEL_WIDTH,
        1,
        grid_color);
    Eva2SoftwareRenderer_FillRect(
        framebuffer,
        OVERLAY_PANEL_X + OVERLAY_LABEL_WIDTH,
        OVERLAY_TABLE_TOP,
        1,
        OVERLAY_HEADER_HEIGHT + OVERLAY_ROW_HEIGHT * EVA2_CHARACTER_STAT_COUNT,
        grid_color);
    for (column = 1; column < (int)EVA2_CHARACTERS_PER_PAGE; ++column) {
        Eva2SoftwareRenderer_FillRect(
            framebuffer,
            OVERLAY_PANEL_X + OVERLAY_LABEL_WIDTH + column * OVERLAY_COLUMN_WIDTH,
            OVERLAY_TABLE_TOP,
            1,
            OVERLAY_HEADER_HEIGHT + OVERLAY_ROW_HEIGHT * EVA2_CHARACTER_STAT_COUNT,
            grid_color);
    }
    for (row = 1; row <= (int)EVA2_CHARACTER_STAT_COUNT; ++row) {
        Eva2SoftwareRenderer_FillRect(
            framebuffer,
            OVERLAY_PANEL_X,
            OVERLAY_TABLE_TOP + OVERLAY_HEADER_HEIGHT + row * OVERLAY_ROW_HEIGHT,
            OVERLAY_PANEL_WIDTH,
            1,
            grid_color);
    }

    for (column = 0; column < (int)EVA2_CHARACTERS_PER_PAGE; ++column) {
        draw_centered_text(
            framebuffer,
            atlas,
            OVERLAY_PANEL_X + OVERLAY_LABEL_WIDTH + column * OVERLAY_COLUMN_WIDTH,
            OVERLAY_COLUMN_WIDTH,
            OVERLAY_TABLE_TOP + 2,
            Eva2CharacterStatus_Name(page_start + (size_t)column),
            header_color);
    }

    for (row = 0; row < (int)EVA2_CHARACTER_STAT_COUNT; ++row) {
        int text_y = OVERLAY_TABLE_TOP + OVERLAY_HEADER_HEIGHT + row * OVERLAY_ROW_HEIGHT + 1;
        Eva2SoftwareRenderer_DrawText(
            framebuffer,
            atlas,
            OVERLAY_PANEL_X + 7,
            text_y,
            Eva2CharacterStatus_Label((Eva2CharacterStat)row),
            label_color);
        for (column = 0; column < (int)EVA2_CHARACTERS_PER_PAGE; ++column) {
            Eva2CharacterStatus_FormatUint32(
                Eva2CharacterStatus_Read(
                    &characters[page_start + (size_t)column],
                    (Eva2CharacterStat)row),
                value_buffer,
                sizeof(value_buffer));
            draw_centered_text(
                framebuffer,
                atlas,
                OVERLAY_PANEL_X + OVERLAY_LABEL_WIDTH + column * OVERLAY_COLUMN_WIDTH,
                OVERLAY_COLUMN_WIDTH,
                text_y,
                value_buffer,
                value_color);
        }
    }
}
