#ifndef EVA2_CHARACTER_STATUS_OVERLAY_H
#define EVA2_CHARACTER_STATUS_OVERLAY_H

#include <stddef.h>
#include <stdint.h>

#define EVA2_CHARACTER_COUNT 16u
#define EVA2_CHARACTERS_PER_PAGE 4u
#define EVA2_CHARACTER_PAGE_COUNT 4u
#define EVA2_CHARACTER_STAT_COUNT 12u
#define EVA2_CHARACTER_STATS_SIZE 0x1A50u
#define EVA2_CHARACTER_STATS_GAME_ADDR 0x08B59B54u

/* These values match PSP_CTRL_LTRIGGER and PSP_CTRL_RTRIGGER. */
#define EVA2_CHARACTER_BUTTON_L 0x00000100u
#define EVA2_CHARACTER_BUTTON_R 0x00000200u

#if defined(__GNUC__)
#pragma pack(push, 1)
#endif
typedef struct Eva2CharacterStats {
    uint16_t impulse;
    uint8_t reserved_0002[0x026];
    uint8_t transaction;
    uint8_t reserved_0029[3];
    uint8_t intelligence;
    uint8_t reserved_002d[3];
    uint8_t combat;
    uint8_t reserved_0031[3];
    uint8_t synchronization;
    uint8_t reserved_0035[0x073];
    uint8_t hunger;
    uint8_t reserved_00a9[3];
    uint8_t hydration;
    uint8_t reserved_00ad[3];
    uint8_t sleepiness;
    uint8_t reserved_00b1[3];
    uint8_t toilet;
    uint8_t reserved_00b5[3];
    uint8_t bathing;
    uint8_t reserved_00b9[0x027];
    uint32_t money;
    uint8_t reserved_00e4[0x0a8];
    uint8_t at;
    uint8_t reserved_018d[0x18c3];
} Eva2CharacterStats;
#if defined(__GNUC__)
#pragma pack(pop)
#endif

typedef enum Eva2CharacterStat {
    EVA2_CHARACTER_STAT_AT = 0,
    EVA2_CHARACTER_STAT_IMPULSE,
    EVA2_CHARACTER_STAT_TRANSACTION,
    EVA2_CHARACTER_STAT_INTELLIGENCE,
    EVA2_CHARACTER_STAT_COMBAT,
    EVA2_CHARACTER_STAT_SYNCHRONIZATION,
    EVA2_CHARACTER_STAT_HUNGER,
    EVA2_CHARACTER_STAT_HYDRATION,
    EVA2_CHARACTER_STAT_SLEEPINESS,
    EVA2_CHARACTER_STAT_TOILET,
    EVA2_CHARACTER_STAT_BATHING,
    EVA2_CHARACTER_STAT_MONEY
} Eva2CharacterStat;

typedef struct Eva2CharacterOverlayState {
    uint32_t previous_buttons;
    uint8_t visible;
    uint8_t page;
} Eva2CharacterOverlayState;

typedef enum Eva2PixelFormat {
    EVA2_PIXEL_FORMAT_565 = 0,
    EVA2_PIXEL_FORMAT_5551 = 1,
    EVA2_PIXEL_FORMAT_4444 = 2,
    EVA2_PIXEL_FORMAT_8888 = 3
} Eva2PixelFormat;

typedef struct Eva2Color {
    uint8_t red;
    uint8_t green;
    uint8_t blue;
    uint8_t alpha;
} Eva2Color;

typedef struct Eva2FrameBuffer {
    void *pixels;
    int width;
    int height;
    int stride;
    Eva2PixelFormat pixel_format;
} Eva2FrameBuffer;

typedef struct Eva2AtlasGlyph {
    uint16_t code;
    uint8_t width;
} Eva2AtlasGlyph;

typedef struct Eva2GlyphAtlas {
    const uint8_t *pixels;
    int width;
    int height;
    int cell_size;
    int columns;
    const Eva2AtlasGlyph *glyphs;
    size_t glyph_count;
} Eva2GlyphAtlas;

void Eva2CharacterOverlayState_Init(Eva2CharacterOverlayState *state);
void Eva2CharacterOverlayState_Update(Eva2CharacterOverlayState *state, uint32_t buttons);
const char *Eva2CharacterStatus_Name(size_t character_index);
const char *Eva2CharacterStatus_Label(Eva2CharacterStat stat);
size_t Eva2CharacterStatus_PageStart(uint8_t page);
uint32_t Eva2CharacterStatus_Read(
    const volatile Eva2CharacterStats *character,
    Eva2CharacterStat stat);
size_t Eva2CharacterStatus_FormatUint32(uint32_t value, char *buffer, size_t buffer_size);

void Eva2SoftwareRenderer_BlendPixel(
    Eva2FrameBuffer *framebuffer,
    int x,
    int y,
    Eva2Color color);
Eva2Color Eva2SoftwareRenderer_ReadPixel(
    const Eva2FrameBuffer *framebuffer,
    int x,
    int y);
void Eva2SoftwareRenderer_FillRect(
    Eva2FrameBuffer *framebuffer,
    int x,
    int y,
    int width,
    int height,
    Eva2Color color);
int Eva2SoftwareRenderer_MeasureText(const Eva2GlyphAtlas *atlas, const char *text);
int Eva2SoftwareRenderer_DrawText(
    Eva2FrameBuffer *framebuffer,
    const Eva2GlyphAtlas *atlas,
    int x,
    int y,
    const char *text,
    Eva2Color color);
void Eva2CharacterStatusOverlay_Draw(
    Eva2FrameBuffer *framebuffer,
    const Eva2GlyphAtlas *atlas,
    const volatile Eva2CharacterStats *characters,
    uint8_t page);

void CharacterStatusOverlay_Start(uint32_t game_base);
void CharacterStatusOverlay_Stop(void);

#endif
