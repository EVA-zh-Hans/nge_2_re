#include <pspkernel.h>

#include "hook_write.h"
#include "runtime_args.h"
#include "runtime_patch.h"
#include "runtime_log.h"

void TextEncodingPatch_Install(u32 game_base);
void SentencePatch_Install(u32 game_base);
int ExternalTranslationPatch_Apply(u32 game_base, const char *filename);
void FontPatch_Install(u32 game_base);
void SaveDataPatch_Install(u32 game_base);
void MessageDialogPatch_Install(u32 game_base);
void DebugPatch_Install(u32 game_base, u32 flags);
void FrameRatePatch_Install(u32 game_base);
void MemTalkPatch_Install(u32 game_base);
void StaffRollPatch_Install(u32 game_base);

#define EXTERNAL_TRANSLATION_PATH "disc0:/PSP_GAME/USRDIR/EBTRANS.BIN"

void RuntimePatch_InstallAll(u32 game_base, u32 flags)
{
    if (flags & EVA2_FLAG_60_FPS) {
        FrameRatePatch_Install(game_base);
    }

    TextEncodingPatch_Install(game_base); // Encoding Range Patch
    SentencePatch_Install(game_base); // UTF-8 Sentence Patch
    ExternalTranslationPatch_Apply(game_base, EXTERNAL_TRANSLATION_PATH); // External Translation Patch
    
    SaveDataPatch_Install(game_base); // Save Data Simplified Chinese Patch
    MessageDialogPatch_Install(game_base); // Message Dialog Simplified Chinese Patch
    FontPatch_Install(game_base); // sceFont Patch

    MemTalkPatch_Install(game_base);
    StaffRollPatch_Install(game_base);

    DebugPatch_Install(game_base, flags); // Debug Menu Patch

    HookWrite_FlushCaches();
    RuntimeLog_Printf("runtime install all end");
}
