#pragma once
#include <stddef.h>

char *strcpy(char *dest, const char *src);
char *strcpyn(char *dest, const char *src, size_t n);
int my_sprintf(char *buf, const char *fmt, ...);