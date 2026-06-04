/*
 * Chinese MemTalk sentence builder.
 *
 * The ActionRecord selection and the game's memory text window stay in the
 * original code. This hook replaces MemTalk_ShowMemorySentence at 0x0890F080
 * so detail sentences can render Chinese event templates with {A}/{B} slots.
 *
 * Translation data lives in translation/cn_memtalk_templates.c and is
 * generated from docs/memtalk_template_translation_workbook.tsv as UTF-8.
 * The selected template is converted to EVA SJIS before it reaches the game.
 */

#include <stdint.h>

#include "hook_write.h"
#include "memtalk_game_calls.h"
#include "memtalk_patch.h"
#include "transform.h"

#define CN_MEMTALK_ADDR_SHOW_TOKENIZED_TEXT 0x0882FD7Cu
#define CN_MEMTALK_ADDR_GET_CURRENT_PLAYER_BIT 0x08828580u
#define CN_MEMTALK_ADDR_RAND_N 0x08871778u
#define CN_MEMTALK_ADDR_GET_NAME_BY_BIT 0x088395D8u
#define CN_MEMTALK_ADDR_FORMAT_CHARACTER_MASK 0x0890F7B4u
#define CN_MEMTALK_ADDR_FORMAT_TIME_PHRASE 0x0890F8B8u
#define CN_MEMTALK_ADDR_FORMAT_LOCATION_PHRASE 0x0890F9F0u

#define CN_MEMTALK_HOOK_SHOW_MEMORY_SENTENCE 0x0890F080u
#define CN_MEMTALK_HOOK_FORMAT_ACTION_SUMMARY 0x0890F6B8u
#define CN_MEMTALK_LOW24_MASK 0x00FFFFFFu

enum {
    CN_MEMTALK_SENTENCE_CAP = 512,
    CN_MEMTALK_EVENT_CAP = 384,
    CN_MEMTALK_MASK_CAP = 96,
    CN_MEMTALK_LITERAL_CAP = 128,
    CN_MEMTALK_SUMMARY_CAP = 25,
    CN_MEMTALK_TEMPLATE_PIECE_CAP = 192
};

typedef struct CnMemTalkActionRecord {
    uint32_t timestamp;
    uint32_t maskA;
    uint32_t maskB;
    uint8_t valid;
    uint8_t locationId;
    uint16_t templateId;
    uint8_t recordType;
    uint8_t unk11;
    uint16_t sortKey;
} CnMemTalkActionRecord;

static uint8_t CnMemTalk_GetSpeakerBit(const void *ctx)
{
    return *((const uint8_t *)ctx + 0x51);
}

static uint8_t CnMemTalk_GetTargetBit(const void *ctx)
{
    return *((const uint8_t *)ctx + 0x52);
}

static int CnMemTalk_StrStartsWith(const uint8_t *text, const char *ascii)
{
    while (*ascii)
    {
        if (*text++ != (uint8_t)*ascii++)
        {
            return 0;
        }
    }
    return 1;
}

static int CnMemTalk_AppendByte(char *out, int outCap, int pos, uint8_t byte)
{
    if (!out || outCap <= 0 || pos + 1 >= outCap)
    {
        return pos;
    }

    out[pos++] = (char)byte;
    out[pos] = '\0';
    return pos;
}

static int CnMemTalk_AppendText(char *out, int outCap, int pos, const char *text)
{
    const uint8_t *p = (const uint8_t *)text;

    if (!text)
    {
        return pos;
    }

    while (*p)
    {
        pos = CnMemTalk_AppendByte(out, outCap, pos, *p++);
    }
    return pos;
}

static int CnMemTalk_AppendUtf8Text(char *out, int outCap, int pos, const char *utf8Text)
{
    uint8_t evaSjisText[CN_MEMTALK_LITERAL_CAP];
    int utf8Len = 0;
    int textLen;

    if (!utf8Text || !utf8Text[0])
    {
        return pos;
    }

    while (utf8Text[utf8Len])
    {
        ++utf8Len;
    }

    textLen = utf8_to_eva_sjis(
        utf8Text,
        utf8Len,
        evaSjisText,
        sizeof(evaSjisText));
    if (textLen < 0)
    {
        return pos;
    }

    return CnMemTalk_AppendText(out, outCap, pos, (const char *)evaSjisText);
}

static int CnMemTalk_StrLen(const char *text)
{
    int size = 0;
    if (!text)
    {
        return 0;
    }
    while (text[size])
    {
        ++size;
    }
    return size;
}

