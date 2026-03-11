## Staff 表渲染流程详解

### 数据结构（已在 IDA 中定义）

```c
// 每条 Staff 指令条目，8 字节
struct StaffScrollCmd {
    unsigned int ctrl;   // 控制字，见下方位域说明
    short  row_left;     // 左列 row_id（-1 = 无）
    short  row_right;    // 右列 row_id（-1 = 无）
};
// ctrl 位域：
//   [0]    end_flag     —— 最后一条指令，滚动结束
//   [1:3]  align        —— 0=右(240-w) 1=居中(224-w) 2=左(10) 3=远右(248) 4/5/6=自定义x
//   [4:19] pixel_gap    —— 本行出现前还需滚动多少像素
//   [20]   has_separator—— 同时插入一条分割线(row_id=155)

// 全局上下文，0x56C = 1388 字节
struct StaffRollCtx {
    int            done_flag;         // +0    滚动完成标志
    int            har_handle;        // +4    game/staff.har 句柄
    int            hpt_handle[21];    // +8    [1..20] = staff01.hpt ~ staff20.hpt
    int            sprite_handle[64]; // +92   64 个活跃精灵句柄（环形缓冲）
    SlotPair       slot_pairs[64];    // +348  每个槽的左右辅助精灵（双列布局）
    int            sprite_x[64];      // +860  各槽缓存的 X 坐标
    float          sprite_y[64];      // +1116 各槽当前 Y 坐标（从 280.0 开始向上滚）
    int            cmd_tail_slot;     // +1372 环形缓冲写入指针（0-63）
    float          scroll_speed;      // +1376 每帧移动像素 = total_height / 5280.0
    float          scroll_accum;      // +1380 剩余像素距离（到显示下一行）
    StaffScrollCmd *cmd_ptr;          // +1384 当前命令表读取指针
};
```

---

### 渲染管线（逐帧流程）

#### 第一阶段：初始化 `StaffRoll_Init` @ `0x8975BB4`

```
1. Heap_Alloc(0x56C)           → 分配 StaffRollCtx
2. HAR_Load("game/staff.har")  → 打开资源包，句柄存 har_handle
3. 循环 i=1..20:
     hpt_handle[i] = HAR_FindEntry("staffNN")
4. sprite_y[0..63] = 280.0     → 初始 Y 在屏幕下方（PSP 屏高 272，280 即刚好在外）
   sprite_handle[*] = -1       → 全部槽标记为空
   slot_pairs[*] = {-1, -1}    → 辅助精灵也置空
5. scroll_speed = StaffRoll_CalcTotalHeight() / 5280.0
   cmd_ptr = &g_staffScrollTable[0]
```

#### 第二阶段：每帧 tick `StaffRoll_Update` @ `0x8975E0C`

```
if done_flag != 0: 直接返回（动画已结束）

// ① 决定是否消费下一条命令
if scroll_accum <= 0.0:
    StaffRoll_ProcessCmd(cmd_ptr)
    cmd_ptr += 1  (前进 8 字节)

// ② 更新所有活跃槽的 Y 坐标（向上滚动）
for slot in 0..63:
    if sprite_handle[slot] == -1: continue
    sprite_y[slot] -= scroll_speed     // 每帧上移 scroll_speed 像素

    top_edge = sprite_y[slot]
    height   = Sprite_GetHeight(sprite_handle[slot])

    if -height < top_edge:              // 精灵仍在屏幕内（bottom > 0）
        Sprite_SetY(sprite_handle[slot], top_edge)
        // 辅助精灵同步（双列布局）
        if slot_pairs[slot].sprite_a != -1:
            Sprite_SetXY(sprite_a, sprite_x[slot], top_edge + header_offset)
        if slot_pairs[slot].sprite_b != -1:
            Sprite_SetXY(sprite_b, 240.0, top_edge + header_offset)
    else:                               // 已完全滚出屏幕顶部
        StaffRoll_FreeSlot(slot)        // 释放精灵内存

// ③ 累加器每帧递减
scroll_accum -= scroll_speed
```

#### 第三阶段：处理命令条目 `StaffRoll_ProcessCmd` @ `0x8975F9C`

```
// 读指令位域
if ctrl.end_flag: done_flag = 1

// ── 左列 (row_left != -1) ──
slot = cmd_tail_slot
sprite_y[slot] = 280.0   (重置为屏幕底部外侧)
sprite_handle[slot] = StaffRoll_AllocRow(row_left)
if sprite_handle[slot] != -1:
    Sprite_Show(handle)
    Sprite_SetPriority(handle, 2)
    w = Sprite_GetWidth(handle)
    x = 按 ctrl.align 计算:
          align=0 → 240-w    (右列居中)
          align=1 → 224-w    (中央右侧)
          align=2 → 10       (左侧)
          align=3 → 248      (远右)
          align=4/5/6 → 自定义
    Sprite_SetX(handle, x)
cmd_tail_slot = (slot + 1) % 64

// ── 右列 (row_right != -1，类似处理，X 固定偏移) ──

// ── 分割线 (ctrl.has_separator) ──
if ctrl.has_separator and separator_height > 0:
    slot = cmd_tail_slot
    sprite_y[slot] = 280.0 + 24.0   (稍低一行，24px 间距)
    sprite_handle[slot] = StaffRoll_AllocRow(155)  // 固定为分割线行
    Sprite_SetScale(handle, total_width / sprite_w, 1.0)
    Sprite_SetX(handle, 240 - separator_height)
    cmd_tail_slot = (slot + 1) % 64

// ── 累加像素距离 ──
scroll_accum += (ctrl >> 4) & 0xFFFF   // pixel_gap
```

