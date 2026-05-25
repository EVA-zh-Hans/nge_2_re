# sub_890F2C4 与 off_8A4B45C 研究总结

## 结论概览

- `off_8A4B45C` 不是“单纯的字符串指针数组”，而是 **每项 8 字节的二元指针表**：`{prefix, suffix}`。
- `sub_890F2C4` 本身 **不做字符串拼接**，它负责从某个 `ActionRecord` 数组里筛选记录并按 `sortKey` 排序输出。
- 真正的“拼接/生成字符串”发生在 `sub_890FA58`：它根据 `rec->templateId` 取出 `{prefix, suffix}` 两段模板，展开后写入输出缓冲区，格式为：
  - `prefix`
  - 如果 `suffix` 非空：`prefix + (可选分隔符 delimiter) + suffix`
- 模板展开由 `sub_890FB64` 负责，支持两类占位符：`$a` 与 `$b`，分别用 `rec->maskA` / `rec->maskB` 的位掩码生成按键文本（最终调用 `sub_890F7B4`）。

## 数据结构（已在 IDA 里应用）

### ActionTemplatePair（off_8A4B45C 的元素类型）

```c
typedef struct ActionTemplatePair {
  const char *prefix;
  const char *suffix;
} ActionTemplatePair;

extern ActionTemplatePair off_8A4B45C[0x6D6];
```

- 表基址：`0x8A4B45C`
- 索引方式：`templateId << 3`（每项 8 字节）
- `prefix[0] == 0` 常被用作“该条目无效/隐藏”的判定（见 `sub_890F2C4`）
- `suffix[0] == 0` 表示不需要第二段（见 `sub_890FA58`）

### ActionRecord（sub_890F2C4 / sub_890FA58 用到的字段）

```c
typedef struct ActionRecord {
    uint32_t timestamp;   /* +0x00 */
    uint32_t maskA;       /* +0x04, template-layer $a */
    uint32_t maskB;       /* +0x08, template-layer $b */
    uint8_t valid;        /* +0x0C */
    uint8_t locationId;   /* +0x0D */
    uint16_t templateId;  /* +0x0E  索引 off_8A4B45C，范围 < 0x6D6 */
    uint8_t recordType;   /* +0x10 */
    uint8_t unk11;        /* +0x11 */
    uint16_t sortKey;     /* +0x12 sub_890F2C4 用作排序键；0 表示跳过 */
} ActionRecord;
```

## sub_890F2C4 行为（筛选 + 排序）

IDA 当前函数签名（已更新）：

```c
typedef int (__fastcall *ActionRecordFilterFn)(const ActionRecord *rec, int userArg);

int __fastcall sub_890F2C4(
  ActionRecord **outRecs,
  int recordCount,
  int memTalkHandle,
  ActionRecordFilterFn filter,
  int filterArg
);
```

核心逻辑（伪代码）：

```c
keys = Heap_Alloc(4 * recordCount);
ctx  = sub_88226E0(memTalkHandle);          // 返回结构体里 +0x1A48 是记录数组基址
base = *(u8 **)(ctx + 0x1A48);

outN = 0;
for (i = 0; i < recordCount; i++) {
  rec = (ActionRecord *)(base + 0x14 * i);
  if (!rec) continue;
  if (rec->sortKey == 0) continue;

  id = rec->templateId;
  if (id >= 0x6D6) continue;
  if (off_8A4B45C[id].prefix[0] == 0) continue;

  if (filter && !filter(rec, filterArg)) continue;

  outRecs[outN] = rec;
  keys[outN]    = rec->sortKey;
  outN++;
}

sub_882032C(keys, outN, outRecs);           // 用 keys 做排序键重排 outRecs
Heap_Free(keys);
return outN;
```

结论：`sub_890F2C4` 更像是“构建可显示动作列表”的过滤器/排序器，依赖 `off_8A4B45C[id].prefix` 来判断是否有可用的显示模板。

## off_8A4B45C 的“拼接”方式（真正发生在 sub_890FA58）

`sub_890FA58`（已在 IDA 里把签名改成更直观的形式）：

```c
int __fastcall sub_890FA58(
  const ActionRecord *rec,
  char *outBuf,
  unsigned int outBufSize,
  char delimiter,
  char style
);
```

行为要点：
- 先 `memset(outBuf, 0, outBufSize)`（`sub_89A492C`）
- 把 `off_8A4B45C[rec->templateId].prefix` 当作模板写入输出
- 若 `suffix` 非空：可选插入 `delimiter`，然后继续把 `suffix` 模板追加写入
- 最后补 `\\0`，并返回 `写入字节数 + 1`

