# EBOOT Loader

Load the game and patch it.

> TODO: Tried to sideload a plugin but failed somehow

## Usage

+ Replace the orginal `EBOOT.BIN` with the generated one.
+ Decrypt `EBOOT.BIN` and rename it to `BOOT.BIN`

> You can decrypt `EBOOT.BIN` using `PPSSPP`
> 1. 打开PPSSPP
> 2. `设置`->`工具`->`开发者工具`->`载入游戏时保存已解密的EBOOT.bin`
> 3. 进入游戏
> 4. 提示框会显示解密`EBOOT.bin`保存的地址

## Build Instruction

+ Generate EBOOT.BIN
```sh
make release
```

+ Generate EBOOT.BIN with Debug Log
```sh
make debug
```

> Debug Version will log under the `ms0:/PSP` directory, may not work on real mahine.

## Generated Assets

The plugin keeps generated C arrays in `src/bin/` so the PSP build does not
depend on re-running every asset conversion by hand. Regenerate them with:

```sh
make generate-assets
```

Generated from scripts:

+ `src/bin/gb2312.c` is generated from `scripts/gentable.py`.
+ `src/bin/atlas.c`, `src/bin/atlas_palette.c`, and `include/atlas_data.h` are
  generated from `scripts/gen_ttf_atlas.py`, `assets/fonts/ChillRoundFBold.ttf`,
  and `assets/ui_atlas_chars.txt`.

Stable extracted tables:

+ `src/bin/sjis.c` and `src/bin/utf16.c` are extracted from the original game
  and are treated as stable source assets unless the source game table changes.

To verify that checked-in generated files match the generators, run:

```sh
make check-generated
```

# Contributing

```
├── include
├── assets  # Font and text inputs for generated plugin assets
├── scripts # Generators for coding tables and UI atlas binaries
└── src
    ├── bin # Binaries converted to C arrays
    ├── loader # EBOOT Loader
    ├── runtime # Runtime patch registration and patch implementations
    └── utils # Log Util
```

+ `src/runtime/patches/` contains the active runtime patch implementations.
+ `src/loader/ui_draw.c` contains the loader UI renderer.
+ `transform.c` contains the translated text conversion functions.

## Basic Idea

在Shift-JIS（SJIS）编码中，多字节字符的首个字节范围如下：

1. **单字节字符**：
   - ASCII字符：0x00 - 0x7F
   - 半角片假名：0xA1 - 0xDF

2. **多字节字符的首个字节**：
   - 0x81 - 0x9F
   - 0xE0 - 0xFC

```
0x00------0x7f 0x81------0x9f 0xa1------0xdf 0xe0------0xfc
修改前：        |   双字节    |               |  双字节     |
修改后：        |   双字节    |       |  双字节             |
```

将游戏中不使用的半角片假名对应的区域用于编码GB2312中的汉字字符。

在 GB2312 编码中，多字节字符的首个字节范围如下：

+ **First Byte**: 0xA1-0xF7
+ **Second Byte**: 0xA1-0xFE

使用公式
```C
index = (first_byte - 0xA1) * 94 + (second_byte - 0xA1);
mapped_code = 0xA600 + index;
```

映射到`0xA600-0xDDFF`区域。


## SJIS Check for Binary

