# Memory Talk 本地化方案

## 原始游戏的实现

### 拼接所需的元数据

原始游戏的对话拼接主要依赖两部分元数据：
- 预制的模板
    - 位置：`0x08A4B45C`
    - 类型：`ActionTemplatePair`数组，每个元素包含 `prefix` 和 `suffix` 两个字符串
    - 作用：`templateId -> (prefix, suffix)` 的映射表，范围 < 0x6D6。这个表里存的字符串是日语骨架，包含固定文本和 `$a/$b` 占位符。
- `ActionRecord`：
    - 动作发生的时间戳 `timestamp` 字段
    - `templateId` 字段。用于索引模板。
    - `$a`和`$b`对应人物的掩码标志 `maskA/maskB` 字段
- 上下文
    - `ctx->speakerBit`：掩码，表示说话者
    - `ctx->targetBit`：掩码，表示听话者

### 生成句子的流程

#### 句子

1. 简化句式：`"$aは、昔の出来事を%s。"`（`%s = verbSjis`）
2. 详细句式：`"$aは%s、\n%sの出来事を%s。$n%s%s%s\n%s%sを。"`
    - 参数依次是：
        1. `"$bに"` 或空串（取决于 `ctx->targetBit` 是否存在）
        2. `timePhrase`
        3. `verbSjis`
        4. `placePhrase`
        5. `maskAText`（仅在 `maskA` 不包含 `speakerBit` 时输出，否则为空）
        6. `"が"`（仅在输出了 `maskAText` 时输出，否则为空）
        7. `maskBText`
        8. `expanded`

这个为空可以看下面这个例子：

```
speaker=真嗣, maskA=真嗣, maskB=明日香, template=2
=> 碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。

speaker=真嗣, maskA=绫波, maskB=明日香, template=2
=> 碇真嗣回想起今早在 NERV 食堂绫波向明日香搭话的事。
```

> ```text
> $aは%s、
> %sの出来事を%s。$n%s%s%s
> %s%sを。
> ```
> 详细句式的模板

前面两行是主句，比较好翻译，大致解释
- `$aは%s、`：以 `$a`（说话者）为主语。如果存在`ctx->targetBit`，则以收听者`$b`为宾语
- `%sの出来事を%s。`：描述事件发生的时间（timePhrase）的状语和谓语（verbSjis，如回忆）
后面两行是补充说明，基本格式是`{place}{maskA}{が}{maskB}{expanded}を。`，比较难翻译，主要解释
- place：事件发生的地点状语，通常是一个短语，例如`マンションのリビングで`
- maskA：如`ペンペン`
- 可选的`"が"`
- maskB：如`自分`
- expanded：模板展开的结果，通常是一个描述事件细节的短句，例如`に、たわいもない話をしたこと`

此处的maskA和maskB来源于过去发生的事件（Action）的记录，分别对应事件中的两个参与者。
对应的字符串生成规律（MemTalk_FormatCharacterMask）如下：

- mask 为空或只有 bit0        => 空字符串
- mask 包含 styleBit          => "自分"
- mask 不含 styleBit          => 取第一个置位角色名
- mask 还有其他置位角色       => 追加 "たち"

```
$aは、
１時間前の出来事を思い出した。
$nマンションのリビングでペンペンが
自分に、たわいもない話を
したことを。
```

翻译为中文大改就是
```
{speaker}
回想起一小时前
在公寓客厅里，PenPen
和自己闲聊的事。
```

不难理解，此处的maskA和maskB其实很适合整合到模板中。而不应该向现在这样硬性假定顺序进行拼接。

在部分Template内部，存在`$a`和`$b`标记，但是会被替换为Action记录中的MaskA和MaskB的文本（ExpandActionTemplate）即参与者短语（自分/アスカたち），而不是上下文中的说话者和听话者。AppendExpandedTemplate 的展开规则如下：

- 普通 ASCII 字节：原样复制。
- Shift-JIS 高位字节：按双字节复制，避免把日文第二字节误判成 $。
- 遇到 $：读取下一个字符作为占位符。
- $a：调用 MemTalk_FormatCharacterMask(rec->maskA, styleBit, dst)。
- $b：调用 MemTalk_FormatCharacterMask(rec->maskB, styleBit, dst)。
- 其他 $x：不输出任何东西。

`MemTalk_ShowMemorySentence` 在显示完主句后，如果 `ctx->speakerBit==16 && ctx->targetBit!=0`，还会根据 `sub_8871778(5)` 的结果追加一条“但是没理解/没听清/不太懂”的尾句：

- `0x89D52F4`：`しかし%sは\nよく理解できなかった。`
- `0x89D5318`：`しかし%sは\nうまく聞き取れなかった。`
- `0x89D533C`：`しかし%sは\nよくわからなかった。`




#### 菜单列表里的短摘要

# 附录

## 动词列表（位置？）

> off_8A4ED24? off_8A4ED34?


| idx | 字符串 |
|---:|---|
| 0 | よく思い出す |
| 1 | よくよく思い出す |
| 2 | よくよくよく思い出す |
| 3 | 真剣に思い出す |
| 4 | もう一度考え直す |

上面这些似乎是在拼接菜单时使用的。有待进一步研究。

似乎没有固定的位置，AI目前只发现了三个词语。

```C
if (verbSjis == (const char *)0x089CF0C8) {
    // 思い出した
    // 中文外层动词：回想起
} else if (verbSjis == (const char *)0x089CF47C) {
    // 話した
    // 中文外层动词：说起 / 谈起
} else if (verbSjis == (const char *)0x089CF484) {
    // 聞き取った
    // 中文外层动词：听到 / 听清了 / 得知
}
```