## 模板语法（sub_890FB64 / sub_890FC64）

- 模板字符串以单字节为主，但代码对 `signed char < 0` 的情况按“连续两字节”透传，典型是 Shift-JIS。
- 遇到字符 `$`（0x24）会把后面一个字符作为占位符类型：
  - `$a`：展开 `rec->maskA`
  - `$b`：展开 `rec->maskB`
- 展开最终调用 `sub_890F7B4(mask, style, dst)`，生成“按键/位掩码”的文本表示。

## 完整调用链：从候选记录到“完整句子”

这一整套逻辑可以按 3 层理解：

1) **选一条 ActionRecord（候选 -> 选择）**
- `MemTalk_SelectActionRecord(ctx, filter, arg, interactive)`（原 `sub_890FDEC`）
  - `sub_8821FF4(ctx->memTalkIndex)` 得到记录数 N
  - `MemTalk_BuildCandidateRecords(outList, N, memTalkIndex, filter, arg)`（原 `sub_890F2C4`）过滤 + sortKey 排序
  - `interactive!=0`：`MemTalk_BuildMenuEntryList(candidates, count, ctx)`（原 `sub_890F410`）分页显示（12 项/页），返回用户选中的 `ActionRecord*`
  - `interactive==0`：`MemTalk_PickActionRecord_NonInteractive(candidates, count)`（原 `sub_890F5F4`）自动挑一条（倾向从列表末尾向前扫，遇到“mask 不冲突”的条目以 50% 概率选中，否则继续）

2) **菜单里每条记录的“短摘要”（用于列表显示）**
- `MemTalk_BuildMenuEntryList` 对每条候选记录：
  - 若 `(rec->maskA & rec->maskB & 0xFFFFFF) == 0` 才会生成摘要（否则跳过/显示为空）
  - `MemTalk_FormatActionSummary25(rec, styleBit, out25)`（原 `sub_890F6B8`）构造 25 字节以内的短句：
    - `maskA` 不包含 `styleBit`（当前角色）时：前缀为 `"<maskA>が"`（例如“アスカが”/“自分が”）
    - 总是追加 `"<maskB><expandedTemplate>"`（其中 expandedTemplate 来自 `MemTalk_ExpandActionTemplate`）

3) **最终“整句话”的拼装（含时间/地点/换行）**
- `MemTalk_ShowMemorySentence(ctx, rec, verbSjis)`（原 `sub_890F080`）决定使用“简化句式”还是“详细句式”
  - 简化句式（`rec==NULL` 或 `maskA/maskB` 在低 24 位有交集）：
    - 文本：`"$aは、昔の出来事を%s。"`（`%s = verbSjis`）
  - 详细句式（`rec!=NULL` 且 `(maskA & maskB & 0xFFFFFF)==0`）：
    - 计算：
      - `timePhrase = MemTalk_FormatTimePhrase(rec)`：例如“今朝”“夜中”“１週間程前”“ずいぶん昔”
      - `placePhrase = MemTalk_FormatLocationPhrase(rec, styleBit)`：例如“シンジの部屋で”“ネルフの食堂で”
      - `maskAText = MemTalk_FormatCharacterMask(rec->maskA, styleBit, ...)`：例如“自分”“アスカ”“アスカたち”
      - `maskBText = MemTalk_FormatCharacterMask(rec->maskB, styleBit, ...)`
      - `expanded = MemTalk_ExpandActionTemplate(rec, outBuf, 0x46, '\\n', styleBit)`
    - 文本骨架（注意 `$a/$b/$n` 是给文本引擎后续替换的 token，本函数通过 `sprintf` 只是把它们拼进缓冲区）：
      - `"$aは%s、\n%sの出来事を%s。$n%s%s%s\n%s%sを。"`
      - 参数依次是：
        1. `"$bに"` 或空串（取决于 `ctx->targetBit` 是否存在）
        2. `timePhrase`
        3. `verbSjis`
        4. `placePhrase`
        5. `maskAText`（仅在 `maskA` 不包含 `styleBit` 时输出，否则为空）
        6. `"が"`（仅在输出了 `maskAText` 时输出，否则为空）
        7. `maskBText`
        8. `expanded`

## 语义层：详细句式的完整拼接流程（从 ActionRecord 到屏幕）

这一节只讲“详细句式”（`rec!=NULL` 且 `(rec->maskA & rec->maskB & 0xFFFFFF)==0`）在语义上是怎么形成最终日语文本的；它包含两层占位符系统：

