#include <pspkernel.h>
#include <pspsdk.h>

#include "hook_write.h"
#include "runtime_args.h"
#include "runtime_patch.h"

void TextEncodingPatch_Install(u32 game_base);
void SentencePatch_Install(u32 game_base);
int ExternalTranslationPatch_Apply(u32 game_base, const char *filename);
void FontPatch_Install(u32 game_base);
void SaveDataPatch_Install(u32 game_base);
void MessageDialogPatch_Install(u32 game_base);
void DebugPatch_Install(u32 game_base, u32 flags);
void MemTalkPatch_Install(u32 game_base);

void RuntimePatch_InstallAll(u32 game_base, u32 flags)
{
    (void)ExternalTranslationPatch_Apply(game_base, "disc0:/PSP_GAME/USRDIR/EBTRANS.BIN");

    u32 state = pspSdkDisableInterrupts();

    TextEncodingPatch_Install(game_base);
    SentencePatch_Install(game_base);
    SaveDataPatch_Install(game_base);
    MessageDialogPatch_Install(game_base);
    FontPatch_Install(game_base);
    MemTalkPatch_Install(game_base);
    DebugPatch_Install(game_base, flags);

    HookWrite_FlushCaches();
    pspSdkEnableInterrupts(state);
}
