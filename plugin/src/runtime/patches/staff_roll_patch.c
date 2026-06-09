#include <stdint.h>
#include <string.h>

#include "hook_write.h"
#include "staff_roll_log.h"

typedef struct StaffScrollCmd {
    uint32_t ctrl;
    int16_t row_left;
    int16_t row_right;
} StaffScrollCmd;

#include "generated_staff_roll.h"

#define STAFF_ROLL_ADDR_INIT 0x08975BB4u
#define STAFF_ROLL_ADDR_DESTROY 0x08975CBCu
#define STAFF_ROLL_ADDR_ALLOC_ROW 0x08976500u
#define STAFF_ROLL_ADDR_HAR_FIND_ENTRY 0x08813298u
#define STAFF_ROLL_ADDR_HPT_CREATE_ROW_SPRITE 0x08812EB0u
#define STAFF_ROLL_ADDR_HPT_RELEASE 0x088132BCu

#define STAFF_ROLL_ADDR_CTX_PTR 0x08BEB5B0u
#define STAFF_ROLL_ADDR_COMMAND_TABLE 0x08A561FCu
#define STAFF_ROLL_ADDR_FRAME_LIMIT 0x08975AE8u

#define STAFF_ROLL_HOOK_INIT 0x08975A44u
#define STAFF_ROLL_HOOK_DESTROY 0x08975B70u
#define STAFF_ROLL_HOOK_ALLOC_LEFT 0x08976064u
#define STAFF_ROLL_HOOK_ALLOC_RIGHT 0x0897615Cu
#define STAFF_ROLL_HOOK_ALLOC_SEPARATOR 0x0897627Cu

#define STAFF_ROLL_OPCODE_FRAME_LIMIT 0x2A0714A0u
#define STAFF_ROLL_OPCODE_SLTI_A3_S0 0x2A070000u

#define STAFF_ROLL_CTX_SCROLL_SPEED_OFFSET 0x560u
#define STAFF_ROLL_CTX_COMMAND_PTR_OFFSET 0x568u
#define STAFF_ROLL_END_FLAG 0x1u
#define STAFF_ROLL_GAP_SHIFT 4
#define STAFF_ROLL_GAP_MASK 0xFFFFu
#define STAFF_ROLL_ORIGINAL_ROW_COUNT 214
#define STAFF_ROLL_MAX_FRAME_LIMIT 0x7FFF

typedef void (*StaffRollVoidFn)(void);
typedef int (*StaffRollFindEntryFn)(const char *name);
typedef int (*StaffRollCreateRowSpriteFn)(
    int hpt_handle,
    int local_row,
    int initial_x,
    int initial_y,
    int height);
typedef void (*StaffRollReleaseFn)(int hpt_handle);
typedef int (*StaffRollAllocRowFn)(int row_id);

static StaffRollVoidFn g_staffRollOriginalInit;
static StaffRollVoidFn g_staffRollOriginalDestroy;
static StaffRollFindEntryFn g_staffRollFindEntry;
static StaffRollCreateRowSpriteFn g_staffRollCreateRowSprite;
static StaffRollReleaseFn g_staffRollRelease;
static StaffRollAllocRowFn g_staffRollOriginalAllocRow;

static u32 g_staffRollCtxPtrAddr;
static u32 g_staffRollFrameLimitAddr;
static int g_staffRollExtraHpt = -1;
static int g_staffRollFrameLimitPatched;
static StaffScrollCmd g_staffRollExtendedCommands[STAFF_ROLL_EXTENDED_COMMAND_COUNT];

static u32 StaffRollPatch_ReadU32(u32 addr)
{
    return *(const volatile u32 *)addr;
}

static void *StaffRollPatch_GetCtx(void)
{
    return *(void *const volatile *)g_staffRollCtxPtrAddr;
}

static int StaffRollPatch_BuildExtendedTable(const StaffScrollCmd *original)
{
    int suffixCount;

    if (!original ||
        (original[STAFF_ROLL_ORIGINAL_COMMAND_COUNT - 1].ctrl & STAFF_ROLL_END_FLAG) == 0)
    {
        StaffRollLog_Printf(
            "staffroll build table: invalid original table or missing end flag");
        return 0;
    }

    suffixCount = STAFF_ROLL_ORIGINAL_COMMAND_COUNT - STAFF_ROLL_INSERT_INDEX;
    StaffRollLog_Printf(
        "staffroll build table: original=%d extra=%d insert=%d suffix=%d",
        STAFF_ROLL_ORIGINAL_COMMAND_COUNT,
        STAFF_ROLL_EXTRA_COMMAND_COUNT,
        STAFF_ROLL_INSERT_INDEX,
        suffixCount);
    memcpy(
        g_staffRollExtendedCommands,
        original,
        STAFF_ROLL_INSERT_INDEX * sizeof(StaffScrollCmd));
    memcpy(
        g_staffRollExtendedCommands + STAFF_ROLL_INSERT_INDEX,
        g_staffRollExtraCommands,
        STAFF_ROLL_EXTRA_COMMAND_COUNT * sizeof(StaffScrollCmd));
    memcpy(
        g_staffRollExtendedCommands + STAFF_ROLL_INSERT_INDEX + STAFF_ROLL_EXTRA_COMMAND_COUNT,
        original + STAFF_ROLL_INSERT_INDEX,
        suffixCount * sizeof(StaffScrollCmd));
    return 1;
}