1) **模板层占位符**：出现在 `off_8A4B45C[templateId].{prefix,suffix}` 中的 `$a/$b`  
   - `$a` => 用 `rec->maskA` 生成“参与者短语”（`自分/シンジ/アスカたち/...`）
   - `$b` => 用 `rec->maskB` 生成“参与者短语”
   - 这一步在 `MemTalk_ExpandActionTemplate` / `MemTalk_AppendExpandedTemplate` 内完成，直接写入 `expanded` 字符串缓冲区

2) **文本引擎 token**：出现在最终句式骨架字符串里的 `$a/$b/$c/$n/$m`  
   - `$a/$b/$c` 在显示前由文本引擎替换为“角色名”（不是 mask 短语）
   - `$n/$m` 是控制符，用于分段/换行与显示同步

### Step 0：输入变量（可视作一条“记忆记录”）

输入来自两部分：

- `ctx`（`ActionListContext`）
  - `speakerBit`：当前视角/说话者（也是 `styleBit`）
  - `targetBit`：可选的“对话/思考对象”，用于 `$b` 的名字替换
- `rec`（`ActionRecord`）
  - `maskA/maskB`：模板层 `$a/$b` 的参与者掩码
  - `templateId`：选择动作模板
  - `unk0`：时间戳（以分钟为单位的概率很高：代码里存在 `% 0x5A0`=1440 的判定）
  - `unkC` 的高字节：`locationId`（用于地点短语）

### Step 1：生成 expanded（模板展开结果）

```C
typedef int (*ExpandActionTemplateFn)(const MemTalkActionRecord *rec, char *outBuf, unsigned int outBufSize, char delimiter, int styleBit);
```

取模板：

- `pair = off_8A4B45C[rec->templateId]`
- `prefix = pair.prefix`
- `suffix = pair.suffix`（可能为空字符串）

展开规则：

- 逐字节扫描模板（Shift-JIS 双字节直接透传）
- 遇到 `$`：
  - `$a` => 把 `rec->maskA` 转换为参与者短语，写入输出
  - `$b` => 把 `rec->maskB` 转换为参与者短语，写入输出
- `suffix` 非空时，会在 `prefix` 与 `suffix` 之间插入 `delimiter`
  - **详细句式调用时 delimiter=10（`'\\n'`）**，所以两段模板在最终细节显示里会被强制换行分隔

参与者短语（mask -> 文本）的语义：

- 如果 `mask` 包含当前 `styleBit`（即 `mask & (1<<styleBit) != 0`）：输出 `"自分"`
- 否则：从 bit=1 开始找到第一个置位的 bit，输出该 bit 对应角色名（例如 `"シンジ"`）
- 如果 `mask` 除“被选中 bit”外还有其他置位：追加 `"たち"` 表示复数/同伴（例如 `"アスカたち"`）

### Step 2：生成时间短语 timePhrase

调用 `MemTalk_FormatTimePhrase(rec)`，逻辑可以概括为：

- 若 `rec->unk0==0` 或 `now-rec->unk0 < 0`：返回默认 `"以前"`
- 否则 `delta = now - rec->unk0`（分钟差）
  - 如果 `rec->unk0` 与 `now` 在同一天：
    - 遍历 `TimeOfDayRule[6]`，找到满足条件的第一条并返回其短语  
      条件：`delta` 在 `[min,max)` 且 `rec->unk0 % 1440 < threshold`
  - 如果不在同一天：
    - 遍历 `TimeAgoRule[14]`（阈值升序），找到第一条 `delta < threshold` 的短语
    - 若超过最大阈值：返回默认 `"以前"`

### Step 3：生成地点短语 placePhrase

调用 `MemTalk_FormatLocationPhrase(rec, styleBit)`：

- `locationId = HIBYTE(rec->unkC)`
- 若 `sub_8822698(styleBit) == locationId`：返回 `"ここで"`
- 否则：
  - 若 `1 <= locationId < 81`：返回 `off_8A4EB0C[locationId]`（内容形如 `"シンジの部屋で"`）
  - 否则：返回空字符串

### Step 4：组装详细句式骨架（sprintf 拼接）

在 `MemTalk_ShowMemorySentence(ctx, rec, verbSjis)` 内生成一段带 token 的 Shift-JIS 字符串 `buffer`：

骨架（原文，地址 `0x89D5368`）：

```
$aは%s、
%sの出来事を%s。$n%s%s%s
%s%sを。
```

注意：这一步只是 `sprintf` 拼接，`$a/$b/$n` 并未替换。

8 个 `%s` 参数的语义（按顺序）：

