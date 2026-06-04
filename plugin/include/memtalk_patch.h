#pragma once

#include <stdint.h>
#include <psptypes.h>

enum {
    CN_MEMTALK_TEMPLATE_COUNT = 0x6D6
};

typedef enum CnMemTalkSubjectPolicy {
    CN_MEMTALK_SUBJECT_AUTO = 0,
    CN_MEMTALK_SUBJECT_MANUAL = 1
} CnMemTalkSubjectPolicy;

typedef struct CnMemTalkTemplatePair {
    uint8_t subjectPolicy;
    const char *prefix;
    const char *suffix;
} CnMemTalkTemplatePair;

extern const CnMemTalkTemplatePair g_cnMemTalkTemplates[CN_MEMTALK_TEMPLATE_COUNT];

void MemTalkPatch_Install(u32 game_base);
char *CnMemTalk_FormatActionSummary25(const void *rec, uint8_t styleBit, char *out25);
void *CnMemTalk_ShowMemorySentence(void *ctx, const void *rec, const char *verbSjis);
