#include "hook_write.h"
#include "runtime_args.h"

static void DebugPatch_PulseAutowin(u32 game_base)
{
    HookWrite_Nop(HookWrite_GameAddr(game_base, 0x0885b478));
    HookWrite_Nop(HookWrite_GameAddr(game_base, 0x0885b5fc));
    HookWrite_Nop(HookWrite_GameAddr(game_base, 0x0885b5c4));
}

static void DebugPatch_BattleDebugMenu(u32 game_base)
{
    HookWrite_U32(HookWrite_GameAddr(game_base, 0x08b57e04), 0x01);
}

static void DebugPatch_DailyDebugMenu(u32 game_base)
{
    HookWrite_U32(
        HookWrite_GameAddr(game_base, 0x089c97cc),
        HookWrite_GameAddr(game_base, 0x088984c0));
}

void DebugPatch_Install(u32 game_base, u32 flags)
{
    if (flags & EVA2_FLAG_PULSE_AUTOWIN) {
        DebugPatch_PulseAutowin(game_base);
    }
    if (flags & EVA2_FLAG_BATTLE_DEBUG) {
        DebugPatch_BattleDebugMenu(game_base);
    }
    if (flags & EVA2_FLAG_DAILY_DEBUG) {
        DebugPatch_DailyDebugMenu(game_base);
    }
}
