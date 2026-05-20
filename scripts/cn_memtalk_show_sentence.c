/*
 * cn_memtalk_show_sentence.c
 *
 * Purpose
 * -------
 * Replacement implementation sketch for the game's MemTalk_ShowMemorySentence
 * at 0x0890F080.
 *
 * This file is meant to be copied/adapted into the PSP patch/plugin side.
 * It keeps the original game's record selection, text window, typewriter
 * effect, and wait behavior, but replaces the Japanese sentence builder with
 * a Chinese semantic renderer:
 *
 *   speaker + talkTarget + verb + time + place + event + "的事。"
 *
 * Example outputs
 * ---------------
 *   碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。
 *   碇真嗣向明日香认真回想起昨天在学校教室绫波丽无视自己的事。
 *   但是明日香没能听清。
 *
 * Encoding note
 * -------------
 * The readable Chinese literals in this file are for implementation clarity.
 * In the actual game patch, these strings must be encoded in the same custom
 * EVA SJIS byte encoding that your text renderer accepts. A practical path is:
 *
 *   1. Edit docs/memtalk_templates_zh_draft.jsonc.
 *   2. Validate/encode strings with app.parser.tools.common.to_eva_sjis().
 *   3. Generate a C table with escaped byte strings or load it from a binary
 *      resource.
 *
 * If you compile this file as UTF-8 literals without an encoding conversion,
 * the game may not render the Chinese correctly.
 */

#include <stddef.h>
#include <stdint.h>

/*
 * If this code is built into a plugin loaded at a different base address,
 * define CN_MEMTALK_REBASE(x) to your NEW_ADDR(x) macro before including or
 * compiling this file.
 */
#ifndef CN_MEMTALK_REBASE
#define CN_MEMTALK_REBASE(x) (x)
#endif

#define CN_GAME_FN(type, addr) ((type)CN_MEMTALK_REBASE(addr))
#define CN_GAME_PTR(type, addr) ((type)CN_MEMTALK_REBASE(addr))

/*
 * Original game helpers used by the replacement. These are intentionally kept
 * as calls into the original engine:
 *
 * - sub_882FD7C: opens the text window, expands $a/$b/$c/$n/$m, displays text,
 *   waits, and closes the window.
 * - sub_8828580: returns current player/controlled character bit.
 * - MemTalk_FormatTimePhrase: keeps the original time threshold logic.
 * - MemTalk_FormatLocationPhrase: keeps the original "here/table/empty" logic.
 * - sub_8871778: preserves the original random tail-sentence branch.
 */
typedef void *(*CnGame_ShowTokenizedTextFn)(int group, int speakerBit, int targetBit, int thirdBit, char *text);
typedef int (*CnGame_GetCurrentPlayerBitFn)(void);
typedef const char *(*CnGame_FormatTimePhraseFn)(const void *rec);
typedef const char *(*CnGame_FormatLocationPhraseFn)(const void *rec, uint8_t styleBit);
typedef int (*CnGame_RandNFn)(int n);

#define Game_ShowTokenizedText CN_GAME_FN(CnGame_ShowTokenizedTextFn, 0x0882FD7C)
#define Game_GetCurrentPlayerBit CN_GAME_FN(CnGame_GetCurrentPlayerBitFn, 0x08828580)
#define Game_FormatTimePhrase CN_GAME_FN(CnGame_FormatTimePhraseFn, 0x0890F8B8)
#define Game_FormatLocationPhrase CN_GAME_FN(CnGame_FormatLocationPhraseFn, 0x0890F9F0)
#define Game_RandN CN_GAME_FN(CnGame_RandNFn, 0x08871778)

enum {
  CN_MEMTALK_TEMPLATE_COUNT = 0x6D6,
  CN_MEMTALK_LOCATION_COUNT = 81,
  CN_MEMTALK_TEXT_CAP = 512,
  CN_MEMTALK_PHRASE_CAP = 96
};

/*
 * Correct ActionRecord layout from the original code:
 *
 *   +0x00 u32 timestamp
 *   +0x04 u32 maskA
 *   +0x08 u32 maskB
 *   +0x0C u8  valid/type-ish byte
 *   +0x0D u8  locationId
 *   +0x0E u16 templateId
 *   +0x10 u8  recordType
 *   +0x11 u8  unknown
 *   +0x12 u16 sortKey
 *
 * IDA disassembly confirmation:
 *   MemTalk_ExpandActionTemplate reads lhu 0xE(rec) for templateId.
 *   MemTalk_FormatLocationPhrase reads lbu 0xD(rec) for locationId.
 */
