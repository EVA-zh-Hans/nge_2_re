#include "hook_write.h"
#include "memtalk_game_calls.h"

#define CN_MEMTALK_ADDR_SHOW_TOKENIZED_TEXT 0x0882fd7cu
#define CN_MEMTALK_ADDR_GET_CURRENT_PLAYER_BIT 0x08828580u
#define CN_MEMTALK_ADDR_RAND_N 0x08871778u
#define CN_MEMTALK_ADDR_GET_NAME_BY_BIT 0x088395d8u
#define CN_MEMTALK_ADDR_FORMAT_CHARACTER_MASK 0x0890f7b4u
#define CN_MEMTALK_ADDR_FORMAT_TIME_PHRASE 0x0890f8b8u
#define CN_MEMTALK_ADDR_FORMAT_LOCATION_PHRASE 0x0890f9f0u

typedef void *(*ShowTokenizedTextFn)(int group, int speakerBit, int targetBit, int thirdBit, char *text);
typedef int (*GetCurrentPlayerBitFn)(void);
typedef int (*RandNFn)(int n);
typedef const char *(*GetNameByBitFn)(int bit);
typedef int (*FormatCharacterMaskFn)(uint32_t mask, int styleBit, char *out);
typedef const char *(*FormatTimePhraseFn)(const void *rec);
typedef const char *(*FormatLocationPhraseFn)(const void *rec, int styleBit);

static ShowTokenizedTextFn show_tokenized_text;
static GetCurrentPlayerBitFn get_current_player_bit;
static RandNFn rand_n;
static GetNameByBitFn get_name_by_bit;
static FormatCharacterMaskFn format_character_mask;
static FormatTimePhraseFn format_time_phrase;
static FormatLocationPhraseFn format_location_phrase;

void MemTalkGameCalls_Init(u32 game_base)
{
    show_tokenized_text = (ShowTokenizedTextFn)HookWrite_GameAddr(game_base, CN_MEMTALK_ADDR_SHOW_TOKENIZED_TEXT);
    get_current_player_bit = (GetCurrentPlayerBitFn)HookWrite_GameAddr(game_base, CN_MEMTALK_ADDR_GET_CURRENT_PLAYER_BIT);
    rand_n = (RandNFn)HookWrite_GameAddr(game_base, CN_MEMTALK_ADDR_RAND_N);
    get_name_by_bit = (GetNameByBitFn)HookWrite_GameAddr(game_base, CN_MEMTALK_ADDR_GET_NAME_BY_BIT);
    format_character_mask = (FormatCharacterMaskFn)HookWrite_GameAddr(game_base, CN_MEMTALK_ADDR_FORMAT_CHARACTER_MASK);
    format_time_phrase = (FormatTimePhraseFn)HookWrite_GameAddr(game_base, CN_MEMTALK_ADDR_FORMAT_TIME_PHRASE);
    format_location_phrase = (FormatLocationPhraseFn)HookWrite_GameAddr(game_base, CN_MEMTALK_ADDR_FORMAT_LOCATION_PHRASE);
}

void *MemTalkCall_ShowTokenizedText(int group, int speakerBit, int targetBit, int thirdBit, char *text)
{
    return show_tokenized_text(group, speakerBit, targetBit, thirdBit, text);
}

int MemTalkCall_GetCurrentPlayerBit(void)
{
    return get_current_player_bit();
}

int MemTalkCall_RandN(int n)
{
    return rand_n(n);
}

const char *MemTalkCall_GetNameByBit(int bit)
{
    return get_name_by_bit(bit);
}

int MemTalkCall_FormatCharacterMask(uint32_t mask, int styleBit, char *out)
{
    return format_character_mask(mask, styleBit, out);
}

const char *MemTalkCall_FormatTimePhrase(const void *rec)
{
    return format_time_phrase(rec);
}

const char *MemTalkCall_FormatLocationPhrase(const void *rec, int styleBit)
{
    return format_location_phrase(rec, styleBit);
}
