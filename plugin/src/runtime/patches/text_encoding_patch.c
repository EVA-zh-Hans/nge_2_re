#include "hook_write.h"
#include "transform.h"

void TextEncodingPatch_Install(u32 game_base)
{
    HookWrite_U32(HookWrite_GameAddr(game_base, 0x08874260), 0x2ca600a6);
    HookWrite_U32(HookWrite_GameAddr(game_base, 0x08819d68), 0x288200a6);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x088691b8), translate_code);
}