#### 第四阶段：行图像定位 `StaffRoll_AllocRow` @ `0x8976500`

```
// row_id 是全局行编号（0-213），映射到对应的 HPT 图像和局部行号
// 每张 HPT 包含若干行文字（单行高 24px，宽 512px）
// 分段映射表（共 20 段）：
//   row_id  0- 9  → hpt_handle[1]  (staff01), local = row_id - 0
//   row_id 10-20  → hpt_handle[2]  (staff02), local = row_id - 10
//   row_id 21-33  → hpt_handle[3]  (staff03), local = row_id - 21
//   ... 依此类推到 row_id 213
//   row_id 155    → 特殊：分割线（hpt_handle 某段）
//   row_id >= 214 → 返回 -1（无效）

return HPT_CreateRowSprite(hpt, local_row, 0x4000, 512, 24)
//   参数：图像句柄, 行号, 初始X(0x4000=屏外), 行宽, 行高
```

---

### 速度控制公式

游戏以固定 **60 FPS** 运行。整个 Staff 表的播放时长固定为 **88 秒**：

$$\text{scroll\_speed} = \frac{\sum \text{pixel\_gap}_i}{5280.0}, \quad 5280 = 60 \times 88$$

若要追加新的 Staff 行：
1. **`.har` 内容**：向 `staff.har` 注入 `staff21.hpt`（或扩展现有 HPT 的行数）
2. **循环上限**：Patch `0x8975c24` 的 `slti v0,v1,21` → `slti v0,v1,N+1`
3. **堆内存大小**：Patch `0x8975bec` 的 `0x56C` → `0x56C + (N-20)*4`（每增加一个 HPT 句柄多 4 字节）
4. **命令表**：在 `g_staffScrollTable` 末尾（`end_flag=1` 之前）插入新的 `StaffScrollCmd` 条目，并相应调整 `pixel_gap` 以维持 88 秒节奏（或直接调大 `5280.0` 保持原节奏）

Ran `disasm` 
Completed with input: {
  "addr": "0x8A561FC",
  "count": 32
}

Ran `get_bytes` 
Completed with input: {
  "regions": [
    {
      "addr": "0x8A561FC",
      "size": 128
    }
  ]
}

数据已经可读了，我来解析前几条并查找交叉引用以确认数据来源： 

Ran `xrefs_to` 
Completed with input: {
  "addrs": "[\"0x8A561FC\"]"
}

Ran `get_bytes` 
Completed with input: {
  "regions": [
    {
      "addr": "0x8A561FC",
      "size": 2048
    }
  ]
}