1. `targetPrefix`：若 `ctx->targetBit != 0` 则为 `"$bに"`，否则为空字符串
2. `timePhrase`：来自 Step 2（例如 `"今朝"`、`"１週間程前"`）
3. `verbSjis`：外部传入的“回忆动词/操作动词”（例如菜单里的 `"よく思い出す"` 系列）
4. `placePhrase`：来自 Step 3（例如 `"ここで"`、`"ネルフの食堂で"` 或空）
5. `maskAText`：若 `rec->maskA` 不包含 `styleBit` 则输出 Step 1 的 maskA 短语，否则为空
6. `"が"`：仅在第 5 项非空时输出，否则为空
7. `maskBText`：Step 1 的 maskB 短语
8. `expanded`：Step 1 的模板展开结果（可能包含换行）

### Step 5：文本引擎 token 替换与显示同步（$a/$b/$n/$m）

最终显示调用：`sub_882FD7C(0, ctx->speakerBit, ctx->targetBit, 0, buffer)`，内部会调用 `sub_882EED4` 做 token 处理。

token 处理的关键语义（根据 `sub_882EED4` 反编译）：

- 扫描 `buffer`，遇到普通字符直接拷贝到内部临时缓冲并累计
- 遇到 `$x`（0x24 后跟一字节）：
  - `$a`：用 `sub_8839434(mode, speakerBit)` 获取“speaker 名字字符串”，写入输出
  - `$b`：用 `sub_8839434(mode, targetBit)` 获取“target 名字字符串”，写入输出
  - `$c`：用 `sub_8839434(mode, a4)` 获取第三个名字（在本句式里 a4 固定为 0）
  - `$n`：先把当前临时缓冲提交显示，然后进入下一段显示流程（并会在需要时吞掉紧随其后的 `\\n`）
  - `$m`：类似 `$n` 的一次“提交显示/重置”控制符，但会额外重置某些状态（在本句式里通常不出现）

因此，“模板层的 `$a/$b`”与“文本引擎层的 `$a/$b`”完全不同：  
前者变成 `"自分/アスカたち"` 这种 **参与者短语**，后者变成 `"シンジ/アスカ"` 这种 **角色名**。

### Step 6：额外尾句（speakerBit==16 的特殊分支）

`MemTalk_ShowMemorySentence` 在显示完主句后，如果 `ctx->speakerBit==16 && ctx->targetBit!=0`，还会根据 `sub_8871778(5)` 的结果追加一条“但是没理解/没听清/不太懂”的尾句：

- `0x89D52F4`：`しかし%sは\nよく理解できなかった。`
- `0x89D5318`：`しかし%sは\nうまく聞き取れなかった。`
- `0x89D533C`：`しかし%sは\nよくわからなかった。`

这里的 `%s` 由 `sub_88395D8(ctx->targetBit)` 取目标角色名（同样属于“名字替换层”）。

### 关键字符串（Shift-JIS 解码后）

- `aA_0 @ 0x89D52DC`：`$aは、昔の出来事を%s。`
- `aA_1 @ 0x89D5368`：`$aは%s、\n%sの出来事を%s。$n%s%s%s\n%s%sを。`
- `"$bに" @ 0x89D535C`：`$bに`（当 `ctx->targetBit!=0` 时作为第 1 个 `%s` 参数插入）
- `"自分" @ 0x89D53B0`
- `"たち" @ 0x89D53A8`
- `"が" @ 0x89D5364`
- `rec->locationId == current` 时用于“ここで”：`unk_89D53B8 @ 0x89D53B8` = `ここで`
- `speakerBit==16` 尾句（Shift-JIS）：
  - `0x89D52F4`：`しかし%sは\nよく理解できなかった。`
  - `0x89D5318`：`しかし%sは\nうまく聞き取れなかった。`
  - `0x89D533C`：`しかし%sは\nよくわからなかった。`

## 时间/地点短语表

### 时间（MemTalk_FormatTimePhrase）

- `0x8A4ECC0`：`MemTalk_TimeOfDayRule[6]`（同一天内按分钟范围选“早朝/今朝/昼間/夕方/今夜/夜中”等）
- `0x8A4EC50`：`MemTalk_TimeAgoRule[14]`（跨天/长时间差阈值：`たった今 / ちょっと前 / 1時間前 / 昨日 / 1週間程前 / ずいぶん昔`）
- `0x8A4ED20`：默认兜底短语：`以前`

#### 同一天（TimeOfDayRule[6]，base=0x8A4ECC0）

