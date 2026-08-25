#include "hook_write.h"

#define FRAME_RATE_ADDR_SET_MODE_BRANCH 0x08819B5Cu
#define FRAME_RATE_ADDR_SET_MODE_STORE 0x08819B60u
#define FRAME_RATE_ADDR_LIMIT_BRANCH 0x08804594u
#define FRAME_RATE_ADDR_TARGET_MODE 0x08AFB8E0u
#define FRAME_RATE_ADDR_TIME_STEP 0x089EA26Cu

#define FRAME_RATE_ADDR_ANIMATION_STEP 0x0887B514u
#define FRAME_RATE_ADDR_BLEND_FRAMES_1 0x0887B28Cu
#define FRAME_RATE_ADDR_BLEND_FRAMES_2 0x0887BD9Cu
#define FRAME_RATE_ADDR_BLEND_FRAMES_3 0x0887BFA4u

#define MIPS_BEQ_ALWAYS_7 0x10000007u
#define MIPS_SW_ZERO_TARGET_MODE 0xAC60B8E0u
#define MIPS_SLL_V1_A1_4 0x00091900u
#define MIPS_SLL_S3_A2_1 0x00069840u
#define FLOAT_4096_BITS 0x45800000u

void FrameRatePatch_Install(u32 game_base)
{
    /* Force SetFrameRateMode to store mode 0 and select its 60 Hz path. */
    HookWrite_U32(
        HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_SET_MODE_BRANCH),
        MIPS_BEQ_ALWAYS_7);
    HookWrite_U32(
        HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_SET_MODE_STORE),
        MIPS_SW_ZERO_TARGET_MODE);

    /* The runtime is installed before the game starts, so initialize both values now. */
    HookWrite_U32(HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_TARGET_MODE), 0u);
    HookWrite_U32(
        HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_TIME_STEP),
        FLOAT_4096_BITS);

    /* Skip the optional second VBlank wait used by the 30 FPS mode. */
    HookWrite_Nop(HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_LIMIT_BRANCH));

    /* Advance HGMN animation time by 16 units instead of 32 per refresh. */
    HookWrite_U32(
        HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_ANIMATION_STEP),
        MIPS_SLL_V1_A1_4);

    /* Preserve blend timing by doubling the frame-count argument in all three paths. */
    HookWrite_U32(
        HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_BLEND_FRAMES_1),
        MIPS_SLL_S3_A2_1);
    HookWrite_U32(
        HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_BLEND_FRAMES_2),
        MIPS_SLL_S3_A2_1);
    HookWrite_U32(
        HookWrite_GameAddr(game_base, FRAME_RATE_ADDR_BLEND_FRAMES_3),
        MIPS_SLL_S3_A2_1);
}
