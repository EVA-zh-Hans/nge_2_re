#include <pspsdk.h>
#include <pspkernel.h>
#include <psptypes.h>

#include "patcher.h"

// Utils
#include "utils.h"
#include "log.h"

// PSP SDK Patch
#include "scefttt.h"
#include "psputil.h"

// Custom Patch
#include "fs.h"
#include "transform.h"

/**
 * The full 32-bit jump address is formed by concatenating
 * the high order 4 bits of the program counter,
 * 26 bits of the target
 * and two 0 bits
 *
 * The coded address is formed from the bits at positions 27 to 2
 */
#define MIPS_J_ADDRESS(x) (((u32)((x)) & 0x3fffffff) >> 2)

#define NOP 0x000C0000
#define JAL_TO(x) (0x0E000000 | MIPS_J_ADDRESS(x))
#define J_TO(x) (0x08000000 | MIPS_J_ADDRESS(x))
#define LUI(x, y) (0x3C000000 | ((x & 0x1f) << 0x10) | (y & 0xffff))

// Codes to Patch
#define BIN_COND_INST_OPERAND_ADDR 0x08874260
// 088691b8 a0 11 22 0e     jal FUN_08884680
#define JAL_INST_ADDR 0x088691b8
#define EVS_COND_INST_OPERAND_ADDR 0x08819d68

// The Default Load Position for USER_MAIN Module.
// The Addresses above is based on this address.
#define STD_BASE 0x08804000

u32 offset_;

#define NEW_ADDR(x) ((u32)x + offset_)

void pulse_autowin()
{
    const u32 ADDR_1 = 0x885b478;
    const u32 ADDR_2 = 0x885b5fc;
    // const u32 ADDR_3 = 0x885b5cc;
    const u32 ADDR_4 = 0x885b5c4;
    u32 state = pspSdkDisableInterrupts();
    {
        _sw(0x00000000, NEW_ADDR(ADDR_1));
        _sw(0x00000000, NEW_ADDR(ADDR_2));
        // _sw(0x0a216d82, NEW_ADDR(ADDR_3));
        _sw(0x00000000, NEW_ADDR(ADDR_4));
        sceKernelDcacheWritebackAll();
        sceKernelIcacheInvalidateAll();
    }
    pspSdkEnableInterrupts(state);
}

void patch(u32 mod_base)
{
    offset_ = mod_base - 0x08804000;
    patch_function();
    patch_sentence();

    patch_from_external_file("disc0:/PSP_GAME/USRDIR/EBTRANS.BIN");
};

void patchPulseAutowin() {
    pulse_autowin();
}

void patchBattleDebugMenu() {
    u32 state = pspSdkDisableInterrupts();
    {
        // Battle Debug
        *(u32 *)NEW_ADDR(0x08b57e04) = 0x01;
        
        sceKernelDcacheWritebackAll();
        sceKernelIcacheInvalidateAll();
    }
    pspSdkEnableInterrupts(state);
}

void patchDailyDebugMenu() {
    u32 state = pspSdkDisableInterrupts();
    {
        // Daily Special Debug
        *(u32 *)NEW_ADDR(0x89C97CC) = NEW_ADDR(0x088984C0);
                
        sceKernelDcacheWritebackAll();
        sceKernelIcacheInvalidateAll();
    }
    pspSdkEnableInterrupts(state);
}