每项结构：`{minDelta, maxDelta, minuteOfDayThreshold, phrase}`  
满足 `delta` 在 `[minDelta, maxDelta)` 且 `rec->unk0%1440 < threshold` 时命中。

| idx | minDelta | maxDelta | threshold | 短语 |
|---:|---:|---:|---:|---|
| 0 | 120 | 1200 | 240 | 夜中 |
| 1 | 120 | 720 | 420 | 早朝 |
| 2 | 120 | 720 | 600 | 今朝 |
| 3 | 120 | 720 | 960 | 昼間 |
| 4 | 120 | 720 | 1140 | 夕方 |
| 5 | 120 | 720 | 1560 | 今夜 |

#### 跨天/较久之前（TimeAgoRule[14]，base=0x8A4EC50）

每项结构：`{deltaThreshold, phrase}`，找到第一个 `delta < deltaThreshold` 的短语。

| idx | deltaThreshold(分钟) | 短语 |
|---:|---:|---|
| 0 | 10 | たった今 |
| 1 | 30 | ちょっと前 |
| 2 | 60 | １時間前 |
| 3 | 120 | ２時間前 |
| 4 | 1440 | 昨日 |
| 5 | 2880 | おととい |
| 6 | 5760 | ３日程前 |
| 7 | 10080 | １週間程前 |
| 8 | 20160 | ２週間程前 |
| 9 | 43200 | ひと月程前 |
| 10 | 86400 | ふた月程前 |
| 11 | 259200 | 半年前 |
| 12 | 525600 | １年前 |
| 13 | 2147483647 | ずいぶん昔 |

### 地点（MemTalk_FormatLocationPhrase）

- `0x8A4EB0C`：`const char *[81]`，索引为 `rec->locationId`，内容是“...で”的地点短语（例如“シンジの部屋で”“ネルフの発令所で”“セントラルドグマで”等）。

#### 地点表完整列表（off_8A4EB0C[0..80]，Shift-JIS 解码）

> `locationId==0` 为“非法/未命名 map 名”；当 `locationId` 与当前场景一致时会输出 `"ここで"` 而不是表项内容。

| id | 短语 |
|---:|---|
| 0 | イリーガルマップ名 |
| 1 | マンションのリビングで |
| 2 | ダイニングキッチンで |
| 3 | シンジの部屋で |
| 4 | シンジの部屋で |
| 5 | アスカの部屋で |
| 6 | ミサトの部屋で |
| 7 | マンションの洗面所で |
| 8 | 総司令公務室で |
| 9 | ネルフの発令所で |
| 10 | ミサトの執務室で |
| 11 | ネルフの食堂で |
| 12 | リツコの研究室で |
| 13 | 加持の個室で |
| 14 | ネルフ自販機コーナーで |
| 15 | ネルフ自販機コーナーで |
| 16 | （呼称未定義予備１）で |
| 17 | ネルフの大浴場で |
| 18 | セントラルドグマで |
| 19 | レイのマンションで |
| 20 | レイのマンションで |
| 21 | 学校の教室で |
| 22 | 学校の廊下で |
| 23 | コンビニで |
| 24 | 地上の廃墟で |
| 25 | 心の迷宮で |
| 26 | 初号機のケイジで |
| 27 | ミサトの執務室で |
| 28 | （呼称未定義マップＥＶＡケイジ）で |
| 29 | （呼称未定義マップ予備宿舎）で |
| 30 | （呼称未定義マップ予備５）で |
| 31 | 第３新東京市で |
| 32 | ネルフ本部で |
| 33 | 自宅で |
| 34 | （呼称未定義マップ自室）で |
| 35 | ベランダで |
| 36 | ベランダで |
| 37 | ベランダで |
| 38 | マンションの外で |
| 39 | どこかで |
| 40 | （呼称未定義マップ予備１６）で |
| 41 | レイのマンションで |
| 42 | ミサトのマンションで |
| 43 | リツコの研究室で |
| 44 | ミサトの執務室で |
| 45 | ミサトの執務室で |
| 46 | リツコの研究室で |
| 47 | コンビニの外で |
| 48 | 学校の屋上で |
| 49 | 高台の公園で |
| 50 | 新箱根湯本駅で |
| 51 | 零号機のケイジで |
| 52 | 弐号機のケイジで |
| 53 | 参号機のケイジで |
| 54 | 四号機のケイジで |
| 55 | ネルフの本部脇で |
| 56 | カヲルの宿舎で |
| 57 | 加持の宿舎で |
| 58 | シンジの宿舎で |
| 59 | レイの宿舎で |
| 60 | アスカの宿舎で |
| 61 | ミサトの宿舎で |
| 62 | リツコの宿舎で |
| 63 | トウジの宿舎で |
| 64 | 青葉の宿舎で |
| 65 | 日向の宿舎で |
| 66 | マヤの宿舎で |
| 67 | 冬月の宿舎で |
| 68 | ゲンドウの宿舎で |
| 69 | 学校への通学路で |
| 70 | 本部のエスカレーターで |
| 71 | 第７実験場で |
| 72 | 実験場で |
| 73 | 射撃訓練所で |
| 74 | 幹部宿舎前の通路で |
| 75 | 職員宿舎前の通路で |
| 76 | パイロット宿舎前廊下で |
| 77 | （呼称未定義マップ遠景廃墟）で |
| 78 | （呼称未定義マップ遠景屋上）で |
| 79 | （呼称未定義マップ遠景公園）で |
| 80 | （呼称未定義マップ遠景駅）で |

