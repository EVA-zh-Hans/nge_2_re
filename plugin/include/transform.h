#pragma once
#include <stdint.h>

uint16_t translate_code(uint16_t code);
uint16_t modified_to_utf16(uint16_t code);

#define EVA_ENCODING_ERROR_ARGUMENT -1
#define EVA_ENCODING_ERROR_INPUT -2
#define EVA_ENCODING_ERROR_OUTPUT -3
#define EVA_ENCODING_ERROR_UNMAPPABLE -4

// Reversed from Binary.
// FUN_08884680
uint16_t sjis_to_utf16(uint16_t sjis);
// FUN_08884724
int binary_search(uint16_t sjis, int low, int high);

int eva_sjis_to_utf8(const uint8_t *input, int input_size, char *output, int output_size);
int utf8_to_eva_sjis(const char *input, int input_size, uint8_t *output, int output_size);
