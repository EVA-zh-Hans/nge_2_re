#include <string.h>
#include <pspkernel.h>
#include <pspsdk.h>

#include "hook_write.h"

#define MIPS_J_ADDRESS(x) (((u32)(x) & 0x0fffffffu) >> 2)
#define J_TO(x) (0x08000000u | MIPS_J_ADDRESS(x))
#define JAL_TO(x) (0x0c000000u | MIPS_J_ADDRESS(x))

u32 HookWrite_GameAddr(u32 game_base, u32 original_addr)
{
    return game_base + (original_addr - EVA2_STD_BASE);
}

void HookWrite_U32(u32 addr, u32 value)
{
    _sw(value, addr);
}

void HookWrite_Nop(u32 addr)
{
    HookWrite_U32(addr, 0);
}

void HookWrite_Jump(u32 addr, const void *target)
{
    HookWrite_U32(addr, J_TO((u32)target));
}

void HookWrite_Call(u32 addr, const void *target)
{
    HookWrite_U32(addr, JAL_TO((u32)target));
}

void HookWrite_Copy(u32 addr, const void *src, size_t size)
{
    memcpy((void *)addr, src, size);
}

void HookWrite_FlushCaches(void)
{
    sceKernelDcacheWritebackAll();
    sceKernelIcacheInvalidateAll();
}