static int CnMemTalk_RenderEvaTemplatePiece(
    char *out,
    int outCap,
    int pos,
    const char *piece,
    const char *maskAText,
    const char *maskBText)
{
    const uint8_t *p = (const uint8_t *)piece;

    if (!piece)
    {
        return pos;
    }

    while (*p)
    {
        if (CnMemTalk_StrStartsWith(p, "{A}"))
        {
            pos = CnMemTalk_AppendText(out, outCap, pos, maskAText);
            p += 3;
            continue;
        }
        if (CnMemTalk_StrStartsWith(p, "{B}"))
        {
            pos = CnMemTalk_AppendText(out, outCap, pos, maskBText);
            p += 3;
            continue;
        }

        /*
         * Keep EVA SJIS bytes paired while scanning ASCII placeholders.
         * Only treat known lead-byte ranges as 2-byte sequences.
         */
        if ((*p >= 0xA6 && *p <= 0xDD) || (*p >= 0x81 && *p <= 0x9F) || (*p >= 0xE0 && *p <= 0xFC))
        {
            pos = CnMemTalk_AppendByte(out, outCap, pos, *p++);
            if (*p)
            {
                pos = CnMemTalk_AppendByte(out, outCap, pos, *p++);
            }
            continue;
        }

        pos = CnMemTalk_AppendByte(out, outCap, pos, *p++);
    }

    return pos;
}

static int CnMemTalk_RenderTemplatePiece(
    char *out,
    int outCap,
    int pos,
    const char *utf8Piece,
    const char *maskAText,
    const char *maskBText)
{
    uint8_t evaSjisPiece[CN_MEMTALK_TEMPLATE_PIECE_CAP];
    int pieceLen;

    if (!utf8Piece || !utf8Piece[0])
    {
        return pos;
    }

    pieceLen = utf8_to_eva_sjis(
        utf8Piece,
        CnMemTalk_StrLen(utf8Piece),
        evaSjisPiece,
        sizeof(evaSjisPiece));
    if (pieceLen < 0)
    {
        return pos;
    }

    return CnMemTalk_RenderEvaTemplatePiece(
        out,
        outCap,
        pos,
        (const char *)evaSjisPiece,
        maskAText,
        maskBText);
}

static int CnMemTalk_MaskContainsStyle(uint32_t mask, uint8_t styleBit)
{
    if (styleBit >= 32)
    {
        return 0;
    }
    return (mask & (1u << styleBit)) != 0;
}

static int CnMemTalk_IsSjisLeadByte(uint8_t byte)
{
    if (byte >= 0xA6 && byte <= 0xDD)
    {
        return 1;
    }
    return (byte >= 0x81 && byte <= 0x9F) || (byte >= 0xE0 && byte <= 0xFC);
}

static int CnMemTalk_SjisCharSize(const uint8_t *text)
{
    if (!text || !text[0])
    {
        return 0;
    }

    if (CnMemTalk_IsSjisLeadByte(text[0]))
    {
        return text[1] ? 2 : 0;
    }

    return 1;
}

static int CnMemTalk_SjisFits(const char *text, int outCap)
{
    const uint8_t *p = (const uint8_t *)text;
    int pos = 0;

    if (!text || outCap <= 0)
    {
        return 1;
    }

    while (*p)
    {
        int charSize = CnMemTalk_SjisCharSize(p);
        if (charSize <= 0 || pos + charSize >= outCap)
        {
            return 0;
        }
        pos += charSize;
        p += charSize;
    }

    return 1;
}

static int CnMemTalk_EncodeUtf8Literal(const char *utf8Text, char *out, int outCap)
{
    int utf8Len = 0;

    if (!utf8Text || !out || outCap <= 0)
    {
        return 0;
    }

    while (utf8Text[utf8Len])
    {
        ++utf8Len;
    }

    return utf8_to_eva_sjis(utf8Text, utf8Len, (uint8_t *)out, outCap);
}