typedef struct CnActionRecord {
  uint32_t timestamp;
  uint32_t maskA;
  uint32_t maskB;
  uint8_t valid;
  uint8_t locationId;
  uint16_t templateId;
  uint8_t recordType;
  uint8_t unk11;
  uint16_t sortKey;
} CnActionRecord;

/*
 * The original MemTalk context is much larger. For this replacement we only
 * need the two byte fields proven by the original function:
 *
 *   +0x51 speakerBit
 *   +0x52 targetBit
 */
static uint8_t CnMemTalk_GetSpeakerBit(const void *ctx) {
  return *((const uint8_t *)ctx + 0x51);
}

static uint8_t CnMemTalk_GetTargetBit(const void *ctx) {
  return *((const uint8_t *)ctx + 0x52);
}

typedef enum CnSubjectPolicy {
  CN_SUBJECT_AUTO = 0,   /* Prefix actor when maskA is not current speaker. */
  CN_SUBJECT_INSIDE = 1, /* Template contains {A}; do not auto-prefix actor. */
  CN_SUBJECT_NONE = 2    /* Never prefix actor. Useful for fixed/system events. */
} CnSubjectPolicy;

typedef struct CnMemTalkTemplate {
  uint16_t templateId;
  CnSubjectPolicy subjectPolicy;
  const char *eventTemplate;
  const char *summaryTemplate;
} CnMemTalkTemplate;

typedef struct CnPtrPhrase {
  uintptr_t originalPtr;
  const char *cn;
} CnPtrPhrase;

static size_t CnStrLen(const char *s) {
  size_t n = 0;
  if (!s) return 0;
  while (s[n]) n++;
  return n;
}

static int CnStrStartsWith(const char *s, const char *prefix) {
  size_t i = 0;
  if (!s || !prefix) return 0;
  while (prefix[i]) {
    if (s[i] != prefix[i]) return 0;
    i++;
  }
  return 1;
}

static size_t CnAppendByte(char *dst, size_t cap, size_t pos, uint8_t b) {
  if (!dst || cap == 0) return pos;
  if (pos + 1 >= cap) return pos;
  dst[pos++] = (char)b;
  dst[pos] = '\0';
  return pos;
}

static size_t CnAppendCStr(char *dst, size_t cap, size_t pos, const char *s) {
  if (!dst || cap == 0 || !s) return pos;
  while (*s && pos + 1 < cap) {
    dst[pos++] = *s++;
  }
  dst[pos] = '\0';
  return pos;
}

/*
 * Copy a string that may contain custom-SJIS multibyte characters. Placeholders
 * are ASCII sequences like {B}; when a high-bit byte is seen, copy the next byte
 * together so a trail byte cannot be misread as a placeholder.
 */
static size_t CnAppendTemplateText(
    char *dst,
    size_t cap,
    size_t pos,
    const char *tmpl,
    const char *actor,
    const char *actorRef,
    const char *object) {
  const uint8_t *p = (const uint8_t *)tmpl;

  if (!tmpl) return pos;

  while (*p) {
    if (*p >= 0x80) {
      pos = CnAppendByte(dst, cap, pos, *p++);
      if (*p) pos = CnAppendByte(dst, cap, pos, *p++);
      continue;
    }

    if (CnStrStartsWith((const char *)p, "{A_ref}")) {
      pos = CnAppendCStr(dst, cap, pos, actorRef);
      p += 7;
      continue;
    }
    if (CnStrStartsWith((const char *)p, "{A}")) {
      pos = CnAppendCStr(dst, cap, pos, actor);
      p += 3;
      continue;
    }
    if (CnStrStartsWith((const char *)p, "{B}")) {
      pos = CnAppendCStr(dst, cap, pos, object);
      p += 3;
      continue;
    }

    pos = CnAppendByte(dst, cap, pos, *p++);
  }

  return pos;
}

