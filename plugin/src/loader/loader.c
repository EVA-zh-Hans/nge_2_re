#include <pspsdk.h>
#include <stdint.h>
#include <pspkernel.h>
#include <pspthreadman.h>
#include <pspmodulemgr.h>
#include <pspge.h>
#include <pspdisplay.h>
#include <pspctrl.h>

#include "runtime_args.h"
#include "ui_atlas.h"
#include "image_display.h"

/*
 * Run the loader as a pure kernel module (PSP_MODULE_KERNEL + USE_KERNEL_LIBS)
 * so it lives in kernel memory and never occupies user memory at 0x08804000.
 * BOOT.BIN and EVA2RT.PRX are both user-mode PRXs loaded via
 * ModuleMgrForKernel::sceKernelLoadModule, so BOOT.BIN lands at 0x08804000
 * with zero base-address shift.
 */
PSP_MODULE_INFO("EBOOT_LOADER", PSP_MODULE_KERNEL, 1, 1);
PSP_NO_CREATE_MAIN_THREAD();

#define BUFFER_WIDTH 512
#define BUFFER_HEIGHT 272
#define SCREEN_WIDTH 480
#define SCREEN_HEIGHT BUFFER_HEIGHT
#define FRAME_BUFFER_BYTES (BUFFER_WIDTH * BUFFER_HEIGHT * (int)sizeof(uint32_t))

#define PathOldBoot "disc0:/PSP_GAME/SYSDIR/BOOT.BIN"
#define PathRuntime "disc0:/PSP_GAME/SYSDIR/EVA2RT.PRX"
#define MENU_ITEM_COUNT 4
#define MENU_ROW_GAP 24
#define MENU_FIRST_Y 90
#define STRINGIFY_VALUE(value) #value
#define STRINGIFY(value) STRINGIFY_VALUE(value)
#define PROJECT_CREDIT "EVA2 汉化计划 2024-" STRINGIFY(BUILD_YEAR)

static uint32_t *vram_display_buffers[2];
static uint32_t *vram_draw_buffers[2];
static int back_buffer_index = 1;

static int selected_index = 0;
static int last_pad_buttons = 0;
static SceCtrlData pad;

static int enable_pulse_autowin = 0;
static int enable_daily_debug = 0;
static int enable_battle_debug = 0;
static int enable_60_fps = 0;

static void clearFramebuffer(uint32_t *framebuffer, uint32_t color) {
    int count = BUFFER_WIDTH * BUFFER_HEIGHT;
    for (int i = 0; i < count; ++i) {
        framebuffer[i] = color;
    }
}

static void initDisplay(void) {
    uintptr_t vram_base = (uintptr_t)sceGeEdramGetAddr();
    vram_display_buffers[0] = (uint32_t *)vram_base;
    vram_display_buffers[1] = (uint32_t *)(vram_base + (uintptr_t)FRAME_BUFFER_BYTES);
    vram_draw_buffers[0] = (uint32_t *)(vram_base | 0x40000000u);
    vram_draw_buffers[1] = (uint32_t *)((vram_base + (uintptr_t)FRAME_BUFFER_BYTES) | 0x40000000u);
    back_buffer_index = 1;

    clearFramebuffer(vram_draw_buffers[0], 0xFF000000u);
    clearFramebuffer(vram_draw_buffers[1], 0xFF000000u);

    sceDisplaySetMode(0, SCREEN_WIDTH, SCREEN_HEIGHT);
    sceDisplaySetFrameBuf(
        vram_display_buffers[0],
        BUFFER_WIDTH,
        PSP_DISPLAY_PIXEL_FORMAT_8888,
        PSP_DISPLAY_SETBUF_NEXTFRAME);
    sceDisplayWaitVblankStart();
}

static void presentBackBuffer(void) {
    sceDisplayWaitVblankStart();
    sceDisplaySetFrameBuf(
        vram_display_buffers[back_buffer_index],
        BUFFER_WIDTH,
        PSP_DISPLAY_PIXEL_FORMAT_8888,
        PSP_DISPLAY_SETBUF_NEXTFRAME);
    back_buffer_index ^= 1;
}

static void clearDisplayForGame(void) {
    clearFramebuffer(vram_draw_buffers[0], 0xFF000000u);
    clearFramebuffer(vram_draw_buffers[1], 0xFF000000u);
    sceDisplayWaitVblankStart();
    sceDisplaySetFrameBuf(
        vram_display_buffers[0],
        BUFFER_WIDTH,
        PSP_DISPLAY_PIXEL_FORMAT_8888,
        PSP_DISPLAY_SETBUF_NEXTFRAME);
}

static void printCentered(uint32_t *framebuffer, int y, const char *text, uint32_t color) {
    uiPrint(
        framebuffer,
        BUFFER_WIDTH,
        SCREEN_WIDTH,
        SCREEN_HEIGHT,
        (SCREEN_WIDTH - uiTextWidth(text)) / 2,
        y,
        text,
        color);
}

