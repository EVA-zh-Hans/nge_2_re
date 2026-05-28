#include <pspsdk.h>
#include <stdarg.h>
#include <pspkernel.h>
#include <pspthreadman.h>
#include <pspmodulemgr.h>
#include <pspiofilemgr.h>

#include <pspgu.h>
#include <pspdisplay.h>

#include <pspctrl.h>

#include "patcher.h"
#include "ui_atlas.h"
#include "image_display.h"

PSP_MODULE_INFO("EBOOT_LOADER", PSP_MODULE_USER, 1, 1);
PSP_NO_CREATE_MAIN_THREAD();

#define BUFFER_WIDTH 512
#define BUFFER_HEIGHT 272
#define SCREEN_WIDTH 480
#define SCREEN_HEIGHT BUFFER_HEIGHT

char list[0x20000] __attribute__((aligned(64)));

void initGu(){
    sceGuInit();

    //Set up buffers
    sceGuStart(GU_DIRECT, list);
    sceGuDrawBuffer(GU_PSM_8888,(void*)0,BUFFER_WIDTH);
    sceGuDispBuffer(SCREEN_WIDTH,SCREEN_HEIGHT,(void*)0x88000,BUFFER_WIDTH);
    sceGuDepthBuffer((void*)0x110000,BUFFER_WIDTH);

    //Set up viewport
    sceGuOffset(2048 - (SCREEN_WIDTH / 2), 2048 - (SCREEN_HEIGHT / 2));
    sceGuViewport(2048, 2048, SCREEN_WIDTH, SCREEN_HEIGHT);
    sceGuEnable(GU_SCISSOR_TEST);
    sceGuScissor(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT);

    //Set some stuff
    sceGuDepthRange(65535, 0); //Use the full buffer for depth testing - buffer is reversed order

    sceGuDepthFunc(GU_GEQUAL); //Depth buffer is reversed, so GEQUAL instead of LEQUAL
    sceGuEnable(GU_DEPTH_TEST); //Enable depth testing

    sceGuFinish();
    sceGuDisplay(GU_TRUE);
}

void endGu(){
    sceGuDisplay(GU_FALSE);
    sceGuTerm();
}

void startFrame(){
    sceGuStart(GU_DIRECT, list);
    sceGuClearColor(0xFF000000); // White background
    sceGuClear(GU_COLOR_BUFFER_BIT);
}

void endFrame(){
    sceGuFinish();
    sceGuSync(0, 0);
    sceDisplayWaitVblankStart();
    sceGuSwapBuffers();
}

typedef struct {
    unsigned short u, v;
    short x, y, z;
} Vertex;

void drawRect(float x, float y, float w, float h) {

    Vertex* vertices = (Vertex*)sceGuGetMemory(2 * sizeof(Vertex));

    vertices[0].x = x;
    vertices[0].y = y;

    vertices[1].x = x + w;
    vertices[1].y = y + h;

    sceGuDisable(GU_TEXTURE_2D); // 确保纹理被禁用
    sceGuColor(0xFF0000FF); // Red, colors are ABGR
    sceGuDrawArray(GU_SPRITES, GU_TEXTURE_16BIT | GU_VERTEX_16BIT | GU_TRANSFORM_2D, 2, 0, vertices);
	sceGuEnable(GU_TEXTURE_2D); // 重新启用纹理
}


#define PathOldBoot "disc0:/PSP_GAME/SYSDIR/BOOT.BIN"

int selected_index = 0;
int last_pad_buttons = 0;

SceCtrlData pad;

static int enable_pulse_autowin = 0;
static int enable_daily_debug = 0;
static int enable_battle_debug = 0;

void handleInput() {
    sceCtrlPeekBufferPositive(&pad, 1);
    
    // 只在按键刚刚按下时触发（从 0 变为 1）
    int pressed_buttons = pad.Buttons & ~last_pad_buttons;
    last_pad_buttons = pad.Buttons;

    if (pressed_buttons & PSP_CTRL_UP) {
        selected_index--;
        if (selected_index < 0) selected_index = 2;
    }
    if (pressed_buttons & PSP_CTRL_DOWN) {
        selected_index++;
        if (selected_index > 2) selected_index = 0;
    }
    
    // 切换功能开关
    if (pressed_buttons & PSP_CTRL_CIRCLE) {
        if (selected_index == 0) enable_pulse_autowin = !enable_pulse_autowin;
        if (selected_index == 1) enable_battle_debug = !enable_battle_debug;
        if (selected_index == 2) enable_daily_debug = !enable_daily_debug;
    }
}

static int main_thread(SceSize args, void *argp)
{

	initGu();
	
	while(1) {	
        handleInput(); // 处理按键逻辑
        
		startFrame();
		{
            // TODO: Draw Logo
            // drawRect(100.0f, 100.0f, 280.0f, 72.0f);

            // Render Menu
            uint32_t color = (selected_index == 0) ? 0xFF00FFFF : 0xFFFFFFFF;
            uiPrint(110, 110, "自动跳过脉冲", color);
            uiPrint(250, 110, enable_pulse_autowin ? "[ON]" : "[OFF]", color);
            
            uiPrint(110, 135, "启用战斗调试菜单", (selected_index == 1) ? 0xFF00FFFF : 0xFFFFFFFF);
            uiPrint(250, 135, enable_battle_debug ? "[ON]" : "[OFF]", (selected_index == 1) ? 0xFF00FFFF : 0xFFFFFFFF);

            uiPrint(110, 160, "启用日常调试菜单", (selected_index == 2) ? 0xFF00FFFF : 0xFFFFFFFF);
            uiPrint(250, 160, enable_daily_debug ? "[ON]" : "[OFF]", (selected_index == 2) ? 0xFF00FFFF : 0xFFFFFFFF);
            
            uiPrint(150, 200, "按 START 键启动游戏", 0xFF00AAFF);

            uiPrint(150, 220, "EVA2 汉化计划 2026", 0xFF00AAFF);
            uiPrint(150, 235, "插件制作：main_void", 0xFF00AAFF);
        }
		endFrame();

        if (pad.Buttons & PSP_CTRL_START) break;
	}
	
	// Display contributors image for 3 seconds
	displayImageFromFile("disc0:/PSP_GAME/USRDIR/metadata.raw", 480, 272, 5000);
	
	// Clean up GU after displaying image
	endGu();

	SceUID eboot_mid = sceKernelLoadModule(PathOldBoot, 0, NULL);
	if (eboot_mid >= 0)
	{
		sceKernelStartModule(eboot_mid, 0, NULL, NULL, NULL);
	}

	sceKernelDelayThread(1000);
	
	// USER_MAIN Thread Will Only Last for a fraction of second.
	SceKernelModuleInfo info;
	sceKernelQueryModuleInfo(eboot_mid, &info);
	u32 base_addr = info.segmentaddr[0];

	patch(base_addr);

    if (enable_pulse_autowin) {
        patchPulseAutowin();
    }

    if (enable_battle_debug) {
        patchBattleDebugMenu();
    }

    if (enable_daily_debug) {
        patchDailyDebugMenu();
    }

	return sceKernelExitDeleteThread(0);
}

int module_start(SceSize args, void *argp)
{
	int th = sceKernelCreateThread("loader", main_thread, 0x1F, 0x1000, 0, 0);
	if (th >= 0)
	{
		sceKernelStartThread(th, args, argp);
	}
	return 0;
}

int module_stop(SceSize args, void *argp)
{
	return 0;
}