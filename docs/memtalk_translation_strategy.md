# MemTalk 中文化组合翻译方案

这份方案只讨论 MemTalk 的组合句怎么翻，不再重复函数逆向细节。逆向事实见 `docs/sub_890F2C4_off_8A4B45C.md`。

## 总结

不要按最终句子枚举翻译。正确做法是按 `ActionRecord` 的语义槽位生成中文：

```text
speaker        当前说话/回想者，来自 ctx->speakerBit
talkTarget     当前谈话对象，来自 ctx->targetBit，可为空
timePhrase     记忆发生时间，来自 rec->timestamp
placePhrase    记忆发生地点，来自 rec->locationId
actorPhrase    行动发起者，来自 rec->maskA
objectPhrase   行动对象/相关人，来自 rec->maskB
eventTemplate  事件模板，来自 rec->templateId
verbPhrase     菜单动词，如“よく思い出す”
```

推荐最终中文骨架：

```text
{speaker}{talkTargetPart}{verbPart}{timePart}{placePart}{eventClause}。
```

例：

```text
碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。
碇真嗣向明日香回想起昨天在学校教室里绫波无视自己的事。
```

这里的 `eventClause` 应该由 `templateId` 的中文模板生成，而不是继续沿用日语的 `maskBText + prefix + suffix + を。`。

## 为什么不能直接翻现有拼接

原始详细句骨架是：

```text
$aは%s、
%sの出来事を%s。$n%s%s%s
%s%sを。
```

它的后半句实际拼成：

```text
{place}{actor?}{が}{object}{expandedTemplate}を。
```

这适合日语，因为 `object` 可以直接接 `に/を/の/から/と` 等助词：

```text
アスカに話題を振ったこと
アスカを無視したこと
アスカの態度にヘコんだこと
アスカからの誘いを拒絶したこと
```

中文不能稳定地把对象永远放在模板前面，所以模板必须改成带占位符的中文模板：

```json
{
  "2":   { "subject": "auto", "zh": "向{B}搭话" },
  "4":   { "subject": "auto", "zh": "无视{B}" },
  "17":  { "subject": "auto", "zh": "因{B}的态度受打击" },
  "102": { "subject": "auto", "zh": "拒绝{B}的邀请" }
}
```

`subject:auto` 表示：如果 `maskA` 不是当前 speaker，就在事件前补 `actorPhrase`；如果 `maskA` 是当前 speaker，就省略主语。

## 第一层分类：显示分支

### 1. 简单句

触发条件：

```c
rec == NULL || (rec->maskA & rec->maskB & 0xFFFFFF) != 0
```

这时没有可靠的事件细节，只知道“回想过去”。建议翻为泛化句：

```text
{speaker}{talkTargetPart}{verbPart}过去的事。
```

例：

```text
碇真嗣回想起过去的事。
碇真嗣向明日香仔细回想过去的事。
```

### 2. 详细句

触发条件：

```c
rec != NULL && (rec->maskA & rec->maskB & 0xFFFFFF) == 0
```

建议生成：

```text
{speaker}{talkTargetPart}{verbPart}{timePart}{placePart}{eventClause}的事。
```

例：

```text
碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。
碇真嗣向明日香认真回想起昨天在学校教室里绫波拒绝自己的邀请的事。
```

实测样本：`templateId=901`

日志关键字段：

```text
speakerBit=2
targetBit=0
verb=思い出した
maskA=00010000 => ペンペン
maskB=00000004 => 自分
timePhrase=１時間前
placePhrase=マンションのリビングで
templateId=901
expanded=に、たわいもない話を / したこと
```

原始日语 detail 拼接结果：

```text
$aは、
１時間前の出来事を思い出した。$nマンションのリビングでペンペンが
自分に、たわいもない話を
したことを。
```

把换行和日语名词化还原后是：

```text
$a は 1 小时前在公寓客厅里，ペンペンが自分にたわいもない話をしたこと を思い出した。
```

中文不要照搬成“自己に、……したことを”。推荐把 `に、たわいもない話を / したこと` 归入 `B_NI` 里的“说话/告知对象”子类，中文模板写成：