static const char *CnMemTalk_NameByBit(uint8_t bit) {
  static const char *const names[] = {
      "",
      "碇真嗣",
      "明日香",
      "绫波丽",
      "葛城美里",
      "碇源堂",
      "冬月耕造",
      "赤木律子",
      "伊吹摩耶",
      "日向诚",
      "青叶茂",
      "加持良治",
      "洞木光",
      "铃原冬二",
      "相田剑介",
      "渚薰",
      "Pen Pen",
  };

  if (bit < (uint8_t)(sizeof(names) / sizeof(names[0]))) return names[bit];
  return "";
}

static int CnMemTalk_FirstSetBit1To16(uint32_t mask) {
  int bit;
  for (bit = 1; bit <= 16; bit++) {
    if ((mask & (1u << bit)) != 0) return bit;
  }
  return -1;
}

/*
 * Convert the game's participant mask to a Chinese phrase.
 *
 * Original Japanese rule:
 *   - if mask contains styleBit, use "自分"
 *   - otherwise use the first set character bit
 *   - if more bits remain, append "たち"
 *
 * Chinese rule:
 *   - if mask contains styleBit, use selfWord ("自己" in references)
 *   - otherwise use the first set character name
 *   - if more bits remain, append "等人"
 */
static void CnMemTalk_MaskToPhrase(
    uint32_t mask,
    uint8_t styleBit,
    const char *selfWord,
    char *out,
    size_t outCap) {
  int chosenBit = -1;
  uint32_t rest;
  size_t pos = 0;

  if (!out || outCap == 0) return;
  out[0] = '\0';

  if ((mask & 0xFFFFFFFEu) == 0) return;

  if (styleBit < 32 && (mask & (1u << styleBit)) != 0) {
    chosenBit = styleBit;
    pos = CnAppendCStr(out, outCap, pos, selfWord ? selfWord : "自己");
  } else {
    chosenBit = CnMemTalk_FirstSetBit1To16(mask);
    if (chosenBit < 0) return;
    pos = CnAppendCStr(out, outCap, pos, CnMemTalk_NameByBit((uint8_t)chosenBit));
  }

  rest = mask & ~(1u << chosenBit);
  if (rest != 0) {
    pos = CnAppendCStr(out, outCap, pos, "等人");
  }
}

static int CnMemTalk_MaskContainsStyle(uint32_t mask, uint8_t styleBit) {
  if (styleBit >= 32) return 0;
  return (mask & (1u << styleBit)) != 0;
}

/*
 * Time phrase translation by original returned pointer.
 * These addresses come from scripts/memtalk_data.json.
 */
static const CnPtrPhrase g_cnTimePhrases[] = {
    {0x089D51A8, "刚才"},
    {0x089D51B4, "不久前"},
    {0x089D51C0, "一小时前"},
    {0x089D51CC, "两小时前"},
    {0x089D51D8, "昨天"},
    {0x089D51E0, "前天"},
    {0x089D51EC, "大约三天前"},
    {0x089D51F8, "大约一周前"},
    {0x089D5204, "大约两周前"},
    {0x089D5210, "大约一个月前"},
    {0x089D521C, "大约两个月前"},
    {0x089D5228, "半年前"},
    {0x089D5230, "一年前"},
    {0x089D5238, "很久以前"},
    {0x089D5244, "深夜"},
    {0x089D524C, "清晨"},
    {0x089D5254, "今早"},
    {0x089D525C, "白天"},
    {0x089D5264, "傍晚"},
    {0x089D526C, "今晚"},
    {0x089D5274, "以前"},
};

static const char *CnMemTalk_TranslatePtrPhrase(
    const CnPtrPhrase *items,
    size_t count,
    const char *original,
    const char *fallback) {
  size_t i;
  uintptr_t ptr = (uintptr_t)original;
  for (i = 0; i < count; i++) {
    if (ptr == CN_MEMTALK_REBASE(items[i].originalPtr)) return items[i].cn;
  }
  return fallback;
}

static const char *CnMemTalk_TimePhrase(const CnActionRecord *rec) {
  const char *jp = Game_FormatTimePhrase((const void *)rec);
  return CnMemTalk_TranslatePtrPhrase(
      g_cnTimePhrases,
      sizeof(g_cnTimePhrases) / sizeof(g_cnTimePhrases[0]),
      jp,
      "以前");
}

