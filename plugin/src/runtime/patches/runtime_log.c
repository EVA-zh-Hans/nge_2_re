#include <pspiofilemgr.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "runtime_log.h"

#ifdef PSPDEBUG

#define RUNTIME_LOG_FILE "ms0:/PSP/eva2rt_debug.log"

void *_exit = 0;

static int g_runtimeLogInitialized;

static size_t RuntimeLog_StrLen(const char *text)
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

void RuntimeLog_Init(void)
{
    if (g_runtimeLogInitialized)
    {
        return;
    }

    g_runtimeLogInitialized = 1;

    SceUID fd = sceIoOpen(RUNTIME_LOG_FILE, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_TRUNC, 0777);
    if (fd >= 0)
    {
        sceIoClose(fd);
    }
}

void RuntimeLog_Printf(const char *format, ...)
{
    char buffer[512];
    va_list args;
    SceUID fd;

    if (!g_runtimeLogInitialized)
    {
        RuntimeLog_Init();
    }

    fd = sceIoOpen(RUNTIME_LOG_FILE, PSP_O_WRONLY | PSP_O_CREAT | PSP_O_APPEND, 0777);
    if (fd < 0)
    {
        return;
    }

    va_start(args, format);
    vsnprintf(buffer, sizeof(buffer), format, args);
    va_end(args);

    sceIoWrite(fd, buffer, RuntimeLog_StrLen(buffer));
    sceIoWrite(fd, "\n", 1);
    sceIoClose(fd);
}

#else

void RuntimeLog_Init(void)
{
}

void RuntimeLog_Printf(const char *format, ...)
{
    (void)format;
}

#endif
