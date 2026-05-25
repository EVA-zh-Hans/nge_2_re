#include <stdint.h>
#include <stddef.h>

typedef struct ActionTemplatePair {
  const char *prefix;
  const char *suffix;
} ActionTemplatePair;

typedef struct ActionRecord {
  uint32_t unk0;
  uint32_t maskA;
  uint32_t maskB;
  uint16_t templateId;
  uint16_t unkC;
  uint16_t unk10;
  uint16_t sortKey;
} ActionRecord;

typedef struct ActionListContext {
  uint32_t unk00;
  uint32_t unk04;
  uint32_t targetBit;
  uint32_t speakerBit;
  uint32_t thirdBit;
  uint32_t nowMinutes;
  uint32_t currentLocationId;
} ActionListContext;

typedef struct TimeOfDayRule {
  uint32_t minDelta;
  uint32_t maxDelta;
  uint32_t thresholdMinuteOfDay;
  const char *phrase;
} TimeOfDayRule;

typedef struct TimeAgoRule {
  uint32_t deltaThreshold;
  const char *phrase;
} TimeAgoRule;

typedef const char *(*MemTalk_GetNameByBitFn)(int bit);

enum {
  MEMTALK_TEMPLATE_COUNT = 0x6D6,
  MEMTALK_LOCATION_COUNT = 81,
  MEMTALK_MINUTE_PER_DAY = 1440
};

#define MEMTALK_ADDR_TEMPLATES ((uintptr_t)0x08A4B45C)
#define MEMTALK_ADDR_LOC_TABLE ((uintptr_t)0x08A4EB0C)
#define MEMTALK_ADDR_TOD_RULES ((uintptr_t)0x08A4ECC0)
#define MEMTALK_ADDR_TAGO_RULES ((uintptr_t)0x08A4EC50)
#define MEMTALK_ADDR_TIME_DEFAULT_PTR ((uintptr_t)0x08A4ED20)
#define MEMTALK_ADDR_VERB_TABLE ((uintptr_t)0x08A4ED24)
#define MEMTALK_ADDR_SKELETON_SIMPLE ((uintptr_t)0x089D52DC)
#define MEMTALK_ADDR_SKELETON_DETAIL ((uintptr_t)0x089D5368)
#define MEMTALK_ADDR_TOKEN_BNI ((uintptr_t)0x089D535C)
#define MEMTALK_ADDR_STR_GA ((uintptr_t)0x089D5364)
#define MEMTALK_ADDR_STR_JIBUN ((uintptr_t)0x089D53B0)
#define MEMTALK_ADDR_STR_TACHI ((uintptr_t)0x089D53A8)
#define MEMTALK_ADDR_STR_KOKODE ((uintptr_t)0x089D53B8)
#define MEMTALK_ADDR_TAIL_0 ((uintptr_t)0x089D52F4)
#define MEMTALK_ADDR_TAIL_1 ((uintptr_t)0x089D5318)
#define MEMTALK_ADDR_TAIL_2 ((uintptr_t)0x089D533C)

static const ActionTemplatePair *MemTalk_Templates(void) {
  return (const ActionTemplatePair *)MEMTALK_ADDR_TEMPLATES;
}

static const char *const *MemTalk_LocationTable(void) {
  return (const char *const *)MEMTALK_ADDR_LOC_TABLE;
}

static const TimeOfDayRule *MemTalk_TimeOfDayRules(void) {
  return (const TimeOfDayRule *)MEMTALK_ADDR_TOD_RULES;
}

static const TimeAgoRule *MemTalk_TimeAgoRules(void) {
  return (const TimeAgoRule *)MEMTALK_ADDR_TAGO_RULES;
}

static const char *MemTalk_DerefPtrTable(uintptr_t addr) {
  return *(const char *const *)addr;
}

static size_t MemTalk_StrLen(const char *s) {
  size_t n = 0;
  if (!s) return 0;
  while (s[n] != '\0') n++;
  return n;
}

static size_t MemTalk_AppendByte(char *dst, size_t cap, size_t pos, uint8_t b) {
  if (!dst || cap == 0) return pos;
  if (pos + 1 >= cap) return pos;
  dst[pos] = (char)b;
  dst[pos + 1] = '\0';
  return pos + 1;
}

static size_t MemTalk_AppendBytes(char *dst, size_t cap, size_t pos, const uint8_t *src, size_t n) {
  if (!dst || cap == 0) return pos;
  if (!src || n == 0) return pos;
  while (n-- > 0) {
    if (pos + 1 >= cap) return pos;
    dst[pos++] = (char)(*src++);
  }
  if (pos < cap) dst[pos] = '\0';
  else dst[cap - 1] = '\0';
  return pos;
}

static size_t MemTalk_AppendCStr(char *dst, size_t cap, size_t pos, const char *s) {
  if (!s) return pos;
  return MemTalk_AppendBytes(dst, cap, pos, (const uint8_t *)s, MemTalk_StrLen(s));
}