Decompiled Using [ghidra-allegrex](https://github.com/kotcrab/ghidra-allegrex).

```C
/** 
 * This function reads in bytes of encoded characters from char *param2
 * and call FUN_08873f14 for futher processing (Converting to UTF16, etc.)
 */
void FUN_08874180(undefined4 param_1,byte *param_2)
{
  byte bVar1;
  uint uVar2;
  byte *pbVar3;
  // Current Byte
  uVar2 = (uint)*param_2;
  do {
    // Next Byte
    pbVar3 = param_2 + 1;
    switch(uVar2) {
    case 0:
      return;
    default:
      if (uVar2 < 0x20) {
        // Current Byte
        uVar2 = (uint)*pbVar3;
        // Update Next Pos
        param_2 = pbVar3;
      }
      else {
        // 去除了半角片假名
        // 多字节字符的首个字节：0x80-0x9F 0xE0-0xFC
        // NOTE: Patch HERE!
        // ((0x7f < uVar2) && ((uVar2 < 0xa0 || (0xa6 <= uVar2))))
        if ((0x7f < uVar2) && ((uVar2 < 0xa0 || (0xdf < uVar2)))) {
          // Read the next byte
          bVar1 = *pbVar3;
          // Skip 2 bytes
          pbVar3 = param_2 + 2;
          // Now uVar2 is a 2 byte value
          uVar2 = (uint)bVar1 | uVar2 << 8;
        }
        // Param1 可能是一个指向Struct的指针
        FUN_08873f14(param_1,uVar2);
        // Update Curr Byte
        uVar2 = (uint)*pbVar3;
        // Update Next Pos
        param_2 = pbVar3;
      }
      break;
    case 10:
      FUN_08874648(param_1);
      // 修改结构体
      /**
      void FUN_08874648(int param_1)
      {
        int iVar1;
        
        iVar1 = *(int *)(param_1 + 0xe4);
        *(undefined2 *)(iVar1 + 8) = 0;
        *(short *)(iVar1 + 10) = *(short *)(iVar1 + 10) + *(short *)(iVar1 + 0x1e);
        return;
      }
      **/
      // Read Next Byte into uVar2
      uVar2 = (uint)*pbVar3;
      // Update Next Pos
      param_2 = pbVar3;
      break;
    case 0x10:
      FUN_08874664(param_1);

      uVar2 = (uint)*pbVar3;
      param_2 = pbVar3;
      break;
    case 0x14:
      // Next Byte
      pbVar3 = (byte *)FUN_0881204c(*pbVar3);
      /*
      int FUN_0881204c(int param_1)
      {
        return param_1 * 4 + 0x89ea208;
      }
      */
      // 返回了一个地址
      // 在该地址取出u32
      FUN_08874944(param_1,(uint)pbVar3[3] << 0x18 | (uint)pbVar3[2] << 0x10 | (uint)pbVar3[1] << 8
                           | (uint)*pbVar3);
      // 使用该u32修改了param_1内部数据
      /**
      void FUN_08874944(int param_1,u32 param_2)
      {
        *(u32 *)(*(int *)(param_1 + 0xe4) + 0x14) = param_2;
        return;
      }
      */
      uVar2 = (uint)param_2[2];
      param_2 = param_2 + 2;
      break;
    case 0x16:
      // 取出next_byte
      FUN_08873d5c(param_1,*pbVar3);
      // 取出next next byte
      uVar2 = (uint)param_2[2];
      // param_2跳过两个
      param_2 = param_2 + 2;
    }
  } while( true );
}
```

## SJIS Conversion
```C
// uint16_t sjis_to_utf16(u16 sjis)
undefined2 FUN_08884680(uint param_1)
{
  undefined4 uVar1;
  undefined4 uVar2;
  uint uVar3;
  
  param_1 = param_1 & 0xffff;
  uVar1 = 0;
  uVar2 = 0x2d;
  if (DAT_08a33310 <= param_1) {
    uVar1 = 0x2e;
    uVar2 = 0x5a;
    if (param_1 <= DAT_08a33310) {
      uVar3 = 0x2d;
      goto LAB_088846d0;
    }
  }
  // Binary Search
  uVar3 = FUN_08884724(param_1,uVar1,uVar2);
  uVar3 = uVar3 & 0xffff;
LAB_088846d0:
  return *(undefined2 *)
          (&DAT_08a2fb60 +
          ((param_1 - *(ushort *)(&DAT_08a3325c + uVar3 * 4)) +
          (uint)*(ushort *)(&DAT_08a3325e + uVar3 * 4)) * 2);
}
```
## SJIS Check for EVS

0x8830b98调用0x8819d58判断几个字节，最后回到0x8814c14调用`FUN_08873f14`

```C
bool FUN_08819d58(int param_1)

{
  bool bVar1;
  
  bVar1 = false;
  if (0x80 < param_1) {
    bVar1 = true;
    // PATCH HERE:
    // ((0x9f < param_1) && (bVar1 = false, 0xa6 <= param_1))
    if ((0x9f < param_1) && (bVar1 = false, 0xdf < param_1)) {
      bVar1 = param_1 < 0xfd;
    }
  }
  return bVar1;
}
```

```C
undefined FUN_08819d58()
        08819d58 81 00 86 28     slti       a2,a0,0x81
        08819d5c a0 00 85 28     slti       a1,a0,0xa0
        08819d60 07 00 c0 14     bne        a2,zero,LAB_08819d80
        08819d64 21 18 00 00     _li        v1,0
        // Patch Here: 
        //       a6 00 82 28
        08819d68 e0 00 82 28     slti       v0,a0,0xe0
        08819d6c 01 00 03 24     li         v1,0x1
        08819d70 03 00 a0 14     bne        a1,zero,LAB_08819d80
        08819d74 fd 00 84 28     _slti      a0,a0,0xfd
        08819d78 21 18 00 00     li         v1,0
        08819d7c 0a 18 82 00     movz       v1,a0,v0
```

# 其他发现

## EVS Read
```C
void FUN_0882eed4(undefined4 param_1,undefined4 param_2,undefined4 param_3,undefined4 param_4,
                 char *param_5,int param_6)

{
  char *pcVar1;
  int iVar2;
  undefined4 uVar3;
  char cVar4;
  char *pcVar5;
  char *pcVar6;
  undefined4 uVar7;
  char local_230 [512];
  
  pcVar5 = local_230;
  if (DAT_08b01dfc != -1) {
    cVar4 = *param_5;
    uVar7 = param_1;
    while (cVar4 != '\0') {
      if (cVar4 == '$') {
        cVar4 = param_5[1];
        uVar3 = param_2;
        if (((cVar4 == 'a') || (uVar3 = param_3, cVar4 == 'b')) || (uVar3 = param_4, cVar4 == 'c'))
        {
          uVar3 = FUN_08839434(uVar7,uVar3);
          iVar2 = FUN_089a6090(pcVar5,uVar3);
          param_5 = param_5 + 2;
          pcVar5 = pcVar5 + iVar2;
        }
        else if (cVar4 == 'n') {
          *pcVar5 = '\0';
          // TODO!!!
          FUN_08830b98(local_230,param_6,1);
          iVar2 = FUN_088579ac(1);
          if ((iVar2 == 0) || (-1 < DAT_08b57e10)) {
            cVar4 = param_5[2];
          }
          else {
            do {
              // TODO!!!
              FUN_08830b98(local_230,param_6,1);
            } while (DAT_08b57e10 < 0);
            cVar4 = param_5[2];
          }
          pcVar5 = param_5 + 2;
          param_5 = param_5 + 3;
          if (cVar4 != '\n') {
            param_5 = pcVar5;
          }
          param_6 = param_6 + (uint)(0 < param_6);
          pcVar5 = local_230;
          uVar7 = param_1;
        }
        else {
          if (cVar4 != 'm') {
            cVar4 = *param_5;
            goto LAB_0882ef50;
          }
          *pcVar5 = '\0';
          FUN_08830b98(local_230,param_6,1);
          iVar2 = FUN_088579ac(1);
          if (iVar2 != 0) {
            while (DAT_08b57e10 < 0) {
              FUN_08830b98(local_230,param_6,1);
            }
          }
          param_6 = 0;
          if (DAT_08b01df4 != 0) {
            FUN_088148dc(DAT_08b01e00);
            FUN_08820d78(DAT_08b01e28);
            DAT_08b01e28 = 0xffffffff;
          }
          pcVar1 = param_5 + 2;
          pcVar6 = param_5 + 2;
          param_5 = param_5 + 3;
          pcVar5 = local_230;
          uVar7 = 0;
          if (*pcVar1 != '\n') {
            param_5 = pcVar6;
            pcVar5 = local_230;
          }
        }
      }
      else {
        cVar4 = *param_5;
LAB_0882ef50:
        *pcVar5 = cVar4;
        param_5 = param_5 + 1;
        pcVar5 = pcVar5 + 1;
      }
      cVar4 = *param_5;
    }
    *pcVar5 = '\0';
    FUN_08830b98(local_230,param_6,1);
    iVar2 = FUN_088579ac(1);
    if (iVar2 != 0) {
      while (DAT_08b57e10 < 0) {
        FUN_08830b98(local_230,param_6,1);
      }
    }
  }
  return;
}
```

这段代码是一个C语言函数的反汇编或反编译后的伪代码。函数名为`FUN_0882eed4`，接受六个参数。以下是对这段代码的解释：

### 函数签名
```c
void FUN_0882eed4(undefined4 param_1, undefined4 param_2, undefined4 param_3, undefined4 param_4, char *param_5, int param_6)
```
- `param_1` 到 `param_4` 是四个未定义类型的参数（通常是32位整数）。
- `param_5` 是一个指向字符数组（字符串）的指针。
- `param_6` 是一个整数。

### 局部变量
- `local_230` 是一个512字节的字符数组，用于存储临时字符串。
- `pcVar5` 是一个指向字符的指针，用于遍历和操作 `local_230`。
- 其他变量如 `pcVar1`, `pcVar6`, `iVar2`, `uVar3`, `uVar7`, `cVar4` 用于临时存储和逻辑控制。

### 主要逻辑
1. **初始化**：
   - `pcVar5` 指向 `local_230` 的起始位置。
   - 检查全局变量 `DAT_08b01dfc` 是否不等于 -1。

2. **遍历 `param_5` 字符串**：
   - 使用 `cVar4` 逐个读取 `param_5` 中的字符。
   - 如果字符是 `$`，则根据下一个字符执行不同的操作：
     - 如果下一个字符是 `a`, `b`, 或 `c`，调用 `FUN_08839434` 和 `FUN_089a6090` 函数处理。
     - 如果下一个字符是 `n`，调用 `FUN_08830b98` 和 `FUN_088579ac` 函数处理，并根据条件调整 `param_5` 和 `param_6`。
     - 如果下一个字符是 `m`，调用 `FUN_08830b98`, `FUN_088579ac`, `FUN_088148dc`, 和 `FUN_08820d78` 函数处理，并重置 `param_6`。
   - 如果字符不是 `$`，则直接复制到 `local_230`。

3. **处理结束**：
   - 在字符串末尾添加 `\0` 终止符。
   - 调用 `FUN_08830b98` 和 `FUN_088579ac` 函数处理 `local_230`。

### 总结
这个函数的主要作用是解析和处理包含特殊标记（如 `$a`, `$b`, `$c`, `$n`, `$m`）的字符串，并根据这些标记执行相应的操作。具体的操作逻辑依赖于调用的其他函数（如 `FUN_08839434`, `FUN_089a6090`, `FUN_08830b98`, `FUN_088579ac`, `FUN_088148dc`, `FUN_08820d78`）的实现。

# 开始菜单

生成字体贴图（8位索引格式）和 UTF16 索引，在启动主程序之前加载。
