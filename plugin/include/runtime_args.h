#pragma once

#include <pspkerneltypes.h>
#include <psptypes.h>

#define EVA2_FLAG_PULSE_AUTOWIN (1u << 0)
#define EVA2_FLAG_BATTLE_DEBUG (1u << 1)
#define EVA2_FLAG_DAILY_DEBUG (1u << 2)

typedef struct Eva2RuntimeStartArgs {
    SceUID boot_mid;
    u32 flags;
} Eva2RuntimeStartArgs;