```json
{ "subject": "auto", "zh": "和{B}闲聊", "summary": "和{B}闲聊" }
```

这一条完整渲染建议：

```text
{speaker}回想起一小时前在公寓客厅里，PenPen和自己闲聊的事。
```

如果想更贴近原文方向性，也可以写成：

```text
{speaker}回想起一小时前在公寓客厅里，PenPen对自己说了些无关紧要的话。
```

但作为通用模板，`和{B}闲聊` 更适合多数角色组合，也能避免 `{A}对自己说...` 这种中文里略显僵硬的表达。

### 3. 尾句

触发条件：

```c
ctx->speakerBit == 16 && ctx->targetBit != 0
```

三条尾句可以独立翻：

```text
但是{target}没能理解。
但是{target}没能听清。
但是{target}还是不明白。
```

## 第二层分类：参数槽位

### talkTargetPart

来自 `ctx->targetBit`。这是“说给谁/对谁回想”，不是事件里的 `maskB`。

```text
targetBit == 0  => ""
targetBit != 0  => "向{target}"
```

例：

```text
碇真嗣回想起昨天在学校教室里无视明日香的事。
碇真嗣向明日香回想起昨天在学校教室里无视绫波的事。
```

### actorPhrase

来自 `rec->maskA`。

```text
maskA 包含 speakerBit  => 事件主语可省略；内部引用用“自己”
maskA 单人且不是 speaker => 角色名
maskA 多人且不是 speaker => 第一个角色名 + “等人”
```

例：

```text
speaker=真嗣, maskA=真嗣, maskB=明日香, template=2
=> 碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。

speaker=真嗣, maskA=绫波, maskB=明日香, template=2
=> 碇真嗣回想起今早在 NERV 食堂绫波向明日香搭话的事。

speaker=真嗣, maskA=绫波+美里, maskB=明日香, template=2
=> 碇真嗣回想起今早在 NERV 食堂绫波等人向明日香搭话的事。
```

### objectPhrase

来自 `rec->maskB`。它在中文里不要固定拼到模板前面，而要由每个中文模板决定位置。

```text
maskB == 0                 => 模板不用 {B}
maskB 单人                 => 角色名
maskB 多人                 => 第一个角色名 + “等人”
maskB 包含 speakerBit      => “自己”或“自己等人”，按语境处理
```

例：

```text
template=4, zh="无视{B}"
maskB=明日香
=> 无视明日香

template=4, zh="无视{B}"
maskB=明日香+绫波
=> 无视明日香等人

template=35, zh="独自烦恼"
maskB=0
=> 独自烦恼
```

### timePart

时间短语建议翻成能直接接在“回想起”后面的状语。

```text
たった今       刚才
ちょっと前     不久前
１時間前       一小时前
２時間前       两小时前
昨日           昨天
おととい       前天
３日程前       大约三天前
１週間程前     大约一周前
２週間程前     大约两周前
ひと月程前     大约一个月前
ふた月程前     大约两个月前
半年前         半年前
１年前         一年前
ずいぶん昔     很久以前
以前           以前
早朝           清晨
今朝           今早
昼間           白天
夕方           傍晚
今夜           今晚
夜中           深夜
```

例：

```text
回想起今早在学校教室里……
回想起大约一周前在 NERV 食堂……
```

### placePart

地点短语不要保留日语的 `で`，统一做成中文状语。

```text
ここで          在这里
ネルフの食堂で  在 NERV 食堂
空字符串        省略
```

例：

```text
回想起今早在这里向明日香搭话的事。
回想起昨天在 NERV 食堂绫波无视明日香的事。
回想起以前独自烦恼的事。
```

## 第三层分类：模板翻译法

`scripts/memtalk_data.json` 里有 1750 个模板，其中有效模板约 771 个。建议把每个有效 `templateId` 翻成一个中文事件模板，并标注主语策略。

### A. B に：对象是接受者/方向

原文形态：

```text
{B}に話題を振ったこと
{B}に近づいたこと
{B}に警告したこと
{B}に、たわいもない話を / したこと
```