static const char *const g_cnLocationById[CN_MEMTALK_LOCATION_COUNT] = {
    "",
    "在公寓客厅",
    "在餐厅厨房",
    "在真嗣房间",
    "在真嗣房间",
    "在明日香房间",
    "在美里房间",
    "在公寓洗手间",
    "在总司令办公室",
    "在 NERV 发令所",
    "在美里办公室",
    "在 NERV 食堂",
    "在律子研究室",
    "在加持的个人房间",
    "在 NERV 自动贩卖机角",
    "在 NERV 自动贩卖机角",
    "在预备地点一",
    "在 NERV 大浴场",
    "在中央教条区",
    "在绫波的公寓",
    "在绫波的公寓",
    "在学校教室",
    "在学校走廊",
    "在便利店",
    "在地上废墟",
    "在心之迷宫",
    "在初号机机库",
    "在美里办公室",
    "在 EVA 机库预备地图",
    "在预备宿舍地图",
    "在预备地图五",
    "在第三新东京市",
    "在 NERV 总部",
    "在家中",
    "在自室预备地图",
    "在阳台",
    "在阳台",
    "在阳台",
    "在公寓外",
    "在某处",
    "在预备地图十六",
    "在绫波的公寓",
    "在美里的公寓",
    "在律子研究室",
    "在美里办公室",
    "在美里办公室",
    "在律子研究室",
    "在便利店外",
    "在学校屋顶",
    "在高台公园",
    "在新箱根汤本站",
    "在零号机机库",
    "在二号机机库",
    "在三号机机库",
    "在四号机机库",
    "在 NERV 总部旁",
    "在渚薰宿舍",
    "在加持宿舍",
    "在真嗣宿舍",
    "在绫波宿舍",
    "在明日香宿舍",
    "在美里宿舍",
    "在律子宿舍",
    "在冬二宿舍",
    "在青叶宿舍",
    "在日向宿舍",
    "在摩耶宿舍",
    "在冬月宿舍",
    "在源堂宿舍",
    "在上学路上",
    "在总部自动扶梯",
    "在第七实验场",
    "在实验场",
    "在射击训练场",
    "在干部宿舍前通道",
    "在职员宿舍前通道",
    "在驾驶员宿舍前走廊",
    "在远景废墟预备地图",
    "在远景屋顶预备地图",
    "在远景公园预备地图",
    "在远景车站预备地图",
};

static const char *CnMemTalk_LocationPhrase(const CnActionRecord *rec, uint8_t styleBit) {
  const char *jp = Game_FormatLocationPhrase((const void *)rec, styleBit);
  uintptr_t ptr = (uintptr_t)jp;

  if (!jp || jp[0] == '\0') return "";

  /* 0x089D53B8 = "ここで". */
  if (ptr == CN_MEMTALK_REBASE(0x089D53B8)) return "在这里";

  if (rec->locationId < CN_MEMTALK_LOCATION_COUNT) {
    return g_cnLocationById[rec->locationId];
  }
  return "";
}

/*
 * Verb phrase translation by original menu string pointer.
 * If the pointer is not one of the menu verbs, fall back to "回想起".
 */
static const CnPtrPhrase g_cnVerbPhrases[] = {
    {0x089D527C, "回想起"},
    {0x089D528C, "仔细回想起"},
    {0x089D52A0, "反复仔细回想起"},
    {0x089D52B8, "认真回想起"},
    {0x089D52C8, "重新思考"},
    {0x089D5438, "开始战斗测试"},
    {0x089D544C, "开始战斗演示测试"},
};

static const char *CnMemTalk_VerbPhrase(const char *verbSjis) {
  return CnMemTalk_TranslatePtrPhrase(
      g_cnVerbPhrases,
      sizeof(g_cnVerbPhrases) / sizeof(g_cnVerbPhrases[0]),
      verbSjis,
      "回想起");
}

/*
 * Template table examples.
 *
 * The real patch should generate a full table from
 * docs/memtalk_templates_zh_draft.jsonc after manual review. Keep the same
 * structure and replace/extend this array with all reviewed entries.
 */