static int StaffRollPatch_CalculateFrameLimit(float speed)
{
    float accumulator = 0.0f;
    int commandIndex = 0;
    int frame;

    if (speed <= 0.0f)
    {
        return -1;
    }

    for (frame = 1; frame <= STAFF_ROLL_MAX_FRAME_LIMIT + 1; ++frame)
    {
        if (accumulator <= 0.0f)
        {
            const StaffScrollCmd *command;
            if (commandIndex >= STAFF_ROLL_EXTENDED_COMMAND_COUNT)
            {
                return -1;
            }

            command = &g_staffRollExtendedCommands[commandIndex++];
            if (command->ctrl & STAFF_ROLL_END_FLAG)
            {
                return frame - 1;
            }
            accumulator += (float)(
                (command->ctrl >> STAFF_ROLL_GAP_SHIFT) & STAFF_ROLL_GAP_MASK);
        }
        accumulator -= speed;
    }

    return -1;
}

static void StaffRollPatch_InitHook(void)
{
    void *ctx;
    int frameLimit;
    float speed;

    StaffRollLog_Printf("staffroll init hook begin");
    g_staffRollOriginalInit();
    g_staffRollExtraHpt = g_staffRollFindEntry(STAFF_ROLL_ATLAS_NAME);
    StaffRollLog_Printf("staffroll find entry %s -> %d", STAFF_ROLL_ATLAS_NAME, g_staffRollExtraHpt);
    if (g_staffRollExtraHpt < 0)
    {
        StaffRollLog_Printf("staffroll init hook: atlas missing");
        return;
    }

    ctx = StaffRollPatch_GetCtx();
    StaffRollLog_Printf("staffroll ctx=%08x", (unsigned)ctx);
    if (!ctx)
    {
        StaffRollLog_Printf("staffroll init hook: ctx null");
        g_staffRollRelease(g_staffRollExtraHpt);
        g_staffRollExtraHpt = -1;
        return;
    }

    speed = *(const float *)((const uint8_t *)ctx + STAFF_ROLL_CTX_SCROLL_SPEED_OFFSET);
    frameLimit = StaffRollPatch_CalculateFrameLimit(speed);
    StaffRollLog_Printf(
        "staffroll speed_raw=%08x frameLimit=%d",
        *(const unsigned int *)&speed,
        frameLimit);
    if (frameLimit <= 0 || frameLimit > STAFF_ROLL_MAX_FRAME_LIMIT)
    {
        StaffRollLog_Printf("staffroll init hook: invalid frame limit");
        g_staffRollRelease(g_staffRollExtraHpt);
        g_staffRollExtraHpt = -1;
        return;
    }

    StaffRollLog_Printf(
        "staffroll command ptr %08x -> %08x",
        (unsigned)*(const uint32_t *)((uint8_t *)ctx + STAFF_ROLL_CTX_COMMAND_PTR_OFFSET),
        (unsigned)g_staffRollExtendedCommands);
    *(const StaffScrollCmd **)((uint8_t *)ctx + STAFF_ROLL_CTX_COMMAND_PTR_OFFSET) =
        g_staffRollExtendedCommands;
    HookWrite_U32(
        g_staffRollFrameLimitAddr,
        STAFF_ROLL_OPCODE_SLTI_A3_S0 | (u32)frameLimit);
    g_staffRollFrameLimitPatched = 1;
    HookWrite_FlushCaches();
    StaffRollLog_Printf("staffroll init hook: installed frameLimit=%d", frameLimit);
}

static void StaffRollPatch_DestroyHook(void)
{
    StaffRollLog_Printf("staffroll destroy hook begin extraHpt=%d patched=%d", g_staffRollExtraHpt, g_staffRollFrameLimitPatched);
    if (g_staffRollExtraHpt >= 0)
    {
        g_staffRollRelease(g_staffRollExtraHpt);
        g_staffRollExtraHpt = -1;
    }

    if (g_staffRollFrameLimitPatched)
    {
        HookWrite_U32(g_staffRollFrameLimitAddr, STAFF_ROLL_OPCODE_FRAME_LIMIT);
        g_staffRollFrameLimitPatched = 0;
        HookWrite_FlushCaches();
    }

    g_staffRollOriginalDestroy();
    StaffRollLog_Printf("staffroll destroy hook end");
}