中文模板：

```json
{ "subject": "auto", "zh": "向{B}搭话" }
{ "subject": "auto", "zh": "接近{B}" }
{ "subject": "auto", "zh": "警告{B}" }
{ "subject": "auto", "zh": "和{B}闲聊" }
```

完整例句：

```text
碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。
碇真嗣回想起昨天在学校教室里绫波接近明日香的事。
碇真嗣回想起一小时前在公寓客厅里PenPen和自己闲聊的事。
```

注意：`B_NI` 不是都机械翻成“向{B}”。如果动作核心是 `話をした`、`相談した`、`話しかけた` 这类交谈行为，中文经常更自然地写作“和{B}闲聊/找{B}商量/和{B}搭话”。只有 `警告した`、`報告した`、`言った` 这类方向性强的动作，才优先用“向/对/给{B}...”。

### B. B を：对象是直接受事

原文形态：

```text
{B}を無視したこと
{B}を抱きしめたこと
{B}を心配したこと
```

中文模板：

```json
{ "subject": "auto", "zh": "无视{B}" }
{ "subject": "auto", "zh": "抱住{B}" }
{ "subject": "auto", "zh": "担心{B}" }
```

完整例句：

```text
碇真嗣回想起昨天在学校教室里无视明日香的事。
碇真嗣向绫波回想起以前在这里明日香担心自己的事。
```

### C. B の：对象是所属/状态来源

原文形态：

```text
{B}の態度にヘコんだこと
{B}の様子を観察したこと
{B}のふがいない態度を叱ったこと
```

中文模板：

```json
{ "subject": "auto", "zh": "因{B}的态度受打击" }
{ "subject": "auto", "zh": "观察{B}的样子" }
{ "subject": "auto", "zh": "训斥{B}没出息的态度" }
```

完整例句：

```text
碇真嗣回想起昨天在 NERV 食堂因明日香的态度受打击的事。
碇真嗣回想起今早在学校教室里美里训斥明日香没出息的态度的事。
```

### D. B から：对象是来源/施事

原文形态：

```text
{B}から身を離したこと
{B}からの誘いを拒絶したこと
{B}からの問いにわからないと答えたこと
```

中文模板：

```json
{ "subject": "auto", "zh": "从{B}身边离开" }
{ "subject": "auto", "zh": "拒绝{B}的邀请" }
{ "subject": "auto", "zh": "回答{B}的问题说自己不知道" }
```

完整例句：

```text
碇真嗣回想起前天在学校教室里从明日香身边离开的事。
碇真嗣回想起不久前在这里绫波拒绝明日香邀请的事。
```

### E. B と / B との：对象是共同参与者

原文形态：

```text
{B}と指を絡めあったこと
{B}との会話を切り上げたこと
{B}と一緒に勉強したこと
```

中文模板：

```json
{ "subject": "auto", "zh": "和{B}十指相扣" }
{ "subject": "auto", "zh": "结束和{B}的谈话" }
{ "subject": "auto", "zh": "和{B}一起学习" }
```

完整例句：

```text
碇真嗣回想起以前在学校教室里和明日香一起学习的事。
碇真嗣回想起昨天在这里绫波结束和明日香谈话的事。
```

### F. 无 B 或模板自带对象

原文形态：

```text
一人で悩んだこと
入浴したこと
テレビを観たこと
コンビニのトイレに行ったこと
```

中文模板：

```json
{ "subject": "auto", "zh": "独自烦恼" }
{ "subject": "auto", "zh": "洗澡" }
{ "subject": "auto", "zh": "看电视" }
{ "subject": "auto", "zh": "去了便利店厕所" }
```

完整例句：

```text
碇真嗣回想起昨晚在家里独自烦恼的事。
碇真嗣回想起以前在这里绫波看电视的事。
```

### G. 两段 prefix/suffix

原始模板常是两段：

```text
{B}に、そっけない返事を / したこと
{B}との会話を / 切り上げたこと
{B}からの誘いを / 拒絶したこと
```

中文不要保留这个换行边界，直接合成自然动作：