Read [](file:///home/pspdev/.vscode-server/data/User/workspaceStorage/f0413c396fa74e43ce4ae42fcf9abe44/GitHub.copilot-chat/chat-session-resources/2a529258-ff13-4cfd-badd-f5ffd9a475db/toolu_bdrk_01P5LCn3Gz2iVFtbmdoUwEZj__vscode-1773194508442/content.json)

结论已经很清楚了。`g_staffScrollTable` 就在二进制文件内部，让我确认具体的末尾标记位置： 

Ran `find_bytes` 
Completed with input: {
  "patterns": "[{\"pattern\": \"19 00 00 00 FF FF FF FF\", \"start_addr\": \"0x8A561FC\"}]"
}

Ran `find` 
Completed with input: {
  "targets": "[\"sound/eva_se01.bin\"]",
  "type": "string"
}

完整图像已经很清晰了。来告诉你答案：

---

## `g_staffScrollTable` 在哪？

**直接硬编码在 EBOOT.BIN 的只读数据段（`.rodata`）里**，不来自任何外部文件。

- **起始地址**：`0x8A561FC`（在 EBOOT.BIN 中的某个固定文件偏移）
- **结束地址**：`0x8A56814`（末尾是 `ctrl=0x19`，即 `end_flag=1` 的结束标记）
- **表大小**：`0x618` 字节 = **195 条 `StaffScrollCmd` 指令**
- 紧接着（`0x8A5681C`）是字符串 `"sound/eva_se01.bin"`，无任何填充空间

命令表的读取路径完全是：

```
EBOOT.BIN 加载到内存
    → 静态数据段映射到 0x8A561FC
        → StaffRoll_Init() 中 cmd_ptr = &g_staffScrollTable
            → StaffRoll_Update() 每帧按需递增 cmd_ptr 读取下一条
```

---

## 快速解析前几条实际内容

| 地址          | ctrl       | end | align | pixel_gap | row_left | row_right | 含义               |
|---------------|------------|-----|-------|-----------|----------|-----------|---------------------|
| `0x8A561FC`   | `0x0000020C` | 0 | 6     | 32        | 164 (新世紀エヴァンゲリオン2)      | 166 (造られしセカイ)      | 双列姓名行            |
| `0x8A56204`   | `0x0000020C` | 0 | 6     | 32        | 165      | 167       | 双列姓名行            |
| `0x8A5620C`   | `0x00001088` | 0 | 4     | **264**   | -1       | -1        | 大间距空行（章节分隔） |
| `0x8A56214`   | `0x00000108` | 0 | 4     | 16        | -1       | -1        | 小空行               |
| `0x8A5621C`   | `0x00100208` | 0 | 4     | 32        | 120      | -1        | 单列 + **分割线**（bit20=1）|
| `0x8A56814`   | `0x00000019` | **1** | 4  | 1         | -1       | -1        | **结束标记**         |

---

## 追加 Staff 的实际操作

由于表末尾紧贴着 `"sound/eva_se01.bin"` 字符串，**原地插入不可行**，必须**整体搬迁**。步骤如下：

1. **在 EBOOT.BIN 中找一块足够大的空闲区域**（通常是文件末尾填充的 `0x00`），把整个195条表 + 新增条目 + 新 `end_flag` 写进去

2. **Patch 两处引用地址**（加载表基址的指令 `lui/addiu` 对）：
   - `StaffRoll_Init` @ `0x8975C98/0x8975C9C`（设置 `cmd_ptr` 初始值）
   - `StaffRoll_CalcTotalHeight` @ `0x8976410`（遍历表计算总高度）

3. **修改 `scroll_speed` 分母**（`5280.0` 浮点常数），或新增的条目里 `pixel_gap` 要对应缩减，保证总 `∑pixel_gap / 5280.0` 维持原来的帧率节奏

```
.data:08A561FC g_staffScrollTable:StaffScrollCmd <0x20C, 0xA4, 0xA6>
.data:08A561FC                                          # DATA XREF: StaffRoll_Init+E4↑o
.data:08A561FC                                          # StaffRoll_Init+E8↑o ...
.data:08A56204                 StaffScrollCmd <0x20C, 0xA5, 0xA7>
.data:08A5620C                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A56214                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5621C                 StaffScrollCmd <0x100208, 0x78, 0xFFFF>
.data:08A56224                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5622C                 StaffScrollCmd <0x208, 2, 0xFFFF>
.data:08A56234                 StaffScrollCmd <0x208, 3, 0xFFFF>
.data:08A5623C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56244                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5624C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56254                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5625C                 StaffScrollCmd <0x100208, 0x79, 0xFFFF>
.data:08A56264                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5626C                 StaffScrollCmd <0x308, 5, 6>
.data:08A56274                 StaffScrollCmd <0x100, 7, 0xFFFF>
.data:08A5627C                 StaffScrollCmd <0x106, 8, 0xFFFF>
.data:08A56284                 StaffScrollCmd <0x300, 0xC, 0xFFFF>
.data:08A5628C                 StaffScrollCmd <0x308, 9, 0xB>
.data:08A56294                 StaffScrollCmd <0x308, 0xD, 0xE>
.data:08A5629C                 StaffScrollCmd <0x308, 0xF, 0x10>
.data:08A562A4                 StaffScrollCmd <0x308, 0x11, 4>
.data:08A562AC                 StaffScrollCmd <0x308, 0x12, 0x19>
.data:08A562B4                 StaffScrollCmd <0x100, 0x14, 0xFFFF>
.data:08A562BC                 StaffScrollCmd <0x106, 0x1F, 0xFFFF>
.data:08A562C4                 StaffScrollCmd <0x300, 0x16, 0xFFFF>
.data:08A562CC                 StaffScrollCmd <0x308, 0x18, 0x13>
.data:08A562D4                 StaffScrollCmd <0x308, 0x1A, 0x1B>
.data:08A562DC                 StaffScrollCmd <0x100, 0x1C, 0xFFFF>
.data:08A562E4                 StaffScrollCmd <0x106, 0x1D, 0xFFFF>
.data:08A562EC                 StaffScrollCmd <0x300, 0x1E, 0xFFFF>
.data:08A562F4                 StaffScrollCmd <0x308, 0x20, 0x28>
.data:08A562FC                 StaffScrollCmd <0x308, 0x23, 0x24>
.data:08A56304                 StaffScrollCmd <0x308, 0x25, 0x26>
.data:08A5630C                 StaffScrollCmd <0x308, 0x27, 0x21>
.data:08A56314                 StaffScrollCmd <0x308, 0x29, 0x17>
.data:08A5631C                 StaffScrollCmd <0x308, 0x2A, 0x2B>
.data:08A56324                 StaffScrollCmd <0x308, 0x2C, 0x2D>
.data:08A5632C                 StaffScrollCmd <0x308, 0xD0, 0xCF>
.data:08A56334                 StaffScrollCmd <0x308, 0x2F, 0x30>
.data:08A5633C                 StaffScrollCmd <0x308, 0x31, 0x32>
.data:08A56344                 StaffScrollCmd <0x308, 0xA8, 0x34>
.data:08A5634C                 StaffScrollCmd <0x100, 0xA9, 0xFFFF>
.data:08A56354                 StaffScrollCmd <0x106, 0x36, 0xFFFF>
.data:08A5635C                 StaffScrollCmd <0x300, 0xD1, 0xFFFF>
.data:08A56364                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A5636C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56374                 StaffScrollCmd <0x100208, 0x7A, 0xFFFF>
.data:08A5637C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56384                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5638C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56394                 StaffScrollCmd <0x100208, 0x80, 0xFFFF>
.data:08A5639C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A563A4                 StaffScrollCmd <0x208, 0x42, 0xFFFF>
.data:08A563AC                 StaffScrollCmd <0x208, 0x3A, 0xFFFF>
.data:08A563B4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A563BC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A563C4                 StaffScrollCmd <0x100208, 0x7B, 0xFFFF>
.data:08A563CC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A563D4                 StaffScrollCmd <0x208, 0xC2, 0xFFFF>
.data:08A563DC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A563E4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A563EC                 StaffScrollCmd <0x100208, 0x82, 0xFFFF>
.data:08A563F4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A563FC                 StaffScrollCmd <0x208, 0xCD, 0xFFFF>
.data:08A56404                 StaffScrollCmd <0x208, 0x46, 0xFFFF>
.data:08A5640C                 StaffScrollCmd <0x208, 0x49, 0xFFFF>
.data:08A56414                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5641C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56424                 StaffScrollCmd <0x100208, 0xD3, 0xFFFF>
.data:08A5642C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56434                 StaffScrollCmd <0x208, 0x48, 0xFFFF>
.data:08A5643C                 StaffScrollCmd <0x208, 0xC3, 0xFFFF>
.data:08A56444                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5644C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56454                 StaffScrollCmd <0x100208, 0xAA, 0xFFFF>
.data:08A5645C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56464                 StaffScrollCmd <0x20A, 0xC4, 0x4A>
.data:08A5646C                 StaffScrollCmd <0x20A, 0xC5, 0x4D>
.data:08A56474                 StaffScrollCmd <0x20A, 0xC6, 0x4E>
.data:08A5647C                 StaffScrollCmd <0x20A, 0xC7, 0xC8>
.data:08A56484                 StaffScrollCmd <0x20A, 0x4B, 0xC9>
.data:08A5648C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56494                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5649C                 StaffScrollCmd <0x100208, 0x81, 0xFFFF>
.data:08A564A4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A564AC                 StaffScrollCmd <0x20A, 0x51, 0x55>
.data:08A564B4                 StaffScrollCmd <0x20A, 0x58, 0x5B>
.data:08A564BC                 StaffScrollCmd <0x20A, 0x61, 0x54>
.data:08A564C4                 StaffScrollCmd <0x20A, 0xCA, 0x59>
.data:08A564CC                 StaffScrollCmd <0x20A, 0x5E, 0x5A>
.data:08A564D4                 StaffScrollCmd <0x20A, 0xCB, 0x52>
.data:08A564DC                 StaffScrollCmd <0x202, 0x56, 0xFFFF>
.data:08A564E4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A564EC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A564F4                 StaffScrollCmd <0x100208, 0x83, 0xFFFF>
.data:08A564FC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56504                 StaffScrollCmd <0x208, 0x64, 0xFFFF>
.data:08A5650C                 StaffScrollCmd <0x208, 0x63, 0xFFFF>
.data:08A56514                 StaffScrollCmd <0x208, 0xCC, 0xFFFF>
.data:08A5651C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56524                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5652C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56534                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5653C                 StaffScrollCmd <0x100208, 0x89, 0xFFFF>
.data:08A56544                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5654C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56554                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5655C                 StaffScrollCmd <0x100208, 0x8B, 0xFFFF>
.data:08A56564                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5656C                 StaffScrollCmd <0x208, 0x68, 0xFFFF>
.data:08A56574                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5657C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56584                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5658C                 StaffScrollCmd <0x100208, 0x8A, 0xFFFF>
.data:08A56594                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5659C                 StaffScrollCmd <0x208, 0x69, 0xFFFF>
.data:08A565A4                 StaffScrollCmd <0x208, 0x6A, 0xFFFF>
.data:08A565AC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A565B4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A565BC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A565C4                 StaffScrollCmd <0x100208, 0x8D, 0xFFFF>
.data:08A565CC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A565D4                 StaffScrollCmd <0x208, 0x6B, 0xFFFF>
.data:08A565DC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A565E4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A565EC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A565F4                 StaffScrollCmd <0x100208, 0x8E, 0xFFFF>
.data:08A565FC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56604                 StaffScrollCmd <0x208, 0x6C, 0xFFFF>
.data:08A5660C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56614                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5661C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56624                 StaffScrollCmd <0x100208, 0x90, 0xFFFF>
.data:08A5662C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56634                 StaffScrollCmd <0x208, 0x6D, 0xFFFF>
.data:08A5663C                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A56644                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5664C                 StaffScrollCmd <0x100208, 0x9D, 0xFFFF>
.data:08A56654                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5665C                 StaffScrollCmd <0x20A, 0xAF, 0xC1>
.data:08A56664                 StaffScrollCmd <0x20A, 0xB2, 0x9F>
.data:08A5666C                 StaffScrollCmd <0x20A, 0x74, 0xBC>
.data:08A56674                 StaffScrollCmd <0x202, 0xB0, 0xFFFF>
.data:08A5667C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56684                 StaffScrollCmd <0x20A, 0x73, 0x75>
.data:08A5668C                 StaffScrollCmd <0x20A, 0xBB, 0x76>
.data:08A56694                 StaffScrollCmd <0x20A, 0xB9, 0xB3>
.data:08A5669C                 StaffScrollCmd <0x20A, 0xB4, 0xB8>
.data:08A566A4                 StaffScrollCmd <0x20A, 0xB5, 0xBA>
.data:08A566AC                 StaffScrollCmd <0x20A, 0xB6, 0xB7>
.data:08A566B4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A566BC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A566C4                 StaffScrollCmd <0x100208, 0xD5, 0xFFFF>
.data:08A566CC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A566D4                 StaffScrollCmd <0x208, 0xBE, 0xFFFF>
.data:08A566DC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A566E4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A566EC                 StaffScrollCmd <0x100208, 0xAB, 0xFFFF>
.data:08A566F4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A566FC                 StaffScrollCmd <0x208, 0x9E, 0xFFFF>
.data:08A56704                 StaffScrollCmd <0x208, 0xBF, 0xFFFF>
.data:08A5670C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56714                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5671C                 StaffScrollCmd <0x100208, 0x7C, 0xFFFF>
.data:08A56724                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5672C                 StaffScrollCmd <0x208, 0xBD, 0xFFFF>
.data:08A56734                 StaffScrollCmd <0x208, 0xC0, 0xFFFF>
.data:08A5673C                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A56744                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5674C                 StaffScrollCmd <0x100208, 0xAC, 0xFFFF>
.data:08A56754                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5675C                 StaffScrollCmd <0x208, 0x41, 0xFFFF>
.data:08A56764                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A5676C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56774                 StaffScrollCmd <0x100208, 0x97, 0xFFFF>
.data:08A5677C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56784                 StaffScrollCmd <0x208, 0x40, 0xFFFF>
.data:08A5678C                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A56794                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A5679C                 StaffScrollCmd <0x100208, 0x96, 0xFFFF>
.data:08A567A4                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A567AC                 StaffScrollCmd <0x208, 0x38, 0xFFFF>
.data:08A567B4                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A567BC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A567C4                 StaffScrollCmd <0x100208, 0x8C, 0xFFFF>
.data:08A567CC                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A567D4                 StaffScrollCmd <0x208, 2, 0xFFFF>
.data:08A567DC                 StaffScrollCmd <0x208, 3, 0xFFFF>
.data:08A567E4                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A567EC                 StaffScrollCmd <0x208, 0xA2, 0xFFFF>
.data:08A567F4                 StaffScrollCmd <0x1088, 0xFFFF, 0xFFFF>
.data:08A567FC                 StaffScrollCmd <0x204, 0x95, 0xFFFF>
.data:08A56804                 StaffScrollCmd <0x204, 0xA1, 0xFFFF>
.data:08A5680C                 StaffScrollCmd <0x108, 0xFFFF, 0xFFFF>
.data:08A56814                 StaffScrollCmd <0x19, 0xFFFF, 0xFFFF>
```

先并行反编译 `HPT_CreateRowSprite` 以及查看 `slot_pairs` 是在哪里被写入的。 

Ran `decompile` 
Completed with input: {
  "addr": "0x8812EB0"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x88126D0"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x8871A2C"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x8871AE8"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x8869B3C"
}

再深入看 sprite 对象的创建以及 UV 行选择机制： 

Ran `decompile` 
Completed with input: {
  "addr": "0x8871A98"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x88699E4"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x8873570"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x88735A0"
}

继续查看行宽计算和 `slot_pairs` 真正在哪里写入：  

Ran `decompile` 
Completed with input: {
  "addr": "0x88172D8"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x8806064"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x8812CE4"
}

Ran `decompile` 
Completed with input: {
  "addr": "0x8871DCC"
}

看看 `StaffRoll_ProcessCmd` 的实际汇编，搜出写入 slot_pairs（offset 348）的指令： 

Ran `disasm` 
Completed with input: {
  "addr": "0x8975FA4",
  "end_addr": "0x8976320"
}

Ran `get_bytes` 
Completed with input: {
  "regions": [
    {
      "addr": "0x8975FA4",
      "size": 900
    }
  ]
}

还需要查清 `flt_89DB11C`（对位 Y 偏移）以及行对齐用的屏幕宽度函数：  

Ran `get_bytes` 
Completed with input: {
  "regions": [
    {
      "addr": "0x89DB11C",
      "size": 8
    }
  ]
}

Ran `get_bytes` 
Completed with input: {
  "regions": [
    {
      "addr": "0x8AF8FFC",
      "size": 48
    }
  ]
}

用两个关键数值（32.0f 和 240.0f）和精灵系统已经说清楚了。现在添加最终注释和命名：   

Ran `rename` 
Completed with input: {
  "batch": {
    "data": [
      {
        "old": "dword_8AF8FFC",
        "new": "g_spriteSlotTable"
      },
      {
        "old": "flt_89DB11C",
        "new": "f_pairSpriteYOffset"
      }
    ],
    "func": [
      {
        "addr": "0x8871A98",
        "name": "SpriteObj_Create"
      },
      {
        "addr": "0x8871A2C",
        "name": "SpriteObj_SetHPTAtlas"
      },
      {
        "addr": "0x8871AE8",
        "name": "SpriteObj_SelectRow"
      },
      {
        "addr": "0x88699E4",
        "name": "HPT_BindAtlas"
      },
      {
        "addr": "0x8869B3C",
        "name": "HPT_SetUVRow"
      },
      {
        "addr": "0x8873570",
        "name": "HPT_GetRowWidth"
      },
      {
        "addr": "0x88735A0",
        "name": "HPT_GetRowHeight"
      },
      {
        "addr": "0x88172D8",
        "name": "Anchor_ResolveX"
      },
      {
        "addr": "0x8806064",
        "name": "Screen_GetWidth"
      },
      {
        "addr": "0x88126D0",
        "name": "Sprite_SetXY_Anchored"
      },
      {
        "addr": "0x8812D2C",
        "name": "Sprite_GetHeight"
      },
      {
        "addr": "0x8812E24",
        "name": "Sprite_SetScale"
      },
      {
        "addr": "0x8871F18",
        "name": "SpriteObj_Alloc"
      }
    ]
  }
}

Ran `set_comments` 
Completed with input: {
  "items": [
    {
      "addr": "0x8812EB0",
      "comment": "HPT_CreateRowSprite(hpt_handle, local_row, x, width, height=24):\n  1. Find free slot in g_spriteSlotTable (512 slots, 12 bytes each: [obj_ptr, x_pivot, y_pivot, w, h])\n  2. SpriteObj_Create(24) -> alloc sprite object with height=24\n  3. SpriteObj_SetHPTAtlas(obj, HPT_texture_handle) -> bind HPT texture as atlas source\n  4. SpriteObj_SelectRow(obj, local_row) -> set UV crop to row N of HPT (calls HPT_SetUVRow)\n  5. Sprite_SetXY_Anchored(slot, x=0x4000, y=512) -> position off-screen initially\n  Returns: slot index, or -1 if no free slot"
    },
    {
      "addr": "0x88699E4",
      "comment": "HPT_BindAtlas: Change the HPT texture atlas bound to this sprite obj. Reads row 0 UV from atlas header as default UV state."
    },
    {
      "addr": "0x8869B3C",
      "comment": "HPT_SetUVRow(sprite_obj, row_idx): Select row 'row_idx' from the HPT row UV table.\n  Row UV table entry = 8 bytes: {int16 u, int16 v, int16 width, int16 height}\n  Sets sprite's UV crop rect to this row's texture strip coordinates."
    },
    {
      "addr": "0x88172D8",
      "comment": "Anchor_ResolveX(x, sprite_width):\n  x == 0x4000 -> CENTER anchor: returns (Screen_GetWidth() - sprite_width) / 2\n                 e.g. (480 - 512) / 2 = -16 for full-width 512px HPT rows\n                 This positions a 512px-wide sprite at -16 so its center 480px fills the screen.\n  x == anything else -> pass-through, use x directly"
    },
    {
      "addr": "0x8806064",
      "comment": "Screen_GetWidth(): returns 480 (normal PSP mode) or 512 (widescreen mode, dword_8A65B48 != 0)"
    },
    {
      "addr": "0x88126D0",
      "comment": "Sprite_SetXY_Anchored(slot, x, y):\n  x=0x4000 triggers centering via Anchor_ResolveX (uses sprite width from slot entry[4])\n  x=0x8000 = sentinel: skip X update\n  y=0x8000 = sentinel: skip Y update\n  Final screen pos stored in sprite_obj+128 (X) and sprite_obj+132 (Y)"
    },
    {
      "addr": "0x8AF8FFC",
      "comment": "g_spriteSlotTable: flat array of 512 sprite slots, each 12 bytes:\n  +0  (DWORD ): sprite obj ptr (0=free)\n  +4  (int16 ): x_pivot anchor offset\n  +6  (int16 ): y_pivot anchor offset\n  +8  (int16 ): cached sprite width (from HPT row UV crop)\n  +10 (int16 ): cached sprite height (= 24 for HPT rows)"
    }
  ]
}

Ran `declare_type` 
Completed with input: {
  "decls": "[\"struct SpriteSlot { int obj_ptr; short x_pivot; short y_pivot; short cached_width; short cached_height; };\", \"struct HPTRowUV { short u; short v; short width; short height; };\"]"
}

所有重命名和结构定义已写入 IDA。下面是完整的"拼接"机制讲解。

---

## 多 HPT 拼接原理

### 核心结论：没有像素级合并，全是空间布局

引擎**从不**把多张 HPT 的位图拷贝到同一块内存再渲染。"拼"这个动作发生在 **GPU 显示层**，通过把多个 Sprite 放在不同 X 坐标来拼出一整行视觉内容。

---

### 层次 1：HPT 作为 UV 纹理图集

每个 HPT 文件本质上是一张 **512×(N×24) px** 的纹理图集，每行文字占 24px 高度，垂直排列：

```
staff01.hpt (纹理 512×240px)
┌──────────────────────────────────┐ ← Row 0  (ID 0,  UV v=0)
│  "監督                    庵野秀明"  │ 24px
├──────────────────────────────────┤ ← Row 1  (ID 1,  UV v=24)
│  "総作監                  貞本義行"  │ 24px
│ ...                              │
└──────────────────────────────────┘ ← Row 9  (ID 9,  UV v=216)
```

`HPT_SetUVRow` 根据行号从 HPT 内部的 `HPTRowUV[]` 表读取：

```c
struct HPTRowUV { short u; short v; short width; short height; };
// 选行 row N → 设 UV 裁剪窗口为 [u, v, u+w, v+h]
```

---

### 层次 2：全局 Row ID → HPT + 局部行号的映射

`StaffRoll_AllocRow` 把 214 个全局行 ID 分段映射到 20 个 HPT 文件。

**映射范围（从 EBOOT @ 0x8976500 汇编代码提取）**：

```
row_id [  0,  10) → staff01.hpt,  local_row = id -   0     (10 行)
row_id [ 10,  21) → staff02.hpt,  local_row = id -  10     (11 行)
row_id [ 21,  34) → staff03.hpt,  local_row = id -  21     (13 行)
row_id [ 34,  46) → staff04.hpt,  local_row = id -  34     (12 行)
row_id [ 46,  55) → staff05.hpt,  local_row = id -  46     ( 9 行)
row_id [ 55,  67) → staff06.hpt,  local_row = id -  55     (12 行)
row_id [ 67,  80) → staff07.hpt,  local_row = id -  67     (13 行)
row_id [ 80,  93) → staff08.hpt,  local_row = id -  80     (13 行)
row_id [ 93, 103) → staff09.hpt,  local_row = id -  93     (10 行)
row_id [103, 114) → staff10.hpt,  local_row = id - 103     (11 行)
row_id [114, 125) → staff11.hpt,  local_row = id - 114     (11 行)
row_id [125, 136) → staff12.hpt,  local_row = id - 125     (11 行)
row_id [136, 147) → staff13.hpt,  local_row = id - 136     (11 行)
row_id [147, 154) → staff14.hpt,  local_row = id - 147     ( 7 行)
row_id [154, 156) → staff15.hpt,  local_row = id - 154     ( 2 行)
row_id [156, 160) → staff16.hpt,  local_row = id - 156     ( 4 行)
row_id [160, 163) → staff17.hpt,  local_row = id - 160     ( 3 行)
row_id [163, 174) → staff18.hpt,  local_row = id - 163     (11 行)
row_id [174, 206) → staff19.hpt,  local_row = id - 174     (32 行)
row_id [206, 214) → staff20.hpt,  local_row = id - 206     ( 8 行)

特殊值：row_id 155 = staff15 local_row 1（分割线素材）
```

**示例**：
- `cmd[0]: row_left=164, row_right=166` 
  - row_id 164 → staff18 local_row 1
  - row_id 166 → staff18 local_row 3
- `cmd[1]: row_left=165, row_right=167`
  - row_id 165 → staff18 local_row 2  
  - row_id 167 → staff18 local_row 4

每次 `HPT_CreateRowSprite(hpt, local_row, 0x4000, 512, 24)` 创建的 Sprite：
- **纹理源**：指定 HPT 的第 `local_row` 行 UV 裁剪窗口
- **初始位置**：X=`0x4000`（特殊锚点），Y=512（屏幕外）

---

### 层次 3：Sprite 的 X 定位——512px 纹理居中于 480px 屏幕

`Anchor_ResolveX(0x4000, 512)` 对宽度 512px 的 HPT 行执行：

$$X = \frac{480 - 512}{2} = -16$$

所以精灵从 X=-16 开始渲染，后 496px 超出右边界——PSP GE 自动裁剪，实际可见区域是纹理的像素 16 到 495（共 480px），完整地充满整个屏幕宽度：

```
屏幕 [0         479]
纹理 [-16 ... 0 ... 479 ... 495]
         ↑被裁掉    ↑被裁掉
         可见文字内容居中在 512px 纹理中央 480px
```

---

### 层次 4：左列 + 右列的"双列拼接"

一条 `StaffScrollCmd(row_left=L, row_right=R)` 会创建 **两个完全独立的 Sprite**，进入相邻的两个 ring-buffer 槽：

```
槽 A: sprite_handle[A] = HPT_CreateRowSprite(左列 HPT, 局部行)
      sprite_y[A] = 280.0       ← 同样的起始 Y
      X = 按 alignment 计算 (0~239 区域，左半屏)

槽 B: sprite_handle[B] = HPT_CreateRowSprite(右列 HPT, 局部行)  
      sprite_y[B] = 280.0       ← 同样的起始 Y
      X = 240.0 (固定在右半屏)
```

两个精灵**各自独立更新 Y**，但因为：
① 起始 Y 相同（同一帧内 ProcessCmd 同时创建）
② scroll_speed 相同（全局唯一常量）

所以视觉上始终对齐，模拟成"一行"的效果：

```
屏幕坐标 (帧 t):
  X=left_x → [  监督         ] Y=280 - t*speed
  X=240    → [  庵野秀明    ] Y=280 - t*speed
```

---

### 层次 5：`slot_pairs` 的真实用途

经过完整分析（逐字节扫描 `StaffRoll_ProcessCmd` 汇编，未发现对 offset 348/352 的写指令），**staff roll 运行期间 `slot_pairs` 始终保持初始值 -1**。这套机制是图文场景通用底层基础设施（如过场标题卡）预留的能力：主精灵（标题）+ 子精灵 A/B（注脚/图标）共同跟随同一 Y 坐标移动，Y 偏移值固定为 `f_pairSpriteYOffset = 32.0f`。

```
// StaffRoll_AllocRow(int row_id): resolve row_id to (hpt_handle, local_row) and call HPT_CreateRowSprite(hpt, local_row, 0x4000, 512, 24). Range table maps global IDs 0-213 to 20 HPT images. row_id 155 = special horizontal separator bar.
int StaffRoll_AllocRow(int row_id)
{
  int v1; // $v1
  int v3; // $a1
  int v4; // $a0

  v1 = -1;
  if ( row_id < 214 )
  {
    if ( row_id >= 206 )
    {
      v3 = row_id - 206;
      v4 = g_pStaffCtx->hpt_handle[20];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 174 )
    {
      v3 = row_id - 174;
      v4 = g_pStaffCtx->hpt_handle[19];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 163 )
    {
      v3 = row_id - 163;
      v4 = g_pStaffCtx->hpt_handle[18];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 160 )
    {
      v3 = row_id - 160;
      v4 = g_pStaffCtx->hpt_handle[17];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 156 )
    {
      v3 = row_id - 156;
      v4 = g_pStaffCtx->hpt_handle[16];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 154 )
    {
      v3 = row_id - 154;
      v4 = g_pStaffCtx->hpt_handle[15];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 147 )
    {
      v3 = row_id - 147;
      v4 = g_pStaffCtx->hpt_handle[14];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 136 )
    {
      v3 = row_id - 136;
      v4 = g_pStaffCtx->hpt_handle[13];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 125 )
    {
      v3 = row_id - 125;
      v4 = g_pStaffCtx->hpt_handle[12];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 114 )
    {
      v3 = row_id - 114;
      v4 = g_pStaffCtx->hpt_handle[11];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 103 )
    {
      v3 = row_id - 103;
      v4 = g_pStaffCtx->hpt_handle[10];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 93 )
    {
      v3 = row_id - 93;
      v4 = g_pStaffCtx->hpt_handle[9];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 80 )
    {
      v3 = row_id - 80;
      v4 = g_pStaffCtx->hpt_handle[8];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 67 )
    {
      v3 = row_id - 67;
      v4 = g_pStaffCtx->hpt_handle[7];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 55 )
    {
      v3 = row_id - 55;
      v4 = g_pStaffCtx->hpt_handle[6];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 46 )
    {
      v3 = row_id - 46;
      v4 = g_pStaffCtx->hpt_handle[5];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 34 )
    {
      v3 = row_id - 34;
      v4 = g_pStaffCtx->hpt_handle[4];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 21 )
    {
      v3 = row_id - 21;
      v4 = g_pStaffCtx->hpt_handle[3];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    if ( row_id >= 10 )
    {
      v3 = row_id - 10;
      v4 = g_pStaffCtx->hpt_handle[2];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
    v1 = -1;
    if ( row_id >= 0 )
    {
      v3 = row_id;
      v4 = g_pStaffCtx->hpt_handle[1];
      return HPT_CreateRowSprite(v4, v3, 0x4000, 512, 24);
    }
  }
  return v1;
}
```