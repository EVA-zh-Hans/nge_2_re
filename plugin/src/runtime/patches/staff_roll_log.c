#include <pspiofilemgr.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "staff_roll_log.h"

#define STAFF_ROLL_LOG_FILE "ms0:/PSP/staff_roll_debug.log"

void *_exit = 0;

static int g_staffRollLogInitialized;

static size_t StaffRollLog_StrLen(const char *text)
{
    const char *p = text;

    if (!text)
    {
        return 0;
    }

    while (*p)
    {
        ++p;
    }
    return (size_t)(p - text);
}

void StaffRollLog_Init(void)
{
    if (g_staffRollLogInitialized)
    {
        return;
    }

    g_staffRollLogInitialized = 1;

    SceUID fd = sceIoOpen(STAFF_ROLL_LOG_FILE, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_TRUNC, 0777);
    if (fd >= 0)
    {
        sceIoClose(fd);
    }
}

void StaffRollLog_Printf(const char *format, ...)
{
    char buffer[512];
    va_list args;
    SceUID fd;

    if (!g_staffRollLogInitialized)
    {
        StaffRollLog_Init();
    }

    fd = sceIoOpen(STAFF_ROLL_LOG_FILE, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_APPEND, 0777);
    if (fd < 0)
    {
        return;
    }

    va_start(args, format);
    vsnprintf(buffer, sizeof(buffer), format, args);
    va_end(args);

    sceIoWrite(fd, buffer, StaffRollLog_StrLen(buffer));
    sceIoWrite(fd, "\n", 1);
    sceIoClose(fd);
}
