#include "hook_write.h"
#include "scefttt.h"

void FontPatch_Install(u32 game_base)
{
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x08869040), sceFtttNewLib);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x088692f8), sceFtttOpen);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x08869310), sceFtttGetFontInfo);
}