static void handleInput(void) {
    sceCtrlPeekBufferPositive(&pad, 1);

    // Trigger only on rising edge (0 -> 1)
    int pressed_buttons = pad.Buttons & ~last_pad_buttons;
    last_pad_buttons = pad.Buttons;

    if (pressed_buttons & PSP_CTRL_UP) {
        selected_index--;
        if (selected_index < 0) selected_index = MENU_ITEM_COUNT - 1;
    }
    if (pressed_buttons & PSP_CTRL_DOWN) {
        selected_index++;
        if (selected_index >= MENU_ITEM_COUNT) selected_index = 0;
    }

    if (pressed_buttons & PSP_CTRL_CIRCLE) {
        if (selected_index == 0) enable_pulse_autowin = !enable_pulse_autowin;
        if (selected_index == 1) enable_battle_debug = !enable_battle_debug;
        if (selected_index == 2) enable_daily_debug = !enable_daily_debug;
        if (selected_index == 3) enable_60_fps = !enable_60_fps;
    }
}

static void displaySplashImage(const char *filename, int width, int height, int duration_ms) {
    uint32_t *fb = vram_draw_buffers[back_buffer_index];
    clearFramebuffer(fb, 0xFF000000u);
    if (!loadImageToFramebuffer(fb, BUFFER_WIDTH, filename, width, height)) {
        return;
    }
    presentBackBuffer();
    if (duration_ms > 0) {
        sceKernelDelayThread(duration_ms * 1000);
    }
}

static int main_thread(SceSize args, void *argp)
{
    (void)args;
    (void)argp;

    const char *labels[MENU_ITEM_COUNT] = {
        "自动跳过脉冲", "启用战斗调试菜单", "启用日常调试菜单", "60FPS"
    };
    int label_width = 0;
    for (int i = 0; i < MENU_ITEM_COUNT; i++) {
        int width = uiTextWidth(labels[i]);
        if (width > label_width) label_width = width;
    }
    int menu_x = (SCREEN_WIDTH - label_width - 24 - uiTextWidth("[OFF]")) / 2;
    int toggle_x = menu_x + label_width + 24;

    sceCtrlSetSamplingCycle(0);
    sceCtrlSetSamplingMode(PSP_CTRL_MODE_DIGITAL);
    initDisplay();

    while (1) {
        handleInput();

        uint32_t *fb = vram_draw_buffers[back_buffer_index];
        clearFramebuffer(fb, 0xFF000000u);

        const int enabled[MENU_ITEM_COUNT] = {
            enable_pulse_autowin, enable_battle_debug, enable_daily_debug, enable_60_fps
        };
        for (int i = 0; i < MENU_ITEM_COUNT; i++) {
            uint32_t color = (selected_index == i) ? 0xFF00FFFFu : 0xFFFFFFFFu;
            int y = MENU_FIRST_Y + i * MENU_ROW_GAP;
            uiPrint(fb, BUFFER_WIDTH, SCREEN_WIDTH, SCREEN_HEIGHT, menu_x, y, labels[i], color);
            uiPrint(
                fb,
                BUFFER_WIDTH,
                SCREEN_WIDTH,
                SCREEN_HEIGHT,
                toggle_x,
                y,
                enabled[i] ? "[ON]" : "[OFF]",
                color);
        }

        printCentered(fb, 210, "按 START 键启动游戏", 0xFF00AAFFu);
        printCentered(fb, 230, PROJECT_CREDIT, 0xFF00AAFFu);
        printCentered(fb, 245, "插件制作：main_void", 0xFF00AAFFu);

        presentBackBuffer();

        if (pad.Buttons & PSP_CTRL_START) break;
    }

    displaySplashImage("disc0:/PSP_GAME/USRDIR/metadata.raw", 480, 272, 5000);
    clearDisplayForGame();

    SceUID eboot_mid = sceKernelLoadModule(PathOldBoot, 0, NULL);
    if (eboot_mid >= 0) {
        int status = 0;
        SceUID runtime_mid = sceKernelLoadModule(PathRuntime, 0, NULL);
        Eva2RuntimeStartArgs runtime_args;
        runtime_args.boot_mid = eboot_mid;
        runtime_args.flags = 0;
        if (enable_pulse_autowin) {
            runtime_args.flags |= EVA2_FLAG_PULSE_AUTOWIN;
        }
        if (enable_battle_debug) {
            runtime_args.flags |= EVA2_FLAG_BATTLE_DEBUG;
        }
        if (enable_daily_debug) {
            runtime_args.flags |= EVA2_FLAG_DAILY_DEBUG;
        }
        if (enable_60_fps) {
            runtime_args.flags |= EVA2_FLAG_60_FPS;
        }

        if (runtime_mid >= 0) {
            sceKernelStartModule(runtime_mid, sizeof(runtime_args), &runtime_args, &status, NULL);
        }

        sceKernelStartModule(eboot_mid, 0, NULL, &status, NULL);
    }

    return sceKernelExitDeleteThread(0);
}

int module_start(SceSize args, void *argp)
{
    int th = sceKernelCreateThread("loader", main_thread, 0x1F, 0x4000, 0, 0);
    if (th >= 0) {
        sceKernelStartThread(th, args, argp);
    }
    return 0;
}

int module_stop(SceSize args, void *argp)
{
    (void)args;
    (void)argp;
    return 0;
}