static const CnMemTalkTemplate g_cnMemTalkTemplates[] = {
    {2, CN_SUBJECT_AUTO, "向{B}搭话", "搭话"},
    {4, CN_SUBJECT_AUTO, "无视{B}", "无视"},
    {5, CN_SUBJECT_AUTO, "接近{B}", "接近"},
    {7, CN_SUBJECT_AUTO, "冷淡地回应{B}", "冷淡回应"},
    {8, CN_SUBJECT_AUTO, "训斥{B}没出息的态度", "训斥态度"},
    {9, CN_SUBJECT_AUTO, "结束和{B}的谈话", "结束谈话"},
    {17, CN_SUBJECT_AUTO, "因{B}的态度受打击", "受打击"},
    {25, CN_SUBJECT_AUTO, "在{B}面前害羞", "害羞"},
    {31, CN_SUBJECT_AUTO, "移开看向{B}的视线", "移开视线"},
    {32, CN_SUBJECT_AUTO, "对{B}微笑", "微笑"},
    {35, CN_SUBJECT_AUTO, "独自烦恼", "烦恼"},
    {48, CN_SUBJECT_AUTO, "回答{B}的问题说自己不知道", "回答不知道"},
    {49, CN_SUBJECT_AUTO, "警告{B}", "警告"},
    {81, CN_SUBJECT_AUTO, "从{B}身边离开", "离开"},
    {91, CN_SUBJECT_AUTO, "亲吻{B}", "亲吻"},
    {93, CN_SUBJECT_AUTO, "抱住{B}", "抱住"},
    {94, CN_SUBJECT_AUTO, "握住{B}的手", "握手"},
    {99, CN_SUBJECT_AUTO, "紧紧抱住{B}", "紧抱"},
    {101, CN_SUBJECT_AUTO, "和{B}十指相扣", "十指相扣"},
    {102, CN_SUBJECT_AUTO, "拒绝{B}的邀请", "拒绝邀请"},
    {143, CN_SUBJECT_AUTO, "担心{B}", "担心"},
    {200, CN_SUBJECT_AUTO, "洗澡", "洗澡"},
    {212, CN_SUBJECT_AUTO, "坐在椅子上", "坐下"},
    {237, CN_SUBJECT_AUTO, "和{B}闲聊", "闲聊"},
    {476, CN_SUBJECT_AUTO, "审查意见书", "审查意见书"},
    {492, CN_SUBJECT_AUTO, "和{B}一起学习", "一起学习"},
    {578, CN_SUBJECT_AUTO, "去了便利店厕所", "去厕所"},
    {583, CN_SUBJECT_AUTO, "看电视", "看电视"},

    /*
     * Internal $a/$b templates. These are translated manually because the
     * original template's internal placeholders are not equivalent to the
     * final text engine's $a/$b tokens.
     */
    {113, CN_SUBJECT_AUTO, "向{B}询问对{A_ref}的好感", "询问好感"},
    {116, CN_SUBJECT_AUTO, "向{B}询问躲着{A_ref}的理由", "询问理由"},
    {300, CN_SUBJECT_AUTO, "没从{B}那里拿到零花钱，于是向{B}抱怨", "抱怨零花钱"},
    {383, CN_SUBJECT_INSIDE, "{A}看到{B}沉默的样子，自己也沉默了", "一起沉默"},
    {673, CN_SUBJECT_AUTO, "收到{B}的出院报告后关心{B}", "关心出院"},
    {676, CN_SUBJECT_AUTO, "问{B}：{A_ref}不在时是不是很辛苦", "询问辛苦"},
    {1109, CN_SUBJECT_AUTO, "看到{B}对加持感到愤慨，于是安抚{B}", "安抚"},
    {1353, CN_SUBJECT_AUTO, "把{B}想要的道具给了{B}", "给道具"},
};

static const CnMemTalkTemplate *CnMemTalk_FindTemplate(uint16_t templateId) {
  size_t i;
  for (i = 0; i < sizeof(g_cnMemTalkTemplates) / sizeof(g_cnMemTalkTemplates[0]); i++) {
    if (g_cnMemTalkTemplates[i].templateId == templateId) return &g_cnMemTalkTemplates[i];
  }
  return 0;
}