static int MemTalk_FirstSetBit1To16(uint32_t mask) {
  for (int bit = 1; bit <= 16; bit++) {
    if ((mask & (1u << bit)) != 0) return bit;
  }
  return -1;
}

static size_t MemTalk_MaskToText(char *dst, size_t cap, size_t pos, uint32_t mask, int styleBit, MemTalk_GetNameByBitFn getNameByBit) {
  const char *jibun = (const char *)MEMTALK_ADDR_STR_JIBUN;
  const char *tachi = (const char *)MEMTALK_ADDR_STR_TACHI;

  if ((mask & 0xFFFFFFFEu) == 0) return pos;

  int chosenBit = -1;
  const char *base = 0;

  if (0 <= styleBit && styleBit < 32 && (mask & (1u << styleBit)) != 0) {
    chosenBit = styleBit;
    base = jibun;
  } else {
    chosenBit = MemTalk_FirstSetBit1To16(mask);
    if (chosenBit < 0) return pos;
    base = getNameByBit ? getNameByBit(chosenBit) : 0;
  }

  if (base) pos = MemTalk_AppendCStr(dst, cap, pos, base);

  if (chosenBit >= 0) {
    uint32_t rest = (mask & ~(1u << chosenBit));
    if (rest != 0) pos = MemTalk_AppendCStr(dst, cap, pos, tachi);
  }

  return pos;
}

static size_t MemTalk_ExpandTemplate(char *dst, size_t cap, size_t pos, const char *tmpl, const ActionRecord *rec, int styleBit, MemTalk_GetNameByBitFn getNameByBit) {
  if (!tmpl || !rec) return pos;

  const uint8_t *p = (const uint8_t *)tmpl;
  while (*p != 0) {
    uint8_t b = *p++;
    if ((int8_t)b < 0) {
      uint8_t b2 = *p ? *p++ : 0;
      uint8_t pair[2] = {b, b2};
      pos = MemTalk_AppendBytes(dst, cap, pos, pair, 2);
      continue;
    }
    if (b == '$' && *p != 0) {
      uint8_t ph = *p++;
      if (ph == 'a') {
        pos = MemTalk_MaskToText(dst, cap, pos, rec->maskA, styleBit, getNameByBit);
        continue;
      }
      if (ph == 'b') {
        pos = MemTalk_MaskToText(dst, cap, pos, rec->maskB, styleBit, getNameByBit);
        continue;
      }
      pos = MemTalk_AppendByte(dst, cap, pos, '$');
      pos = MemTalk_AppendByte(dst, cap, pos, ph);
      continue;
    }
    pos = MemTalk_AppendByte(dst, cap, pos, b);
  }

  return pos;
}

size_t MemTalk_RenderExpandedPair(const ActionRecord *rec, char *outBuf, size_t outCap, char delimiter, int styleBit, MemTalk_GetNameByBitFn getNameByBit) {
  if (!outBuf || outCap == 0) return 0;
  outBuf[0] = '\0';
  if (!rec) return 0;

  uint32_t id = (uint32_t)rec->templateId;
  if (id >= MEMTALK_TEMPLATE_COUNT) return 0;

  const ActionTemplatePair *pair = &MemTalk_Templates()[id];
  size_t pos = 0;
  pos = MemTalk_ExpandTemplate(outBuf, outCap, pos, pair->prefix, rec, styleBit, getNameByBit);

  if (pair->suffix && pair->suffix[0] != 0) {
    pos = MemTalk_AppendByte(outBuf, outCap, pos, (uint8_t)delimiter);
    pos = MemTalk_ExpandTemplate(outBuf, outCap, pos, pair->suffix, rec, styleBit, getNameByBit);
  }

  return pos;
}

const char *MemTalk_FormatTimePhrase(uint32_t nowMinutes, uint32_t recMinutes) {
  const char *def = MemTalk_DerefPtrTable(MEMTALK_ADDR_TIME_DEFAULT_PTR);
  if (!def) def = "";

  if (recMinutes == 0) return def;
  if (nowMinutes < recMinutes) return def;

  uint32_t delta = nowMinutes - recMinutes;
  uint32_t nowDay = nowMinutes / MEMTALK_MINUTE_PER_DAY;
  uint32_t recDay = recMinutes / MEMTALK_MINUTE_PER_DAY;

  if (nowDay == recDay) {
    uint32_t recMinuteOfDay = recMinutes % MEMTALK_MINUTE_PER_DAY;
    const TimeOfDayRule *rules = MemTalk_TimeOfDayRules();
    for (int i = 0; i < 6; i++) {
      const TimeOfDayRule *r = &rules[i];
      if (delta >= r->minDelta && delta < r->maxDelta && recMinuteOfDay < r->thresholdMinuteOfDay) {
        return r->phrase ? r->phrase : def;
      }
    }
    return def;
  }

  const TimeAgoRule *rules = MemTalk_TimeAgoRules();
  for (int i = 0; i < 14; i++) {
    const TimeAgoRule *r = &rules[i];
    if (delta < r->deltaThreshold) return r->phrase ? r->phrase : def;
  }
  return def;
}