## 菜单动词/提示词（off_8A4ED24 / off_8A4ED34）

`MemTalk_BuildMenuEntryList` 的翻页/确认提示会使用以下字符串（Shift-JIS 解码）：

| idx | 字符串 |
|---:|---|
| 0 | よく思い出す |
| 1 | よくよく思い出す |
| 2 | よくよくよく思い出す |
| 3 | 真剣に思い出す |
| 4 | もう一度考え直す |
| 5 | ●戦闘プレイ開始 |
| 6 | （NULL） |
| 7 | ●戦闘デモテスト |

`off_8A4ED34`（同值）：`もう一度考え直す`

## “完整可能产生的日语列表”：如何从逻辑上生成（用于翻译/校对）

“把所有可能出现的最终句子逐条列出来”在组合意义上会爆炸（不同 `maskA/maskB/styleBit/targetBit/time/location` 会产生大量排列）。但从翻译角度，真正需要覆盖的是 **稳定的日语原子库 + 组合规则**：

1) **稳定原子库（应当逐条翻译/映射）**
   - 句式骨架：`aA_0`、`aA_1`、`"$bに"`、三条 `しかし%sは...` 尾句
   - 时间短语：`TimeOfDayRule` + `TimeAgoRule` + `以前`
   - 地点短语：`off_8A4EB0C[1..80]` + `ここで`
   - 角色名：`sub_8839434(0, bit)` / `sub_88395D8(bit)` 的名字表
   - 模板表：`off_8A4B45C[0..0x6D5]` 的 `prefix/suffix`（含模板层 `$a/$b`）

2) **组合规则（不需要逐条翻译，只需要实现）**
   - mask 参与者短语生成规则（自分/首个置位/たち）
   - 时间选择规则（同一天/跨天阈值）
   - 地点选择规则（ここで / 表项 / 空）
   - 详细句式 8 个 `%s` 参数的插入规则（targetBit 是否存在、maskA 是否含 styleBit）
   - token 替换规则（$a/$b/$n/$m）

3) **导出“模板原文列表”的最直接方法**
   - 遍历 `templateId=0..0x6D5`：
     - 读取 `pair.prefix/pair.suffix` 的 Shift-JIS 字符串
     - 若 `prefix[0]==0` 则跳过（该模板通常不会被候选列表使用）
   - 这一步得到的是“模板原文库”（仍含 `$a/$b`），它是翻译最核心的工作量

## 翻译成中文：建议与落地策略

这里给出两类建议：**句式层面的自然中文** 与 **工程落地（如何 patch）**。

### 句式层面（把日语语气翻成自然中文）

1) `自分` 的中文建议优先译为“我”
   - 因为它是相对 `styleBit` 的第一人称指代，不是客观的“自己”
2) `たち` 的中文建议优先译为“等人/一行”
   - 直接译“们”会遇到性别与数量不确定的问题；“等人/一行”更稳
3) `...で` 的地点短语建议译成“在……/于……”
   - 原表项都带“で”，中文可以统一成“在X”或“于X”，避免重复助词感
4) `…を。` 的中文建议按“（这件）事/这件事。”处理
   - 详细句式下半部分本质是“细节条目”而不是完整谓语句
5) 详细句式第一行的 `"$bに"` 可在中文里改写为“对$b/向$b/关于$b”
   - 这里的 `$b` 是“目标角色名”，不是 mask 短语

一个更贴近中文的语义等价写法（仅做表达建议，不等同于直接替换字面）：

- 主句：`$a（对/关于$b）回想起了%s的往事，%s。`
- 细节：`%s%s%s\n%s%s。`  
  其中 `%s%s%s` 可理解为“地点 +（可选）施事 + 受事”，最后 `%s%s` 是“展开的动作模板 +（这件）事”