void patch_function()
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
    {
        // Dump the Original Code
        u32 code_pos = BIN_COND_INST_OPERAND_ADDR + offset_;
        dbg_log("Original Code at %x\n", code_pos);
        dbg_log("Original Code: %x\n", *(uint32_t *)code_pos);

        // Patch The Code
        u32 state = pspSdkDisableInterrupts();
        { // SJIS Sentece中字符均是大端
            _sw(0x2ca600a6, (u32)code_pos);
            sceKernelDcacheWritebackAll();
            sceKernelIcacheInvalidateAll();
        }
        pspSdkEnableInterrupts(state);

        // Dump the Patched Code
        dbg_log("Patched Code at %x\n", code_pos);
        dbg_log("Patched Code: %x\n", *(uint32_t *)code_pos);
    }

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
    {
        // Dump the Original Code
        u32 code_pos = EVS_COND_INST_OPERAND_ADDR + offset_;
        dbg_log("Original Code at %x\n", code_pos);
        dbg_log("Original Code: %x\n", *(uint32_t *)code_pos);

        // Patch The Code
        u32 state = pspSdkDisableInterrupts();
        { // SJIS Sentece中字符均是大端
            _sw(0x288200a6, (u32)code_pos);
            sceKernelDcacheWritebackAll();
            sceKernelIcacheInvalidateAll();
        }
        pspSdkEnableInterrupts(state);

        // Dump the Patched Code
        dbg_log("Patched Code at %x\n", code_pos);
        dbg_log("Patched Code: %x\n", *(uint32_t *)code_pos);
    }

    /* Hook The Funtion Calls */
    // Generate the JAL Instruction
    {
        // Dump the Original Code
        u32 code_pos = JAL_INST_ADDR + offset_;

        dbg_log("Original Code at %x\n", code_pos);
        dbg_log("Original Code: %x\n", *(uint32_t *)code_pos);

        // Patch The JAL Instruction
        // The Original Code is for converting Non-ASCII SJIS Characters to UTF16
        // Now we extend the range to include More Chinese Characters
        uint32_t jal_inst = JAL_TO(translate_code);
        u32 state = pspSdkDisableInterrupts();
        {
            _sw(jal_inst, (u32)code_pos);
            sceKernelDcacheWritebackAll();
            sceKernelIcacheInvalidateAll();
        }
        pspSdkEnableInterrupts(state);

        // Dump the Patched Code
        dbg_log("Patched Code at %x\n", code_pos);
        dbg_log("Patched Code: %x\n", *(uint32_t *)code_pos);
    }

    // Patch all the sceUtilitySavedataInitStart call
    /**
                             **************************************************************
                             *                          FUNCTION                          *
                             **************************************************************
                             int __stdcall sceUtilitySavedataInitStart(SceUtilitySave
             int               v0:4           <RETURN>
             SceUtilitySave    a0:4           params
                             sceUtilitySavedataInitStart                     XREF[6]:     FUN_0880b3a0:0880b4e4(c), 
                                                                                          FUN_0880b5f4:0880b6f0(c), 
                                                                                          FUN_0880b7d4:0880baf8(c), 
                                                                                          FUN_0880bc84:0880bce0(c), 
                                                                                          FUN_0880d6ac:0880d97c(c), 
                                                                                          FUN_0880e058:0880e1d4(c)  
        089b2c80 08 00 e0 03     jr         ra
        089b2c84 00 00 00 00     _nop
    */
    {
        u32 state = pspSdkDisableInterrupts();
        {
            // jal sceUtilitySavedataInitStartPatched
            _sw(JAL_TO(sceUtilitySavedataInitStartPatched), NEW_ADDR(0x0880b4e4));
            _sw(JAL_TO(sceUtilitySavedataInitStartPatched), NEW_ADDR(0x0880b6f0));
            _sw(JAL_TO(sceUtilitySavedataInitStartPatched), NEW_ADDR(0x0880baf8));
            _sw(JAL_TO(sceUtilitySavedataInitStartPatched), NEW_ADDR(0x0880bce0));
            _sw(JAL_TO(sceUtilitySavedataInitStartPatched), NEW_ADDR(0x0880d97c));
            _sw(JAL_TO(sceUtilitySavedataInitStartPatched), NEW_ADDR(0x0880e1d4));
            sceKernelDcacheWritebackAll();
            sceKernelIcacheInvalidateAll();
        }
        pspSdkEnableInterrupts(state);
    }

    /* Message Dialog Utility */
    {
        u32 state = pspSdkDisableInterrupts();
        {
            // li v1, 0x0b
            _sw(0x2403000b, NEW_ADDR(0x0880d024));
            // sw v1, 4(s1)
            _sw(0xae230004, NEW_ADDR(0x0880d02c));
            sceKernelDcacheWritebackAll();
            sceKernelIcacheInvalidateAll();
        }
        pspSdkEnableInterrupts(state);
    }

    /* sceFont Patch */
    {
        u32 state = pspSdkDisableInterrupts();
        {
            // jal sceFtttNewLib
            _sw(JAL_TO(sceFtttNewLib), NEW_ADDR(0x08869040));
            // jal sceFtttOpen
            _sw(JAL_TO(sceFtttOpen), NEW_ADDR(0x088692f8));
            // jal sceFtttGetFontInfo
            _sw(JAL_TO(sceFtttGetFontInfo), NEW_ADDR(0x08869310));
            sceKernelDcacheWritebackAll();
            sceKernelIcacheInvalidateAll();
        }
        pspSdkEnableInterrupts(state);
    }

    /* Filesystem Patch */
    {
        u32 state = pspSdkDisableInterrupts();
        {
            // jal init_file_handle_with_lbn_path
            _sw(JAL_TO(init_file_handle_with_lbn_path), NEW_ADDR(0x8986f34)); // engineIoOpen
            _sw(JAL_TO(init_file_handle_with_lbn_path), NEW_ADDR(0x8986ffc)); // engineIoOpenAync

            // 089873E4                 jal     path_to_lbn
            _sw(JAL_TO(path_to_lbn), NEW_ADDR(0x089873e4));
            sceKernelDcacheWritebackAll();
            sceKernelIcacheInvalidateAll();
        }
        pspSdkEnableInterrupts(state);
    }
}