static void CnMemTalk_RenderChineseEvent(
    const CnActionRecord *rec,
    uint8_t styleBit,
    char *out,
    size_t outCap) {
  const CnMemTalkTemplate *tpl;
  char actor[CN_MEMTALK_PHRASE_CAP];
  char actorRef[CN_MEMTALK_PHRASE_CAP];
  char object[CN_MEMTALK_PHRASE_CAP];
  size_t pos = 0;

  if (!out || outCap == 0) return;
  out[0] = '\0';

  if (!rec || rec->templateId >= CN_MEMTALK_TEMPLATE_COUNT) {
    CnAppendCStr(out, outCap, 0, "发生过");
    return;
  }

  tpl = CnMemTalk_FindTemplate(rec->templateId);
  if (!tpl) {
    /*
     * Fallback for entries not yet translated. For production, fill the full
     * template table instead of relying on this generic text.
     */
    CnAppendCStr(out, outCap, 0, "发生过");
    return;
  }

  CnMemTalk_MaskToPhrase(rec->maskA, styleBit, "自己", actor, sizeof(actor));
  CnMemTalk_MaskToPhrase(rec->maskA, styleBit, "自己", actorRef, sizeof(actorRef));
  CnMemTalk_MaskToPhrase(rec->maskB, styleBit, "自己", object, sizeof(object));

  if (tpl->subjectPolicy == CN_SUBJECT_AUTO &&
      !CnMemTalk_MaskContainsStyle(rec->maskA, styleBit) &&
      actor[0] != '\0') {
    pos = CnAppendCStr(out, outCap, pos, actor);
  }

  pos = CnAppendTemplateText(
      out,
      outCap,
      pos,
      tpl->eventTemplate,
      actor,
      actorRef,
      object);
}

static void CnMemTalk_BuildTalkTargetPart(uint8_t targetBit, char *out, size_t outCap) {
  size_t pos = 0;
  if (!out || outCap == 0) return;
  out[0] = '\0';
  if (targetBit == 0) return;
  pos = CnAppendCStr(out, outCap, pos, "向");
  pos = CnAppendCStr(out, outCap, pos, CnMemTalk_NameByBit(targetBit));
}

static void CnMemTalk_BuildSimpleSentence(
    uint8_t speakerBit,
    uint8_t targetBit,
    const char *verbSjis,
    char *out,
    size_t outCap) {
  char targetPart[CN_MEMTALK_PHRASE_CAP];
  size_t pos = 0;

  if (!out || outCap == 0) return;
  out[0] = '\0';

  CnMemTalk_BuildTalkTargetPart(targetBit, targetPart, sizeof(targetPart));

  pos = CnAppendCStr(out, outCap, pos, CnMemTalk_NameByBit(speakerBit));
  pos = CnAppendCStr(out, outCap, pos, targetPart);
  pos = CnAppendCStr(out, outCap, pos, CnMemTalk_VerbPhrase(verbSjis));
  pos = CnAppendCStr(out, outCap, pos, "过去的事。");
}

static void CnMemTalk_BuildDetailSentence(
    uint8_t speakerBit,
    uint8_t targetBit,
    const CnActionRecord *rec,
    const char *verbSjis,
    char *out,
    size_t outCap) {
  char targetPart[CN_MEMTALK_PHRASE_CAP];
  char eventText[CN_MEMTALK_TEXT_CAP];
  const char *timePhrase;
  const char *placePhrase;
  size_t pos = 0;

  if (!out || outCap == 0) return;
  out[0] = '\0';

  CnMemTalk_BuildTalkTargetPart(targetBit, targetPart, sizeof(targetPart));
  CnMemTalk_RenderChineseEvent(rec, speakerBit, eventText, sizeof(eventText));
  timePhrase = CnMemTalk_TimePhrase(rec);
  placePhrase = CnMemTalk_LocationPhrase(rec, speakerBit);

  pos = CnAppendCStr(out, outCap, pos, CnMemTalk_NameByBit(speakerBit));
  pos = CnAppendCStr(out, outCap, pos, targetPart);
  pos = CnAppendCStr(out, outCap, pos, CnMemTalk_VerbPhrase(verbSjis));
  pos = CnAppendCStr(out, outCap, pos, timePhrase);
  pos = CnAppendCStr(out, outCap, pos, placePhrase);
  pos = CnAppendCStr(out, outCap, pos, eventText);
  pos = CnAppendCStr(out, outCap, pos, "的事。");
}

static void CnMemTalk_BuildTailSentence(uint8_t targetBit, uint32_t kind, char *out, size_t outCap) {
  const char *tail = "没能理解。";
  size_t pos = 0;

  if (!out || outCap == 0) return;
  out[0] = '\0';

  if (kind == 1) tail = "没能听清。";
  else if (kind == 2) tail = "还是不明白。";

  pos = CnAppendCStr(out, outCap, pos, "但是");
  pos = CnAppendCStr(out, outCap, pos, CnMemTalk_NameByBit(targetBit));
  pos = CnAppendCStr(out, outCap, pos, tail);
}