### 工程落地（patch 时该怎么翻）

1) **优先按“原子库”翻译，而不是试图枚举所有组合句子**
   - 句式骨架/时间表/地点表/模板表/角色名表分别翻译
2) **保证 `sprintf` 的参数数量与顺序不变**
   - `aA_1` 必须保留 8 个 `%s`，否则会造成栈参数错位导致崩溃或乱码
3) **区分两套 `$a/$b`：模板层 vs 文本引擎层**
   - 模板层 `$a/$b` => 参与者短语（会出现“自分/たち”）
   - 引擎层 `$a/$b` => 角色名（不会出现“たち”）
4) **如果你要做“中文化重排”，推荐 patch 点**
   - 轻量：替换 `aA_0/aA_1/\"$bに\"/\"が\"/\"自分\"/\"たち\"/地点表/时间表` 的字符串内容（需要解决中文字体与编码）
   - 更强：在 `MemTalk_ShowMemorySentence` 里改 `sprintf` 的格式字符串与参数组织，使中文语序自然（同样需要编码/字体方案）
   - 最强：绕开模板表，按 `templateId` 做中文模板映射（稳定、可控，且能针对中文语序单独写模板）

## 额外观察：字符串池

- `off_8A4B45C` 指向的字符串并不一定被 IDA 自动识别为 string item（很多字符串紧密排列在同一池里）。
- 例如 `0x089D0128` 的前 4 字节是 `00 00 00 00`，因此它可作为“空字符串”地址；`prefix[0]` 的判定会把这种条目视作不可用。

## ActionRecord：maskA/maskB 的写入点与约束

这里整理“maskA/maskB 是在哪里被写入 ActionRecord 的”（记录生成/入内存）以及由此带来的组合约束。

### 1) 真正的写入点：`ActionRecordContext_InsertRecord` (0x881F3E8)

该函数负责在 `ActionRecordContext` 内选择一个 20 字节槽位并落盘字段（入内存）：

- 选择槽位：`ActionRecordContext_SelectInsertSlot` (0x881F678)
- 逐字段写入（按 `ActionRecord` 偏移）：
  - `+0x00 u32 timestamp`：传入的时间戳（上层可传 `-1` 表示“当前时间”，由封装处理）
  - `+0x04 u32 maskA`
  - `+0x08 u32 maskB`
  - `+0x0C u8 valid`：写入 `1`
  - `+0x0D u8 locationId`
  - `+0x0E u16 templateId`
  - `+0x10 u8 type`：来自封装参数（同一字段在不同系统含义可能不同）
  - `+0x12 u16 sortKey`：由权重/参数计算后写入，用于后续选择/排序

上层“mask 组合是否可能出现”，首先取决于谁调用了这个写入点、以及传入的 mask 是如何构造出来的。

### 2) 两个主入口：mask 直传 vs actorId 转 mask

**A. `ActionRecord_InsertRecord_WithMasks` (0x88243A4)**

- 行为：补默认值后直接把 `maskA/maskB` 原样传给 `ActionRecordContext_InsertRecord`。
- 结论：如果你在内存里看到 `maskA/maskB` 出现“低位多 bit 同时置位”的组合，通常只可能来自这类“直传 mask”的路径（或存档读入等效路径）。

**B. `ActionRecord_InsertRecord_WithActorIds` (0x88244A0)**

- 行为：把 `actorId/targetId` 转成 mask 后再写入。
- 转换规则（对 `actorId` 与 `targetId` 分别应用）：
  - `id == 0`：mask = 0
  - `1 <= id <= 16`：mask = `1 << id`
  - `id >= 17`：mask = `(id - 16) << 24`
- 直接推论：走这条路径时，`maskA/maskB` 的低 24 位不可能出现“多 bit 组合”（要么 0，要么单一 bit）。

`ActionRecord_InsertRecord_WithActorIdsEx` (0x88245F8) 是带额外参数的变体，mask 构造逻辑与上面一致。

### 3) pid=3 的“暂存/恢复”链路（全局缓冲区）

这条链路和你观察到的“不可能组合”经常相关，因为它会把整块 context 从全局缓冲区覆盖回 pid=3 的 context，并且做一次记录过滤。

- 暂存：`ActionRecord_StagePid3ContextToGlobal` (0x8825B94)
  - 从 `ActionRecord_GetContextForPid(3)` 取出 `ActionRecordContext*`
  - 把整块 `0x1A50` 字节复制到 `g_ActionRecordPid3StageCtx`（全局）