const char *MemTalk_FormatLocationPhrase(uint32_t currentLocationId, uint32_t recLocationId) {
  const char *kokode = (const char *)MEMTALK_ADDR_STR_KOKODE;
  if (currentLocationId == recLocationId) return kokode ? kokode : "";
  if (recLocationId == 0 || recLocationId >= MEMTALK_LOCATION_COUNT) return "";
  const char *const *tbl = MemTalk_LocationTable();
  const char *p = tbl ? tbl[recLocationId] : 0;
  return p ? p : "";
}

static size_t MemTalk_FormatPrintfS(char *dst, size_t cap, const char *fmt, const char *const *args, size_t argCount) {
  size_t pos = 0;
  if (!dst || cap == 0) return 0;
  dst[0] = '\0';
  if (!fmt) return 0;

  size_t ai = 0;
  const uint8_t *p = (const uint8_t *)fmt;
  while (*p != 0) {
    uint8_t b = *p++;
    if ((int8_t)b < 0) {
      uint8_t b2 = *p ? *p++ : 0;
      uint8_t pair[2] = {b, b2};
      pos = MemTalk_AppendBytes(dst, cap, pos, pair, 2);
      continue;
    }
    if (b == '%' && *p == 's') {
      p++;
      const char *a = (ai < argCount) ? args[ai] : "";
      ai++;
      pos = MemTalk_AppendCStr(dst, cap, pos, a ? a : "");
      continue;
    }
    pos = MemTalk_AppendByte(dst, cap, pos, b);
  }
  return pos;
}

size_t MemTalk_BuildDetailSentence(
    const ActionListContext *ctx,
    const ActionRecord *rec,
    const char *verbSjis,
    int styleBit,
    MemTalk_GetNameByBitFn getNameByBit,
    char *outBuf,
    size_t outCap) {
  if (!outBuf || outCap == 0) return 0;
  outBuf[0] = '\0';
  if (!ctx || !rec) return 0;

  char expanded[512];
  expanded[0] = '\0';
  MemTalk_RenderExpandedPair(rec, expanded, sizeof(expanded), '\n', styleBit, getNameByBit);

  const char *timePhrase = MemTalk_FormatTimePhrase(ctx->nowMinutes, rec->unk0);
  const char *placePhrase = MemTalk_FormatLocationPhrase(ctx->currentLocationId, (uint32_t)((rec->unkC >> 8) & 0xFFu));

  char maskAText[64];
  char maskBText[64];
  maskAText[0] = '\0';
  maskBText[0] = '\0';
  MemTalk_MaskToText(maskAText, sizeof(maskAText), 0, rec->maskA, styleBit, getNameByBit);
  MemTalk_MaskToText(maskBText, sizeof(maskBText), 0, rec->maskB, styleBit, getNameByBit);

  const int needA = (0 <= styleBit && styleBit < 32) ? ((rec->maskA & (1u << styleBit)) == 0) : 1;
  const char *aOpt = needA ? maskAText : "";
  const char *gaOpt = (needA && aOpt && aOpt[0] != 0) ? (const char *)MEMTALK_ADDR_STR_GA : "";
  const char *targetPrefix = (ctx->targetBit != 0) ? (const char *)MEMTALK_ADDR_TOKEN_BNI : "";

  const char *fmt = (const char *)MEMTALK_ADDR_SKELETON_DETAIL;
  const char *args[8];
  args[0] = targetPrefix ? targetPrefix : "";
  args[1] = timePhrase ? timePhrase : "";
  args[2] = verbSjis ? verbSjis : "";
  args[3] = placePhrase ? placePhrase : "";
  args[4] = aOpt ? aOpt : "";
  args[5] = gaOpt ? gaOpt : "";
  args[6] = maskBText;
  args[7] = expanded;

  return MemTalk_FormatPrintfS(outBuf, outCap, fmt, args, 8);
}

size_t MemTalk_BuildSimpleSentence(const char *verbSjis, char *outBuf, size_t outCap) {
  const char *fmt = (const char *)MEMTALK_ADDR_SKELETON_SIMPLE;
  const char *args[1];
  args[0] = verbSjis ? verbSjis : "";
  return MemTalk_FormatPrintfS(outBuf, outCap, fmt, args, 1);
}

size_t MemTalk_BuildTailSentence(uint32_t kind, const char *targetName, char *outBuf, size_t outCap) {
  const char *fmt = 0;
  if (kind == 1) fmt = (const char *)MEMTALK_ADDR_TAIL_1;
  else if (kind == 2) fmt = (const char *)MEMTALK_ADDR_TAIL_2;
  else fmt = (const char *)MEMTALK_ADDR_TAIL_0;
  const char *args[1];
  args[0] = targetName ? targetName : "";
  return MemTalk_FormatPrintfS(outBuf, outCap, fmt, args, 1);
}
