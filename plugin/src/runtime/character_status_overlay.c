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

extern unsigned char atlas_bin[];

static volatile int g_overlay_running;
static SceUID g_overlay_thread = -1;
static const volatile Eva2CharacterStats *g_characters;

static int CharacterStatusOverlay_Thread(SceSize args, void *argp)
{
    static const Eva2GlyphAtlas atlas = {
        atlas_bin,
        UI_ATLAS_SIZE,
        UI_ATLAS_SIZE,
        UI_ATLAS_CELL_SIZE,
        UI_ATLAS_COLUMNS,
        (const Eva2AtlasGlyph *)atlas_index,
        ATLAS_CHAR_COUNT,
    };
    Eva2CharacterOverlayState state;
    SceCtrlData pad;

    (void)args;
    (void)argp;
    Eva2CharacterOverlayState_Init(&state);

    while (g_overlay_running) {
        void *pixels = 0;
        int stride = 0;
        int pixel_format = 0;

        sceDisplayWaitVblankStart();
        if (!g_overlay_running) {
            break;
        }

        if (sceCtrlPeekBufferPositive(&pad, 1) > 0) {
            Eva2CharacterOverlayState_Update(&state, pad.Buttons);
        }
        if (!state.visible) {
            continue;
        }

        if (sceDisplayGetFrameBuf(
                &pixels,
                &stride,
                &pixel_format,
                PSP_DISPLAY_SETBUF_IMMEDIATE) == 0 && pixels && stride >= PSP_SCREEN_WIDTH &&
            pixel_format >= PSP_DISPLAY_PIXEL_FORMAT_565 &&
            pixel_format <= PSP_DISPLAY_PIXEL_FORMAT_8888) {
            Eva2FrameBuffer framebuffer;
            framebuffer.pixels = (void *)((uintptr_t)pixels | PSP_UNCACHED_USER_MASK);
            framebuffer.width = PSP_SCREEN_WIDTH;
            framebuffer.height = PSP_SCREEN_HEIGHT;
            framebuffer.stride = stride;
            framebuffer.pixel_format = (Eva2PixelFormat)pixel_format;
            Eva2CharacterStatusOverlay_Draw(&framebuffer, &atlas, g_characters, state.page);
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
        return;
    }

    result = sceKernelStartThread(g_overlay_thread, 0, 0);
    if (result < 0) {
        RuntimeLog_Printf("character status thread start failed: %d", result);
        sceKernelDeleteThread(g_overlay_thread);
        g_overlay_thread = -1;
        g_overlay_running = 0;
        return;
    }
    RuntimeLog_Printf(
        "character status overlay started stats=%08x",
        (unsigned)g_characters);
}

void CharacterStatusOverlay_Stop(void)
{
    SceUID thread = g_overlay_thread;

    if (thread < 0) {
        return;
    }
    g_overlay_running = 0;
    sceKernelWaitThreadEnd(thread, 0);
    sceKernelDeleteThread(thread);
    g_overlay_thread = -1;
    g_characters = 0;
    RuntimeLog_Printf("character status overlay stopped");
}