static char *CnMemTalk_CopySjisTruncated(char *out, int outCap, const char *text)
{
    char ellipsis[8];
    int ellipsisLen;
    int bodyLimit;
    int pos = 0;
    int i;
    const uint8_t *p = (const uint8_t *)text;

    if (!out || outCap <= 0)
    {
        return out;
    }

    for (i = 0; i < outCap; ++i)
    {
        out[i] = '\0';
    }

    if (!text)
    {
        return out;
    }

    if (CnMemTalk_SjisFits(text, outCap))
    {
        CnMemTalk_AppendText(out, outCap, 0, text);
        return out;
    }

    ellipsisLen = CnMemTalk_EncodeUtf8Literal("…", ellipsis, sizeof(ellipsis));
    if (ellipsisLen <= 0 || ellipsisLen >= outCap)
    {
        ellipsisLen = 0;
    }

    bodyLimit = outCap - 1 - ellipsisLen;
    while (*p)
    {
        int charSize = CnMemTalk_SjisCharSize(p);
        if (charSize <= 0 || pos + charSize > bodyLimit)
        {
            break;
        }
        out[pos++] = (char)*p++;
        if (charSize == 2)
        {
            out[pos++] = (char)*p++;
        }
    }

    for (i = 0; i < ellipsisLen && pos + 1 < outCap; ++i)
    {
        out[pos++] = ellipsis[i];
    }
    out[pos] = '\0';
    return out;
}

static int CnMemTalk_BuildEvent(
    const CnMemTalkActionRecord *rec,
    uint8_t styleBit,
    char *out,
    int outCap)
{
    const CnMemTalkTemplatePair *templatePair;
    char maskAText[CN_MEMTALK_MASK_CAP];
    char maskBText[CN_MEMTALK_MASK_CAP];
    int pos = 0;

    if (!out || outCap <= 0)
    {
        return 0;
    }
    out[0] = '\0';

    if (!rec || rec->templateId >= CN_MEMTALK_TEMPLATE_COUNT)
    {
        return 0;
    }

    templatePair = &g_cnMemTalkTemplates[rec->templateId];
    if (!templatePair->prefix)
    {
        return 0;
    }

    maskAText[0] = '\0';
    maskBText[0] = '\0';
    MemTalkCall_FormatCharacterMask(rec->maskA, styleBit, maskAText);
    MemTalkCall_FormatCharacterMask(rec->maskB, styleBit, maskBText);

    /*
     * Auto templates omit {A}. Prefix a non-speaker actor before the Chinese
     * event; manual templates already place {A} where the translation needs it.
     */
    if (templatePair->subjectPolicy == CN_MEMTALK_SUBJECT_AUTO &&
        !CnMemTalk_MaskContainsStyle(rec->maskA, styleBit) &&
        maskAText[0])
    {
        pos = CnMemTalk_AppendText(out, outCap, pos, maskAText);
    }

    pos = CnMemTalk_RenderTemplatePiece(out, outCap, pos, templatePair->prefix, maskAText, maskBText);
    pos = CnMemTalk_RenderTemplatePiece(out, outCap, pos, templatePair->suffix, maskAText, maskBText);
    return pos;
}

char *CnMemTalk_FormatActionSummary25(const void *recVoid, uint8_t styleBit, char *out25)
{
    const CnMemTalkActionRecord *rec = (const CnMemTalkActionRecord *)recVoid;
    char eventText[CN_MEMTALK_EVENT_CAP];

    if (!out25)
    {
        return out25;
    }

    if (!CnMemTalk_BuildEvent(rec, styleBit, eventText, sizeof(eventText)))
    {
        eventText[0] = '\0';
        CnMemTalk_AppendUtf8Text(eventText, sizeof(eventText), 0, "过去的事");
    }

    return CnMemTalk_CopySjisTruncated(out25, CN_MEMTALK_SUMMARY_CAP, eventText);
}

static int CnMemTalk_AppendTalkTarget(char *out, int outCap, int pos, uint8_t targetBit)
{
    if (targetBit == 0)
    {
        return pos;
    }

    pos = CnMemTalk_AppendUtf8Text(out, outCap, pos, "向");
    return CnMemTalk_AppendText(out, outCap, pos, "$b");
}

static int CnMemTalk_BuildSimpleSentence(
    char *out,
    int outCap,
    uint8_t targetBit,
    const char *verbSjis)
{
    int pos = 0;

    if (!out || outCap <= 0)
    {
        return 0;
    }
    out[0] = '\0';

    pos = CnMemTalk_AppendText(out, outCap, pos, "$a");
    pos = CnMemTalk_AppendTalkTarget(out, outCap, pos, targetBit);
    pos = CnMemTalk_AppendText(out, outCap, pos, verbSjis);
    pos = CnMemTalk_AppendUtf8Text(out, outCap, pos, "过去的事情。");
    return pos;
}

