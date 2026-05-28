/**
Patch File Look-up functions. Redirect them to ms0:/PSP/GAME/EVA2/USRDIR.
The original program uses LBA syntax in sceIoOpen; this patch instead allows the use of
file path syntax.
*/
#include "fs.h"

#include <pspkernel.h>
#include <pspiofilemgr.h>

#include "log.h"
#include "utils.h"

#define EVA2_PATH_FMT "ms0:/PSP/GAME/EVA2/USRDIR/%s"

SceOff get_file_size(const char *path)
{
    SceUID fd = sceIoOpen(path, PSP_O_RDONLY, 0777);
    if (fd < 0)
        return -1;

    // 移动到文件末尾
    SceOff size = sceIoLseek(fd, 0, PSP_SEEK_END);

    sceIoClose(fd);
    return size;
}

static unsigned int hash_path(const char *s)
{
    // djb2 hash, genearte pseudo LBN
    unsigned int h = 5381;
    int c;

    while ((c = *s++))
        h = ((h << 5) + h) + c;

    return h;
}

// Function at 0x8985FE4
int path_to_lbn(const char *path, unsigned int *out_lbn, unsigned int *out_size) {
  char new_path_buffer[256];
  
  dbg_log("Input path: %s\n", path);
  my_sprintf(new_path_buffer, EVA2_PATH_FMT, path);
  dbg_log("Translated path: %s\n", new_path_buffer);
  
  *out_lbn = hash_path(path); // Hash the path to get a pseudo LBN in case the game relies on it
  *out_size = get_file_size(new_path_buffer);
  
  return 0;
}

// Function at 0x8986C8C
char *init_file_handle_with_lbn_path(char *path, struct EngineFileHandle *handle) {
  char new_path_buffer[256];
  
  path_to_lbn(path, &handle->lbn,&handle->size);
  // sprintf(buffer, "disc0:/sce_lbn0x%x_size0x%x", handle->lbn, handle->size);
  my_sprintf(new_path_buffer, EVA2_PATH_FMT, path);
  strcpyn(handle->filepath, new_path_buffer, sizeof(handle->filepath));
  handle->filepath[sizeof(handle->filepath) - 1] = '\0';
  
  return handle->filepath;
}