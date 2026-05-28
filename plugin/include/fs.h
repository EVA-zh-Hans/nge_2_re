#pragma once

typedef struct EngineFileHandle // sizeof=0x110
{
  int os_fd;
  int is_opened;
  unsigned int lbn;
  unsigned int size;
  char filepath[256];
} EngineFileHandle;

int path_to_lbn(const char *path, unsigned int *out_lbn, unsigned int *out_size);
char *init_file_handle_with_lbn_path(char *path, struct EngineFileHandle *handle);