// TODO: Patch Using External JSON File
void patch_sentence()
{
    // Patch UTF-8 Sentences
    strcpy((char *)NEW_ADDR(0x089b4a94), "碇真嗣");
    strcpy((char *)NEW_ADDR(0x089b4aa4), "惣流・明日香・兰格雷");
    strcpy((char *)NEW_ADDR(0x089b4acc), "绫波丽");
    strcpy((char *)NEW_ADDR(0x089b4adc), "葛城美里");
    strcpy((char *)NEW_ADDR(0x089b4aec), "碇源堂");
    strcpy((char *)NEW_ADDR(0x089b4afc), "冬月耕造");
    strcpy((char *)NEW_ADDR(0x089b4b10), "赤木律子");
    strcpy((char *)NEW_ADDR(0x089b4b20), "伊吹摩耶");
    strcpy((char *)NEW_ADDR(0x089b4b30), "日向诚");
    strcpy((char *)NEW_ADDR(0x089b4b40), "青叶茂");
    strcpy((char *)NEW_ADDR(0x089b4b50), "加持良治");
    strcpy((char *)NEW_ADDR(0x089b4b64), "洞木光");
    strcpy((char *)NEW_ADDR(0x089b4b74), "铃原冬二");
    strcpy((char *)NEW_ADDR(0x089b4b84), "相田剑介");
    strcpy((char *)NEW_ADDR(0x089b4b98), "渚薰");
    strcpy((char *)NEW_ADDR(0x089b4ba8), "Pen Pen");
    strcpy((char *)NEW_ADDR(0x089b4bb8), "使徒、袭来");
    strcpy((char *)NEW_ADDR(0x089b4bc8), "但是、我爱这个世界");
    strcpy((char *)NEW_ADDR(0x089b4be8), "丽、心的彼方");
    strcpy((char *)NEW_ADDR(0x089b4c04), "亲吻脆弱的地方");
    strcpy((char *)NEW_ADDR(0x089b4c28), "女人的战斗");
    strcpy((char *)NEW_ADDR(0x089b4c38), "人类补完计划");
    strcpy((char *)NEW_ADDR(0x089b4c4c), "未完成的白日梦");
    strcpy((char *)NEW_ADDR(0x089b4c64), "女人如火");
    strcpy((char *)NEW_ADDR(0x089b4c70), "花样年华");
    strcpy((char *)NEW_ADDR(0x089b4c80), "暧昧的天空");
    strcpy((char *)NEW_ADDR(0x089b4c90), "Cobalt Sky");
    strcpy((char *)NEW_ADDR(0x089b4ca8), "VS．SEELE");
    strcpy((char *)NEW_ADDR(0x089b4cbc), "心中的一切");
    strcpy((char *)NEW_ADDR(0x089b4cd8), "从梦中醒来");
    strcpy((char *)NEW_ADDR(0x089b4cf0), "看见春天的人");
    strcpy((char *)NEW_ADDR(0x089b4d04), "折断的翅膀");
    strcpy((char *)NEW_ADDR(0x089b4d14), "人手难及");
    strcpy((char *)NEW_ADDR(0x089b4d3c), "「芝村」平衡");
    strcpy((char *)NEW_ADDR(0x089b4da0), "日目");
    strcpy((char *)NEW_ADDR(0x089b4da8), "结束");
    strcpy((char *)NEW_ADDR(0x089b4db0), "剧情通关文件");
    strcpy((char *)NEW_ADDR(0x089b4dd4), "开放剧情数");
    strcpy((char *)NEW_ADDR(0x089b4df0), "完成剧情数");
    strcpy((char *)NEW_ADDR(0x089b4d64), "零");
    strcpy((char *)NEW_ADDR(0x089b4d68), "一");
    strcpy((char *)NEW_ADDR(0x089b4d6c), "二");
    strcpy((char *)NEW_ADDR(0x089b4d70), "三");
    strcpy((char *)NEW_ADDR(0x089b4d74), "四");
    strcpy((char *)NEW_ADDR(0x089b4d78), "五");
    strcpy((char *)NEW_ADDR(0x089b4d7c), "六");
    strcpy((char *)NEW_ADDR(0x089b4d80), "七");
    strcpy((char *)NEW_ADDR(0x089b4d84), "八");
    strcpy((char *)NEW_ADDR(0x089b4d88), "九");
    strcpy((char *)NEW_ADDR(0x089b4d8c), "十");
    strcpy((char *)NEW_ADDR(0x089b4d90), "第");
    strcpy((char *)NEW_ADDR(0x089b4d94), "话");
    strcpy((char *)NEW_ADDR(0x089b4d98), "「");
    strcpy((char *)NEW_ADDR(0x089b4d9c), "」");
    strcpy((char *)NEW_ADDR(0x089b51c4), "AM");
    strcpy((char *)NEW_ADDR(0x089b51c8), "PM");
    strcpy((char *)NEW_ADDR(0x089b4e14), "加载完成。");
    strcpy((char *)NEW_ADDR(0x089b4e38), "保存完成。");
    strcpy((char *)NEW_ADDR(0x089b4e5c), "Memory Stick™空闲容量不足。\n\n");
    strcpy((char *)NEW_ADDR(0x089b4ea8), "本标题还需要\n");
    strcpy((char *)NEW_ADDR(0x089b4ecc), "游戏数据(");
    strcpy((char *)NEW_ADDR(0x089b4ee0), "KB)和\n");
    strcpy((char *)NEW_ADDR(0x089b4ee8), "剧情通关数据(");
    strcpy((char *)NEW_ADDR(0x089b4f08), "KB)的\n");
    strcpy((char *)NEW_ADDR(0x089b4f10), "空闲容量。\n\n");
    strcpy((char *)NEW_ADDR(0x089b4f3c), "是否删除其他游戏数据？");
    strcpy((char *)NEW_ADDR(0x089b4f74), "是否继续游戏？");
    strcpy((char *)NEW_ADDR(0x089b4f98), "是否中止保存？");
    strcpy((char *)NEW_ADDR(0x089b4fbc), "未找到Memory Stick™。\n\n");
    strcpy((char *)NEW_ADDR(0x089b4ff8), "本标题需要保存游戏数据(");
    strcpy((char *)NEW_ADDR(0x089b5024), "KB)的\n");
    strcpy((char *)NEW_ADDR(0x089b502c), "空闲容量。\n\n");
    strcpy((char *)NEW_ADDR(0x089b5070), "中止保存，继续游戏吗？");
    strcpy((char *)NEW_ADDR(0x089b50ac), "无法访问Memory Stick™。\n\n");
    strcpy((char *)NEW_ADDR(0x089b50f4), "无法保存到Memory Stick™。\n\n是否删除其他游戏数据后再次保存？");
    strcpy((char *)NEW_ADDR(0x089ea084), "新世纪福音战士２　被创造的世界");
    strcpy((char *)NEW_ADDR(0x089ea0c4), "空闲存档槽");
    strcpy((char *)NEW_ADDR(0x089ea0d8), "Memory Stick™尚未完成加载。\n\n是否停止加载，继续游戏？");
};