static int CnMemTalk_BuildDetailSentence(
    char *out,
    int outCap,
    const CnMemTalkActionRecord *rec,
    uint8_t styleBit,
    uint8_t targetBit,
    const char *verbSjis)
{
    char eventText[CN_MEMTALK_EVENT_CAP];
    const char *timePhrase;
    const char *placePhrase;
    int pos = 0;

    if (!out || outCap <= 0)
    {
        return 0;
    }
    out[0] = '\0';

    if (!CnMemTalk_BuildEvent(rec, styleBit, eventText, sizeof(eventText)))
    {
        return CnMemTalk_BuildSimpleSentence(out, outCap, targetBit, verbSjis);
    }

    timePhrase = MemTalkCall_FormatTimePhrase(rec);
    placePhrase = MemTalkCall_FormatLocationPhrase(rec, styleBit);

    pos = CnMemTalk_AppendText(out, outCap, pos, "$a");
    pos = CnMemTalk_AppendTalkTarget(out, outCap, pos, targetBit);
    pos = CnMemTalk_AppendText(out, outCap, pos, verbSjis);
    pos = CnMemTalk_AppendText(out, outCap, pos, timePhrase);
    pos = CnMemTalk_AppendText(out, outCap, pos, placePhrase);
    pos = CnMemTalk_AppendText(out, outCap, pos, eventText);
    pos = CnMemTalk_AppendUtf8Text(out, outCap, pos, "。");
    return pos;
}

static void *CnMemTalk_ShowTailIfNeeded(uint8_t speakerBit, uint8_t targetBit)
{
    const char *targetName;
    const char *tailText;
    char buffer[CN_MEMTALK_SENTENCE_CAP];
    int pos = 0;
    int r;

    if (speakerBit != 16 || targetBit == 0)
    {
        return 0;
    }

    r = MemTalkCall_RandN(5);
    if (r >= 0 && r < 2)
    {
        tailText = "还是不明白。";
    }
    else if (r == 2)
    {
        tailText = "没能听清。";
    }
    else
    {
        tailText = "没能理解。";
    }

    targetName = MemTalkCall_GetNameByBit(targetBit);
    buffer[0] = '\0';
    pos = CnMemTalk_AppendUtf8Text(buffer, sizeof(buffer), pos, "但是");
    pos = CnMemTalk_AppendText(buffer, sizeof(buffer), pos, targetName);
    CnMemTalk_AppendUtf8Text(buffer, sizeof(buffer), pos, tailText);
    return MemTalkCall_ShowTokenizedText(0, speakerBit, targetBit, 0, buffer);
}

void *CnMemTalk_ShowMemorySentence(void *ctx, const void *recVoid, const char *verbSjis)
{
    const CnMemTalkActionRecord *rec = (const CnMemTalkActionRecord *)recVoid;
    uint8_t speakerBit;
    uint8_t targetBit;
    uint32_t overlap;
    int currentPlayerBit;
    char buffer[CN_MEMTALK_SENTENCE_CAP];
    void *result;
    void *tailResult;

    if (!ctx)
    {
        return 0;
    }

    speakerBit = CnMemTalk_GetSpeakerBit(ctx);
    targetBit = CnMemTalk_GetTargetBit(ctx);
    currentPlayerBit = MemTalkCall_GetCurrentPlayerBit();

    if (speakerBit != (uint8_t)currentPlayerBit && targetBit != (uint8_t)currentPlayerBit)
    {
        return 0;
    }

    overlap = rec ? (rec->maskA & rec->maskB & CN_MEMTALK_LOW24_MASK) : 1u;
    if (!rec || overlap)
    {
        CnMemTalk_BuildSimpleSentence(buffer, sizeof(buffer), targetBit, verbSjis);
    }
    else
    {
        CnMemTalk_BuildDetailSentence(buffer, sizeof(buffer), rec, speakerBit, targetBit, verbSjis);
    }

    result = MemTalkCall_ShowTokenizedText(0, speakerBit, targetBit, 0, buffer);
    tailResult = CnMemTalk_ShowTailIfNeeded(speakerBit, targetBit);
    return tailResult ? tailResult : result;
}

void MemTalkPatch_Install(u32 game_base)
{
    MemTalkGameCalls_Init(game_base);
    HookWrite_Jump(HookWrite_GameAddr(game_base, CN_MEMTALK_HOOK_FORMAT_ACTION_SUMMARY), CnMemTalk_FormatActionSummary25);
    HookWrite_Nop(HookWrite_GameAddr(game_base, CN_MEMTALK_HOOK_FORMAT_ACTION_SUMMARY + 4));
    HookWrite_Jump(HookWrite_GameAddr(game_base, CN_MEMTALK_HOOK_SHOW_MEMORY_SENTENCE), CnMemTalk_ShowMemorySentence);
    HookWrite_Nop(HookWrite_GameAddr(game_base, CN_MEMTALK_HOOK_SHOW_MEMORY_SENTENCE + 4));
}
