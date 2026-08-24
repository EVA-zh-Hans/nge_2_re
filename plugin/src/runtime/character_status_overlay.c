#include <pspctrl.h>
#include <pspdisplay.h>
#include <pspkernel.h>
#include <pspthreadman.h>

#include "atlas_data.h"
#include "character_status_overlay.h"
#include "hook_write.h"
#include "runtime_log.h"

#define OVERLAY_THREAD_PRIORITY 0x30
#define OVERLAY_THREAD_STACK_SIZE 0x2000
#define PSP_SCREEN_WIDTH 480
#define PSP_SCREEN_HEIGHT 272
#define UI_ATLAS_SIZE 256
#define UI_ATLAS_CELL_SIZE 16
#define UI_ATLAS_COLUMNS 16
#define PSP_UNCACHED_USER_MASK 0x40000000u
#define OVERLAY_VISIBLE_BIT 0x01u
#define OVERLAY_PAGE_SHIFT 8u

/* These are all game-side cross-references to sceDisplaySetFrameBuf. */
#define DISPLAY_SET_FRAMEBUF_GAME_ADDR 0x089B2AB8u
#define DISPLAY_SET_FRAMEBUF_CALL_INIT 0x0898D614u
#define DISPLAY_SET_FRAMEBUF_CALL_ENABLE 0x0898DE00u
#define DISPLAY_SET_FRAMEBUF_CALL_SWAP 0x0898DF10u

extern unsigned char atlas_bin[];

static const Eva2GlyphAtlas g_overlay_atlas = {
    atlas_bin,
    UI_ATLAS_SIZE,
    UI_ATLAS_SIZE,
    UI_ATLAS_CELL_SIZE,
    UI_ATLAS_COLUMNS,
    (const Eva2AtlasGlyph *)atlas_index,
    ATLAS_CHAR_COUNT,
};

static volatile int g_overlay_running;
static volatile uint32_t g_overlay_display_state;
static SceUID g_overlay_thread = -1;
static const volatile Eva2CharacterStats *g_characters;
static uint32_t g_game_base;

static int CharacterStatusOverlay_SetFrameBuf(
    void *topaddr,
    int bufferwidth,
    int pixelformat,
    int sync)
{
    uint32_t display_state = g_overlay_display_state;

    if ((display_state & OVERLAY_VISIBLE_BIT) != 0 && topaddr &&
        bufferwidth >= PSP_SCREEN_WIDTH &&
        pixelformat >= PSP_DISPLAY_PIXEL_FORMAT_565 &&
        pixelformat <= PSP_DISPLAY_PIXEL_FORMAT_8888) {
        Eva2FrameBuffer framebuffer;
        framebuffer.pixels = (void *)((uintptr_t)topaddr | PSP_UNCACHED_USER_MASK);
        framebuffer.width = PSP_SCREEN_WIDTH;
        framebuffer.height = PSP_SCREEN_HEIGHT;
        framebuffer.stride = bufferwidth;
        framebuffer.pixel_format = (Eva2PixelFormat)pixelformat;
        Eva2CharacterStatusOverlay_Draw(
            &framebuffer,
            &g_overlay_atlas,
            g_characters,
            (uint8_t)(display_state >> OVERLAY_PAGE_SHIFT));
    }

    return sceDisplaySetFrameBuf(topaddr, bufferwidth, pixelformat, sync);
}

static void CharacterStatusOverlay_SetDisplayHooks(uint32_t game_base, int enabled)
{
    const void *target = enabled
        ? (const void *)CharacterStatusOverlay_SetFrameBuf
        : (const void *)HookWrite_GameAddr(game_base, DISPLAY_SET_FRAMEBUF_GAME_ADDR);

    HookWrite_Call(
        HookWrite_GameAddr(game_base, DISPLAY_SET_FRAMEBUF_CALL_INIT),
        target);
    HookWrite_Call(
        HookWrite_GameAddr(game_base, DISPLAY_SET_FRAMEBUF_CALL_ENABLE),
        target);
    HookWrite_Call(
        HookWrite_GameAddr(game_base, DISPLAY_SET_FRAMEBUF_CALL_SWAP),
        target);
    HookWrite_FlushCaches();
}

static int CharacterStatusOverlay_Thread(SceSize args, void *argp)
{
    Eva2CharacterOverlayState state;
    SceCtrlData pad;

    (void)args;
    (void)argp;
    Eva2CharacterOverlayState_Init(&state);

    while (g_overlay_running) {
        sceDisplayWaitVblankStart();
        if (!g_overlay_running) {
            break;
        }

        if (sceCtrlPeekBufferPositive(&pad, 1) > 0) {
            Eva2CharacterOverlayState_Update(&state, pad.Buttons);
            g_overlay_display_state =
                (state.visible ? OVERLAY_VISIBLE_BIT : 0u) |
                ((uint32_t)state.page << OVERLAY_PAGE_SHIFT);
        }
    }

    return sceKernelExitThread(0);
}

void CharacterStatusOverlay_Start(uint32_t game_base)
{
    int result;

    if (g_overlay_thread >= 0) {
        return;
    }

    g_characters = (const volatile Eva2CharacterStats *)HookWrite_GameAddr(
        game_base,
        EVA2_CHARACTER_STATS_GAME_ADDR);
    g_game_base = game_base;
    g_overlay_display_state = 0;
    g_overlay_running = 1;
    g_overlay_thread = sceKernelCreateThread(
        "Eva2CharacterStatus",
        CharacterStatusOverlay_Thread,
        OVERLAY_THREAD_PRIORITY,
        OVERLAY_THREAD_STACK_SIZE,
        0,
        0);
    if (g_overlay_thread < 0) {
        RuntimeLog_Printf("character status thread create failed: %d", g_overlay_thread);
        g_overlay_running = 0;
        g_characters = 0;
        g_game_base = 0;
        return;
    }

    result = sceKernelStartThread(g_overlay_thread, 0, 0);
    if (result < 0) {
        RuntimeLog_Printf("character status thread start failed: %d", result);
        sceKernelDeleteThread(g_overlay_thread);
        g_overlay_thread = -1;
        g_overlay_running = 0;
        g_characters = 0;
        g_game_base = 0;
        return;
    }
    CharacterStatusOverlay_SetDisplayHooks(game_base, 1);
    RuntimeLog_Printf(
        "character status overlay started stats=%08x setfb=%08x",
        (unsigned)g_characters,
        (unsigned)CharacterStatusOverlay_SetFrameBuf);
}

void CharacterStatusOverlay_Stop(void)
{
    SceUID thread = g_overlay_thread;

    if (thread < 0) {
        return;
    }
    CharacterStatusOverlay_SetDisplayHooks(g_game_base, 0);
    g_overlay_display_state = 0;
    g_overlay_running = 0;
    sceKernelWaitThreadEnd(thread, 0);
    sceKernelDeleteThread(thread);
    g_overlay_thread = -1;
    g_characters = 0;
    g_game_base = 0;
    RuntimeLog_Printf("character status overlay stopped");
}
