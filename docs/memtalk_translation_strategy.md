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
```

中文模板：

```json
{ "subject": "auto", "zh": "向{B}搭话" }
{ "subject": "auto", "zh": "接近{B}" }
{ "subject": "auto", "zh": "警告{B}" }
```

完整例句：

```text
碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。
碇真嗣回想起昨天在学校教室里绫波接近明日香的事。
```

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