```json
{ "subject": "auto", "zh": "冷淡地回应{B}" }
{ "subject": "auto", "zh": "结束和{B}的谈话" }
{ "subject": "auto", "zh": "拒绝{B}的邀请" }
```

完整例句：

```text
碇真嗣回想起今早在 NERV 食堂冷淡地回应明日香的事。
碇真嗣回想起昨天在学校教室里绫波拒绝明日香邀请的事。
```

## 第四层分类：模板内部 $a/$b

有效模板里只有少量模板含内部 `$a/$b`。这些不要依赖原始模板展开，建议单独给中文模板。

占位符建议：

```text
{A}      行动者，用于完整主语
{A_ref}  maskA 的引用形式。若 maskA 是 speaker，通常是“自己”
{B}      maskB 的引用形式
```

已知内部占位符模板：

```json
{
  "113":  { "subject": "auto",   "zh": "向{B}询问对{A_ref}的好感" },
  "116":  { "subject": "auto",   "zh": "向{B}询问躲着{A_ref}的理由" },
  "300":  { "subject": "auto",   "zh": "没从{B}那里拿到零花钱，于是向{B}抱怨" },
  "383":  { "subject": "inside", "zh": "{A}看到{B}沉默的样子，自己也沉默了" },
  "673":  { "subject": "auto",   "zh": "收到{B}的出院报告后关心{B}" },
  "676":  { "subject": "auto",   "zh": "问{B}：{A_ref}不在时是不是很辛苦" },
  "1109": { "subject": "auto",   "zh": "看到{B}对加持感到愤慨，于是安抚{B}" },
  "1353": { "subject": "auto",   "zh": "把{B}想要的道具给了{B}" }
}
```

例：

```text
speaker=真嗣, maskA=真嗣, maskB=明日香, template=113
=> 碇真嗣回想起以前在这里向明日香询问对自己的好感的事。

speaker=真嗣, maskA=绫波, maskB=明日香, template=113
=> 碇真嗣回想起以前在这里绫波向明日香询问对绫波的好感的事。

speaker=真嗣, maskA=绫波, maskB=明日香, template=383
=> 碇真嗣回想起以前在这里绫波看到明日香沉默的样子，自己也沉默了的事。
```

`subject:inside` 表示中文模板自己处理 `{A}`，外层不要再自动补主语。

## 菜单摘要

菜单列表原始摘要只有 25 字节左右，中文很容易超。建议单独做短摘要，不要复用完整句。

推荐格式：

```text
{A短}->{B短} {短动作}
{A短} {短动作}
{短动作}
```

例：

```text
真嗣->明日香 搭话
绫波->明日香 拒绝邀请
独自烦恼
```

如果继续用原始 `MemTalk_FormatActionSummary25`，需要控制每条摘要非常短；更好的 patch 是扩大摘要缓冲和菜单项显示宽度。

## 实施建议

最稳的实现路径：

1. 保留原始 `ActionRecord` 筛选、排序、时间/地点选择逻辑。
2. 新增 `MemTalk_RenderChineseEvent(rec, styleBit, out, cap)`。
3. 维护一个 `templateId -> ChineseTemplate` 表，表项至少包含：

```c
typedef enum {
  CN_SUBJECT_AUTO,
  CN_SUBJECT_INSIDE,
  CN_SUBJECT_NONE
} CnSubjectPolicy;

typedef struct {
  uint16_t templateId;
  CnSubjectPolicy subjectPolicy;
  const char *zh;       // 含 {A}/{A_ref}/{B} 这类占位符
  const char *summary;  // 可选，菜单短摘要
} CnMemTalkTemplate;
```

4. 详细句不要再用日语骨架的 `maskBText + expanded`，而是：

```text
eventClause = RenderChineseEvent(templateId, maskA, maskB, styleBit)
sentence = speaker + talkTargetPart + verbPart + timePart + placePart + eventClause + "的事。"
```

5. 简单句和尾句作为独立分支处理。

这样翻译工作量变成：

```text
角色名表
时间短语表
地点短语表
菜单动词表
templateId 有效模板表约 771 条
少量内部 $a/$b 模板的特殊处理
```

