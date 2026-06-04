#pragma once

#include <stdint.h>
#include <psptypes.h>

void MemTalkGameCalls_Init(u32 game_base);
void *MemTalkCall_ShowTokenizedText(int group, int speakerBit, int targetBit, int thirdBit, char *text);
int MemTalkCall_GetCurrentPlayerBit(void);
int MemTalkCall_RandN(int n);
const char *MemTalkCall_GetNameByBit(int bit);
int MemTalkCall_FormatCharacterMask(uint32_t mask, int styleBit, char *out);
const char *MemTalkCall_FormatTimePhrase(const void *rec);
const char *MemTalkCall_FormatLocationPhrase(const void *rec, int styleBit);