## 位置列表（off_8A4EB0C[0..80]，Shift-JIS 解码）

- MemTalk_FormatLocationPhrase

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

# 修改方案

是的。核心应该替换 MemTalk_ShowMemorySentence，地址 0x0890F080，原名 sub_890F080。

这是最终“记忆句子”真正拼出来并送进文本引擎的函数。你要做自然中文语序，应该在这里接管：

void *MemTalk_ShowMemorySentence(
    ActionListContext *ctx,
    const ActionRecord *rec,
    const char *verbSjis
);

它现在做的是：

简单句:
$aは、昔の出来事を%s。

详细句:
$aは$bに、
%sの出来事を%s。$n
{place}{maskA}{が}{maskB}{expandedTemplate}を。

中文化后不要再走这个日语骨架，而是在 sub_890F080 里改成：

{speaker}{talkTargetPart}{verbPart}{timePart}{placePart}{eventClause}的事。

也就是：

碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。
碇真嗣向明日香回想起昨天在学校教室里绫波无视自己的事。

不建议优先替换 MemTalk_ExpandActionTemplate / sub_890FA58。那个函数只知道 prefix/suffix/$a/$b，它太底层，不知
道整句中文语序、时间、地点、说话对象，也不知道何时该省略主语。你如果只替换它，还是会被外层日语骨架卡住。

完整 patch 面建议是：

| 目的 | 替换函数 |
|---|---|
| 最终详细句/简单句/尾句 | MemTalk_ShowMemorySentence at 0x0890F080 |
| 菜单列表里的短摘要 | MemTalk_FormatActionSummary25 at 0x0890F6B8，或更彻底替换 MemTalk_BuildMenuEntryList at
0x0890F410 |
| 候选记录筛选排序 | 不替换，保留 sub_890F2C4 |
| 原始模板 prefix/suffix 展开 | 不作为主 patch 点，最多当参考 |

如果你只关心点进记忆后的最终句子，替换 0x0890F080 就够了。

如果你还想菜单列表也中文化，就要处理 0x0890F6B8。但注意：原始菜单摘要只有大约 0x19 字节限制，中文很容易爆。认
真做的话，最好替换 MemTalk_BuildMenuEntryList，让它使用你自己的短摘要缓冲，而不是硬塞进原来的 25 字节。

0x0890F080 的新逻辑大概应该是：

CnMemTalk_ShowMemorySentence(ctx, rec, verb) {
    if (!(speaker == player || target == player))
        return;

    if (!rec || (rec->maskA & rec->maskB & 0xFFFFFF) != 0) {
        build_chinese_simple_sentence(...);
    } else {
        event = RenderChineseEvent(
            rec->templateId,
            rec->maskA,
            rec->maskB,
            ctx->speakerBit
        );

        time = RenderChineseTime(rec);
        place = RenderChinesePlace(rec, ctx->speakerBit);

        build_chinese_detail_sentence(
            speaker,
            targetBit,
            verb,
            time,
            place,
            event
        );
    }

    sub_882FD7C(0, ctx->speakerBit, ctx->targetBit, 0, buffer);

    if (ctx->speakerBit == 16 && ctx->targetBit != 0)
        show_chinese_tail_sentence(...);
}

关键是 RenderChineseEvent() 查你那张 templateId -> 中文模板 表，例如：

2:  "向{B}搭话"
4:  "无视{B}"
7:  "冷淡地回应{B}"
17: "因{B}的态度受打击"

然后根据 maskA/maskB/styleBit 填 {A}、{B}、{A_ref}。

实测案例：templateId=901

调试日志字段：

```
speakerBit=2, targetBit=0, verb=思い出した
maskA=00010000 => ペンペン
maskB=00000004 => 自分
time=１時間前
place=マンションのリビングで
expanded=に、たわいもない話を / したこと
```

原始日语实际拼接：

```
$aは、
１時間前の出来事を思い出した。$nマンションのリビングでペンペンが
自分に、たわいもない話を
したことを。
```

中文设计不要保留 `{B}に...したことを` 这种日语尾巴。这个模板应归为交谈类 `B_NI`，中文事件模板可以写：

```
templateId 899/900/901: "和{B}闲聊"
```

所以这条完整句建议是：

```
{speaker}回想起一小时前在公寓客厅里，PenPen和自己闲聊的事。
```

所以一句话结论：

最终句子替换 sub_890F080；菜单摘要另替换 sub_890F6B8 或 sub_890F410；不要动 sub_890F2C4，也不要把 sub_890FA58
当主战场。

# 翻译方案

首先解决模板的问题。现有的模板包括：

```
maskB + に...
maskB + を...
maskB + の...
maskB + から...
maskB + と...
```

举例：
| 模板 | 角色 |
|---|---|
| {B}に話した | 说话对象 |
| {B}を無視した | 直接受事 |
| {B}の態度 | 所属者 |
| {B}から離れた | 来源/远离对象 |
| {B}と勉強した | 共同行动者 |
| {B}への視線を逸らしたこと | 视线转移对象 |

分类：
- 交谈类（B_NI）：{B}に話した
- 关系类（B_WO）：{B}を無視した
- 属性类（B_NO）：{B}の態度
- 视线类（B_EYELID）：{B}への視線を逸らしたこと
- 其他类（B_KARA/TO）：{B}から離れた、{B}と勉強した
- NO_B：没有 {B} 的模板，一人で悩んだ