不需要枚举所有 `speaker/target/time/place/mask/template` 的最终组合。

## 逐模板处理工作表

我把所有有效模板生成了一份工作表：

- `docs/memtalk_template_translation_workbook.tsv`：适合用表格软件打开和批量筛选。
- `docs/memtalk_templates_zh_draft.jsonc`：适合后续直接变成 patch 数据表；内容是标准 JSON，只是扩展名避开仓库的 `*.json` ignore。
- 生成脚本：`scripts/memtalk_generate_translation_workbook.py`

重新生成：

```sh
python3 scripts/memtalk_generate_translation_workbook.py
```

当前有效模板共 771 条，自动分类结果：

| 分类 | 数量 | 处理核心 |
|---|---:|---|
| `B_NI` | 362 | `{B}に...`，按“向/对/给{B}...”处理 |
| `B_NO` | 110 | `{B}の...`，按“{B}的...”或“因{B}...”处理 |
| `NO_B` | 99 | 不依赖 `{B}`，只翻事件本身 |
| `B_KARA` | 56 | `{B}から...`，按“从{B}/被{B}/因为{B}”择一 |
| `B_KARA_NO` | 40 | `{B}からの...`，按“来自{B}的...”处理 |
| `B_TO` | 30 | `{B}と...`，按“和{B}...”处理 |
| `B_WO` | 29 | `{B}を...`，按直接宾语处理 |
| `B_TO_NO` | 18 | `{B}との...`，按“和{B}的...”处理 |
| `B_NI_TAISHITE` | 16 | `{B}に対して...`，按“对{B}...”处理 |
| `INTERNAL_AB` | 8 | 模板内部含 `$a/$b`，必须手写 |
| `B_HENO` | 3 | `{B}への...`，按“对{B}的/给{B}的...”处理 |

工作表字段含义：

| 字段 | 含义 |
|---|---|
| `id` | `templateId` |
| `same_as_id` | 若该模板文本重复，可复用此 id 的译文 |
| `duplicate_count` | 同一日文模板出现次数 |
| `category` | 自动语法分类 |
| `subject_policy` | 主语策略；目前大多是 `auto` |
| `jp_prefix` | 原始 ActionTemplate 的 prefix |
| `jp_suffix` | 原始 ActionTemplate 的 suffix |
| `jp_with_b` | 若原模板依赖 `maskB`，补上 `{B}` 后的原始日语结构 |
| `zh_prefix` | 中文 ActionTemplate 的 prefix |
| `zh_suffix` | 中文 ActionTemplate 的 suffix |

`zh_prefix` / `zh_suffix` 用统一的工作表占位符：

```text
{A} = rec->maskA 的参与者短语
{B} = rec->maskB 的参与者短语
```

未知条目的中文列默认留空，不再把分类 rule 或机器 seed 混进译表。若中文最终只需要一段模板，可以把完整中文事件放在 `zh_prefix`，`zh_suffix` 留空。实际 patch 若复用原展开器，再把 `{A}` / `{B}` 映射为模板层 `$a` / `$b`。

逐条校对时的推荐步骤：

1. 先按 `same_as_id` 过滤重复项。重复模板直接复用 canonical id 的译文。
2. 按 `category` 分批处理，不要按 id 顺序硬翻。
3. 分别填写 `zh_prefix` / `zh_suffix`；要引用 ActionRecord 的参与者时用 `{A}` / `{B}`。
4. 对有 `same_as_id` 的重复项，优先跟 canonical id 保持一致。
5. 菜单摘要另做短译，不再塞进这个 ActionTemplate 译表。

一个典型条目：

```tsv
id  category  jp_prefix             jp_suffix  zh_prefix   zh_suffix
901 B_NI      に、たわいもない話を したこと    和{B}闲聊
```

渲染时先把 `{B}` 替换为 `maskB` 的参与者短语，再按 `subject_policy` 处理外层主语：

```text
碇真嗣回想起一小时前在公寓客厅里和明日香闲聊的事。
碇真嗣回想起一小时前在公寓客厅里PenPen和自己闲聊的事。
```

