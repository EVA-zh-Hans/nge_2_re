#include "hook_write.h"
#include "transform.h"

void TextEncodingPatch_Install(u32 game_base)
{
    // Patch Code in FUN_08874180
    /**
     * if ((0x7f < uVar2) && ((uVar2 < 0xa0 || (0xdf < uVar2)))) {
          // Read the next byte
          bVar1 = *pbVar3;
          // Skip 2 bytes
          pbVar3 = param_2 + 2;
          // Now uVar2 is a 2 byte value
          uVar2 = (uint)bVar1 | uVar2 << 8;
        }

        Extend The Range uVar2 >= 0xa6 so that First Byte Range in [a6,de) Will Also Be Considered as two byte characters.
        Change Bytes at 0x8874260 to a600a62c
        // 2ca600a6
    */
    HookWrite_U32(HookWrite_GameAddr(game_base, 0x08874260), 0x2ca600a6);

    // Patch Code in FUN_08819d58
    /**
        bool FUN_08819d58(int param_1)
        {
        bool bVar1;

        bVar1 = false;
        if (0x80 < param_1) {
            bVar1 = true;
            if ((0x9f < param_1) && (bVar1 = false, 0xdf < param_1)) {
            bVar1 = param_1 < 0xfd;
            }
        }
        return bVar1;
        }
    */
    // Patch Here:
    //          a6 00 82 28
    // 08819d68 e0 00 82 28     slti       v0,a0,0xe0
    HookWrite_U32(HookWrite_GameAddr(game_base, 0x08819d68), 0x288200a6);
    HookWrite_Call(HookWrite_GameAddr(game_base, 0x088691b8), translate_code);
}