typedef struct TranslationHeader {
    u32 num;
} TranslationHeader;

typedef struct TranslationEntry {
    u32 offset;
    u32 size;
    u8 buffer[1024];
} TranslationEntry;

/**
* Patch SJIS Content in EBOOT bin using Entries Generated.
*/
int patch_from_external_file(const char* filename) {
    int err;

    static TranslationHeader header;
    static TranslationEntry entry;


    SceUID fd = sceIoOpen(filename, PSP_O_RDONLY, 0777);

    dbg_log("fd: %d\n", fd);
    
    err = sceIoRead(fd, &header.num, sizeof(u32));
    if(err < 0) {
        return err;
    }

    dbg_log("Header Num: %d\n", header.num);
    
    for(int i=0;i<header.num;++i) {
        err = sceIoRead(fd, &entry.offset, sizeof(u32));
        if (err < 0) {
            return err;
        }
        
        err = sceIoRead(fd, &entry.size,sizeof(u32));
        if (err < 0) {
            return err;
        }
        
        err = sceIoRead(fd, &entry.buffer, 1024);
        if (err < 0) {
            return err;
        }

        dbg_log("Offset: %x, Buffer: %x, Size: %d\n", entry.offset, entry.buffer, entry.size);
        // Patch the BIN.
        // TODO: Use memcpy instead of strcpy to avoid the Null Terminator Problem.
        strcpyn((char *)NEW_ADDR(entry.offset), entry.buffer, entry.size);
    }

    err = sceIoClose(fd);

    return err;
}