- 恢复并过滤：`ActionRecord_RestorePid3ContextFromStage_KeepType3` (0x8825BF8)
  - 用 `g_ActionRecordPid3StageCtx` 覆盖回 pid=3 的 `ActionRecordContext`（并保留 context 尾部少量 dword 字段）
  - 遍历 `ctx->records`，把 `valid != 3` 的记录全部置无效（`valid=0`），只保留 `valid==3` 的记录

因此：即便某些组合“曾经被写入”，也可能在这条恢复/过滤路径上被直接清掉，最终你在候选列表/渲染侧就再也看不到它。  

MemTalk_ExpandActionTemplate 不是“整句生成器”，它只做一件事：按
  rec->templateId 取事件模板的两段文本，然后把模板内部的 $a/$b 展开成 maskA/
  maskB 的人物短语。

  签名大致是：

  int MemTalk_ExpandActionTemplate(
      const ActionRecord *rec,
      char *outBuf,
      unsigned int outBufSize,
      char delimiter,
      char styleBit
  );

  行为流程：

  memset(outBuf, 0, outBufSize);

  entry = templateTable[rec->templateId]; // 每项是 {prefix, suffix}

  n = AppendExpandedTemplate(
      outBuf,
      entry.prefix,
      outBufSize,
      rec->maskA,
      rec->maskB,
      styleBit
  );

  if (entry.suffix[0] != '\0') {
      if (delimiter != 0)
          outBuf[n++] = delimiter;

      n += AppendExpandedTemplate(
          outBuf + n,
          entry.suffix,
          outBufSize - n,
          rec->maskA,
          rec->maskB,
          styleBit
      );
  }

  outBuf[n] = '\0';
  return n + 1; // 含末尾 NUL

  模板表 stru_8A4B45C 的结构是：

  struct {
      const char *prefix;
      const char *suffix;
  } templates[0x6D6];

  例如你刚才的 templateId=901：

  prefix = "に、たわいもない話を"
  suffix = "したこと"

  在最终句里调用时：

  MemTalk_ExpandActionTemplate(rec, outBuf, 0x46, '\n', speakerBit);

  所以结果是：

  に、たわいもない話を
  したこと

  如果是菜单摘要调用，delimiter=0，结果就会变成：

  に、たわいもない話をしたこと

  AppendExpandedTemplate 的展开规则很简单：

  - 普通 ASCII 字节：原样复制。
  - Shift-JIS 高位字节：按双字节复制，避免把日文第二字节误判成 $。
  - 遇到 $：读取下一个字符作为占位符。
  - $a：调用 MemTalk_FormatCharacterMask(rec->maskA, styleBit, dst)。
  - $b：调用 MemTalk_FormatCharacterMask(rec->maskB, styleBit, dst)。
  - 其他 $x：不输出任何东西。

  这里要特别区分两种 $a/$b：

  模板内部的 $a/$b
  => ExpandActionTemplate 立刻替换成 maskA/maskB 人名短语。

  最终显示字符串里的 $a/$b/$n
  => 留给 sub_882FD7C 文本引擎处理，表示说话者、目标、换行等。

  MemTalk_FormatCharacterMask 的规则是：

  mask 为空或只有 bit0        => 空字符串
  mask 包含 styleBit          => "自分"
  mask 不含 styleBit          => 取第一个置位角色名
  mask 还有其他置位角色       => 追加 "たち"

  所以在你的样本里：

  styleBit = speakerBit = 2
  maskA = 00010000 => ペンペン
  maskB = 00000004 => 自分

  然后外层 MemTalk_ShowMemorySentence 再把它组合成：

  {place}{maskA}{が}{maskB}{expanded}を。

  代入后就是：

  マンションのリビングでペンペンが
  自分に、たわいもない話を
  したことを。

  对汉化最重要的结论是：ExpandActionTemplate 产物通常不是完整中文事件，而是日语
  谓语尾巴，往往期待外层先拼上 maskB：

  maskB + "に、たわいもない話を\nしたこと"
  maskB + "を無視したこと"
  maskB + "の態度にヘコんだこと"
  maskB + "からの誘いを\n拒絶したこと"

  所以它很适合用来“研究原始模板语法”，但不适合直接作为中文最终拼接方案。中文应该
  把 templateId 对应成完整事件模板，比如：

  901:
  日语展开: {B}に、たわいもない話を / したこと
  中文模板: 和{B}闲聊

  然后外层再生成：

  {speaker}回想起一小时前在公寓客厅里，PenPen和自己闲聊的事。