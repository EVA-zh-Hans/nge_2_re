#include "hook_write.h"
#include "psputil.h"

void SaveDataPatch_Install(u32 game_base)
{
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x0880b4e4), sceUtilitySavedataInitStartPatched);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x0880b6f0), sceUtilitySavedataInitStartPatched);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x0880baf8), sceUtilitySavedataInitStartPatched);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x0880bce0), sceUtilitySavedataInitStartPatched);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x0880d97c), sceUtilitySavedataInitStartPatched);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x0880e1d4), sceUtilitySavedataInitStartPatched);
}
