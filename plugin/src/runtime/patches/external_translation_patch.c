#include <pspiofilemgr.h>
#include <psptypes.h>

#include "hook_write.h"

typedef struct TranslationHeader {
    u32 num;
} TranslationHeader;

typedef struct TranslationEntry {
    u32 offset;
    u32 size;
    u8 buffer[1024];
} TranslationEntry;

static char *ExternalTranslation_Strcpyn(char *dest, const char *src, u32 n)
{
    char *ret = dest;
    while (n-- && (*dest++ = *src++) != '\0') {
    }
    if (n > 0) {
        *dest = '\0';
    }
    return ret;
}

int ExternalTranslationPatch_Apply(u32 game_base, const char *filename)
{
    TranslationHeader header;
    TranslationEntry entry;
    SceUID fd;
    int err;
    u32 i;

    fd = sceIoOpen(filename, PSP_O_RDONLY, 0777);
    if (fd < 0) {
        return fd;
    }

    err = sceIoRead(fd, &header.num, sizeof(header.num));
    if (err < 0) {
        sceIoClose(fd);
        return err;
    }

    for (i = 0; i < header.num; ++i) {
        err = sceIoRead(fd, &entry.offset, sizeof(entry.offset));
        if (err < 0) {
            sceIoClose(fd);
            return err;
        }

        err = sceIoRead(fd, &entry.size, sizeof(entry.size));
        if (err < 0) {
            sceIoClose(fd);
            return err;
        }

        err = sceIoRead(fd, entry.buffer, sizeof(entry.buffer));
        if (err < 0) {
            sceIoClose(fd);
            return err;
        }

        ExternalTranslation_Strcpyn(
            (char *)HookWrite_GameAddr(game_base, entry.offset),
            (const char *)entry.buffer,
            entry.size);
    }

    return sceIoClose(fd);
}
