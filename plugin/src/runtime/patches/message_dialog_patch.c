#include "hook_write.h"

void MessageDialogPatch_Install(u32 game_base)
{
    HookWrite_U32(HookWrite_GameAddr(game_base, 0x0880d024), 0x2403000b);
    HookWrite_U32(HookWrite_GameAddr(game_base, 0x0880d02c), 0xae230004);
}