这是一个 **PSP/日文游戏文本 Hook 的调试日志**，看起来是你装的 `MemTalkDebug` 在拦截“回忆/传闻/对话记录”类文本时打印出来的。

核心结论：**Hook 成功了，而且它抓到了两种文本生成分支：simple 和 detail。**

---

## 它在干嘛

第一行：

```txt
MemTalkDebug install:
gameTextAddr=08804040
addrMode=ida_absolute
gameBaseDelta=00000000
hook=0890F080
replacement=08BEBF7C
```

意思是：

* `gameTextAddr=08804040`：游戏文本相关函数或地址。
* `hook=0890F080`：被 Hook 的原函数地址。
* `replacement=08BEBF7C`：你的替换函数地址。
* `addrMode=ida_absolute`：地址按 IDA 看到的绝对地址解释。
* `gameBaseDelta=0`：当前运行地址和 IDA 地址没有偏移，说明地址基准大概率对上了。

---

## MemTalk #1：没有详细记录，走 simple 分支

```txt
rec: <null>
branch: rec=no low24Overlap=00000001 => simple
```

这里 `rec` 是空的，所以没有查到详细记忆记录，于是走了 `simple` 模板。

动词：

```txt
verbSjis hex=8E 76 82 A2 8F 6F 82 B5 82 BD
```

这串 Shift-JIS 解码后是：

```txt
思い出した
```

也就是“想起来了”。

simple 模板大概是：

```txt
$aは、昔の出来事を%s。
```

填入 `%s = 思い出した` 后变成：

```txt
$aは、昔の出来事を思い出した。
```

其中 `$a` 应该是游戏自己的名字/角色 token，还没经过最终 token engine 解析。

---

## MemTalk #2：有记录，走 detail 分支

```txt
rec=08B7A014 ... valid=1 locationId=1 templateId=901 recordType=61
branch: rec=yes low24Overlap=00000000 => detail
```

这次找到了记录 `rec`，而且 `valid=1`，所以走详细文本分支。

它提取到的字段大概是：

```txt
timePhrase = １時間前
placePhrase = マンションのリビングで
maskAText = ペンペン
maskBText = 自分
verb = 思い出した
```

`detail.expanded` 这一段：

```txt
に、たわいもない話を
したこと
```

大概是记录内容的后半句，意思类似：

```txt
和……聊了些无关紧要的话这件事
```

最终 `detail.buffer.beforeTokenEngine` 拼出来的大意是：

```txt
$aは、
１時間前の出来事を思い出した。
$nマンションのリビングでペンペンが
自分に、たわいもない話を
したことを。
```

自然中文大概是：

```txt
$a 想起了 1 小时前发生的事。
在公寓客厅里，ペンペン 和自己聊了些无关紧要的话。
```

`$a`、`$n` 是游戏内部控制符：

* `$a`：可能代表当前说话者/主语名字。
* `$n`：可能代表换行或特殊格式控制。
* 这些会在后面的 `TokenEngine` 里被替换/解释。

---

## 为什么 `.raw` 是乱码？

比如：

```txt
verbSjis.raw="�v���o����"
```

这是因为日志查看器或打印函数把 **Shift-JIS 日文文本当成 UTF-8/ANSI 错误解码** 了。

但 hex 是对的：

```txt
8E 76 82 A2 8F 6F 82 B5 82 BD
```

按 Shift-JIS 解码就是：

```txt
思い出した
```

所以不是文本坏了，是日志显示编码不对。

---

## 你这段日志说明什么？

它说明：

1. **Hook 已经进来了。**
2. **文本地址和函数地址大概率正确。**
3. **simple 分支能拼出基础句子。**
4. **detail 分支能读到记忆记录 rec，并正确拼出时间、地点、人物、事件内容。**
5. 当前最大问题不是 Hook，而是 **日志输出编码显示问题**，以及你可能还需要确认 `$a` / `$n` 这些 token 在最终显示前是否被正确交给原游戏文本引擎处理。

如果你是在调翻译补丁或文本替换，这段日志整体是“好消息”：拦截点和结构解析基本是通的。