static int StaffRollPatch_AllocRowHook(int rowId)
{
    int localRow;

    if (rowId < STAFF_ROLL_ORIGINAL_ROW_COUNT)
    {
        return g_staffRollOriginalAllocRow(rowId);
    }

    localRow = rowId - STAFF_ROLL_EXTRA_ROW_BASE + 1;
    if (g_staffRollExtraHpt < 0 ||
        localRow < 1 ||
        localRow > STAFF_ROLL_EXTRA_ROW_COUNT)
    {
        StaffRollLog_Printf(
            "staffroll alloc row fail rowId=%d extraHpt=%d localRow=%d",
            rowId,
            g_staffRollExtraHpt,
            localRow);
        return -1;
    }

    {
        int sprite = g_staffRollCreateRowSprite(g_staffRollExtraHpt, localRow, 0x4000, 512, 24);
        StaffRollLog_Printf(
            "staffroll alloc row rowId=%d localRow=%d hpt=%d sprite=%d",
            rowId,
            localRow,
            g_staffRollExtraHpt,
            sprite);
        return sprite;
    }
}

void StaffRollPatch_Install(u32 game_base)
{
    u32 hookInit = HookWrite_GameAddr(game_base, STAFF_ROLL_HOOK_INIT);
    u32 hookDestroy = HookWrite_GameAddr(game_base, STAFF_ROLL_HOOK_DESTROY);
    u32 hookAllocLeft = HookWrite_GameAddr(game_base, STAFF_ROLL_HOOK_ALLOC_LEFT);
    u32 hookAllocRight = HookWrite_GameAddr(game_base, STAFF_ROLL_HOOK_ALLOC_RIGHT);
    u32 hookAllocSeparator = HookWrite_GameAddr(game_base, STAFF_ROLL_HOOK_ALLOC_SEPARATOR);
    const StaffScrollCmd *originalTable = (const StaffScrollCmd *)HookWrite_GameAddr(
        game_base,
        STAFF_ROLL_ADDR_COMMAND_TABLE);

    g_staffRollFrameLimitAddr = HookWrite_GameAddr(game_base, STAFF_ROLL_ADDR_FRAME_LIMIT);
    g_staffRollCtxPtrAddr = HookWrite_GameAddr(game_base, STAFF_ROLL_ADDR_CTX_PTR);
    StaffRollLog_Printf(
        "staffroll install begin base=%08x init=%08x destroy=%08x alloc=%08x",
        game_base,
        hookInit,
        hookDestroy,
        hookAllocLeft);

    if (!StaffRollPatch_BuildExtendedTable(originalTable))
    {
        StaffRollLog_Printf("staffroll install abort: build table failed");
        return;
    }

    g_staffRollOriginalInit = (StaffRollVoidFn)HookWrite_GameAddr(
        game_base,
        STAFF_ROLL_ADDR_INIT);
    g_staffRollOriginalDestroy = (StaffRollVoidFn)HookWrite_GameAddr(
        game_base,
        STAFF_ROLL_ADDR_DESTROY);
    g_staffRollOriginalAllocRow = (StaffRollAllocRowFn)HookWrite_GameAddr(
        game_base,
        STAFF_ROLL_ADDR_ALLOC_ROW);
    g_staffRollFindEntry = (StaffRollFindEntryFn)HookWrite_GameAddr(
        game_base,
        STAFF_ROLL_ADDR_HAR_FIND_ENTRY);
    g_staffRollCreateRowSprite = (StaffRollCreateRowSpriteFn)HookWrite_GameAddr(
        game_base,
        STAFF_ROLL_ADDR_HPT_CREATE_ROW_SPRITE);
    g_staffRollRelease = (StaffRollReleaseFn)HookWrite_GameAddr(
        game_base,
        STAFF_ROLL_ADDR_HPT_RELEASE);

    HookWrite_Call(hookInit, StaffRollPatch_InitHook);
    HookWrite_Call(hookDestroy, StaffRollPatch_DestroyHook);
    HookWrite_Call(hookAllocLeft, StaffRollPatch_AllocRowHook);
    HookWrite_Call(hookAllocRight, StaffRollPatch_AllocRowHook);
    HookWrite_Call(hookAllocSeparator, StaffRollPatch_AllocRowHook);
    StaffRollLog_Printf("staffroll install success");
}