static void *CnMemTalk_ShowTailIfNeeded(uint8_t speakerBit, uint8_t targetBit) {
  int r;
  uint32_t kind = 0;
  char buffer[CN_MEMTALK_TEXT_CAP];

  if (speakerBit != 16 || targetBit == 0) return 0;

  /*
   * Preserve original branch:
   *   rand < 0  -> understand failure
   *   rand < 2  -> not understood
   *   rand == 2 -> could not hear
   *   else      -> understand failure
   */
  r = Game_RandN(5);
  if (r >= 0 && r < 2) kind = 2;
  else if (r == 2) kind = 1;
  else kind = 0;

  CnMemTalk_BuildTailSentence(targetBit, kind, buffer, sizeof(buffer));
  return Game_ShowTokenizedText(0, speakerBit, targetBit, 0, buffer);
}

/*
 * Replacement for MemTalk_ShowMemorySentence/sub_890F080.
 *
 * Hook target:
 *   original function address: 0x0890F080
 *
 * Expected call signature:
 *   void *CnMemTalk_ShowMemorySentence(void *ctx, const CnActionRecord *rec, const char *verbSjis)
 *
 * Recommended hook:
 *   replace the JAL/call site to sub_890F080 with this function, or patch
 *   sub_890F080's body to jump here.
 */
void *CnMemTalk_ShowMemorySentence(void *ctx, const CnActionRecord *rec, const char *verbSjis) {
  uint8_t speakerBit;
  uint8_t targetBit;
  int currentPlayerBit;
  uint32_t overlap;
  char buffer[CN_MEMTALK_TEXT_CAP];
  void *result;

  if (!ctx) return 0;

  speakerBit = CnMemTalk_GetSpeakerBit(ctx);
  targetBit = CnMemTalk_GetTargetBit(ctx);
  currentPlayerBit = Game_GetCurrentPlayerBit();

  /*
   * Preserve original visibility condition:
   * show this memory only when the current player is the speaker or target.
   */
  if (speakerBit != (uint8_t)currentPlayerBit && targetBit != (uint8_t)currentPlayerBit) {
    return 0;
  }

  /*
   * Preserve original simple/detail split:
   * simple if no record or maskA/maskB overlap in low 24 bits.
   */
  overlap = rec ? (rec->maskA & rec->maskB & 0x00FFFFFFu) : 1u;
  if (!rec || overlap != 0) {
    CnMemTalk_BuildSimpleSentence(speakerBit, targetBit, verbSjis, buffer, sizeof(buffer));
  } else {
    CnMemTalk_BuildDetailSentence(speakerBit, targetBit, rec, verbSjis, buffer, sizeof(buffer));
  }

  /*
   * We pass fully rendered Chinese names, so the buffer intentionally does not
   * contain $a/$b. Still use sub_882FD7C for the original text box lifecycle.
   */
  result = Game_ShowTokenizedText(0, speakerBit, targetBit, 0, buffer);

  {
    void *tailResult = CnMemTalk_ShowTailIfNeeded(speakerBit, targetBit);
    if (tailResult) result = tailResult;
  }

  return result;
}

/*
 * Implementation examples
 * -----------------------
 *
 * Example 1:
 *   speakerBit = 1  (碇真嗣)
 *   targetBit  = 0
 *   rec->maskA = 1 << 1
 *   rec->maskB = 1 << 2
 *   rec->templateId = 2  // "向{B}搭话"
 *   time = 今早, place = 在 NERV 食堂
 *
 * Output:
 *   碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。
 *
 * Example 2:
 *   speakerBit = 1  (碇真嗣)
 *   targetBit  = 2  (明日香)
 *   rec->maskA = 1 << 3
 *   rec->maskB = 1 << 1
 *   rec->templateId = 4  // "无视{B}"
 *
 * Output:
 *   碇真嗣向明日香回想起以前绫波丽无视自己的事。
 *
 * Example 3:
 *   speakerBit = 1
 *   rec->templateId = 113 // "向{B}询问对{A_ref}的好感"
 *   rec->maskA = 1 << 1
 *   rec->maskB = 1 << 2
 *
 * Output:
 *   碇真嗣回想起以前向明日香询问对自己的好感的事。
 */
