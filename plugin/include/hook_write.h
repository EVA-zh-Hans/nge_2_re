#pragma once

#include <stddef.h>
#include <stdint.h>
#include <psptypes.h>

#define EVA2_STD_BASE 0x08804000u

u32 HookWrite_GameAddr(u32 game_base, u32 original_addr);
void HookWrite_U32(u32 addr, u32 value);
void HookWrite_Nop(u32 addr);
void HookWrite_Jump(u32 addr, const void *target);
void HookWrite_Call(u32 addr, const void *target);
void HookWrite_Copy(u32 addr, const void *src, size_t size);
void HookWrite_FlushCaches(void);
