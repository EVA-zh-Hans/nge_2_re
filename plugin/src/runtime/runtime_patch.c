#include <pspkernel.h>

#include "hook_write.h"
#include "runtime_args.h"
#include "runtime_patch.h"
#include "staff_roll_log.h"

void TextEncodingPatch_Install(u32 game_base);
void SentencePatch_Install(u32 game_base);
int ExternalTranslationPatch_Apply(u32 game_base, const char *filename);
void FontPatch_Install(u32 game_base);
void SaveDataPatch_Install(u32 game_base);
void MessageDialogPatch_Install(u32 game_base);
void DebugPatch_Install(u32 game_base, u32 flags);
void MemTalkPatch_Install(u32 game_base);
void StaffRollPatch_Install(u32 game_base);

void RuntimePatch_InstallAll(u32 game_base, u32 flags)
{
    StaffRollLog_Printf("runtime install all begin base=%08x flags=%08x", game_base, flags);
    TextEncodingPatch_Install(game_base);
    SentencePatch_Install(game_base);
    SaveDataPatch_Install(game_base);
    MessageDialogPatch_Install(game_base);
    FontPatch_Install(game_base);
    MemTalkPatch_Install(game_base);
    StaffRollPatch_Install(game_base);
    DebugPatch_Install(game_base, flags);

    HookWrite_FlushCaches();
    StaffRollLog_Printf("runtime install all end");
}
