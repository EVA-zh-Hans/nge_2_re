/**
Modify the SJIS Table to store more Chinese Characters
First Byte
0x00-0x7F: ASCII
0x81-0x9F: Hiragana, Katakana, Greek, Cyrillic, etc.
0xA1-0xDF: Half-width Katakana
0xE0-0xFC: Kanji

第二字节的范围是 0x40 - 0x7E 或 0x80 - 0xFC

Use 0xA6-0xDD to store more Chinese Characters
0xA600-0xDDFF.
*/
#include <pspkernel.h>
#include <stdint.h>

#include "transform.h"

// #define UTF16_TABLE_ADDRESS 0x08a2fb60
// UTF16 Encoding
extern unsigned char UTF16_bin[14436]; // UTF16 Table
extern unsigned int UTF16_bin_len;

// #define DAT_08a3325c_ADDRESS 0x08a3325c
// lower bound of SJIS Encoding (u16) + Offset (u16)
// 0x20 0x00 0x00 0x00
// 0xa1 0x00 0x00 0x5f
// 0x40 0x81 0x9e 0x00
extern unsigned char SJIS_bin[360]; // SJIS Table
extern unsigned int SJIS_bin_len;

// GB2312 Input Space
// First Byte: 0xA1-0xF7
// Second Byte: 0xA1-0xFE
//
// Output Space: 0xA600-0xDDFF
// index: See gb2312_to_custom_map
extern unsigned char GB2312_CUSTOM_BIN[]; // UTF-16 Table for Custom Encoding
extern unsigned int GB2312_CUSTOM_BIN_len;

#define EVA_CUSTOM_SJIS_FIRST 0xA600
#define EVA_CUSTOM_SJIS_LAST 0xDDFF
#define EVA_CUSTOM_LEAD_FIRST 0xA6
#define EVA_CUSTOM_LEAD_LAST 0xDD

#ifdef LOG
extern int logPrintf(const char* text, ...);
#endif

/**
 * Convert UTF-16 code point to UTF-8 and store it in a buffer
 * Handles BMP (Basic Multilingual Plane) characters up to 0xFFFF
 * 
 * UTF-16 to UTF-8 conversion rules:
 * - 0x0000-0x007F: 1 byte  (0xxxxxxx)
 * - 0x0080-0x07FF: 2 bytes (110xxxxx 10xxxxxx)
 * - 0x0800-0xFFFF: 3 bytes (1110xxxx 10xxxxxx 10xxxxxx)
 */
static int utf16_to_utf8_bytes(uint16_t utf16_code, char *utf8_buf, int buf_size)
{
    if (utf16_code < 0x80)
    {
        // 1-byte UTF-8
        if (buf_size < 1) return EVA_ENCODING_ERROR_OUTPUT;
        utf8_buf[0] = (unsigned char)utf16_code;
        return 1;
    }

    if (utf16_code < 0x800)
    {
        // 2-byte UTF-8
        if (buf_size < 2) return EVA_ENCODING_ERROR_OUTPUT;
        utf8_buf[0] = (unsigned char)(0xC0 | (utf16_code >> 6));
        utf8_buf[1] = (unsigned char)(0x80 | (utf16_code & 0x3F));
        return 2;
    }

    if (utf16_code >= 0xD800 && utf16_code <= 0xDFFF)
    {
        return EVA_ENCODING_ERROR_INPUT;
    }

    // 3-byte UTF-8
    if (buf_size < 3) return EVA_ENCODING_ERROR_OUTPUT;
    utf8_buf[0] = (unsigned char)(0xE0 | (utf16_code >> 12));
    utf8_buf[1] = (unsigned char)(0x80 | ((utf16_code >> 6) & 0x3F));
    utf8_buf[2] = (unsigned char)(0x80 | (utf16_code & 0x3F));
    return 3;
}

static void utf16_to_utf8(uint16_t utf16_code, char *utf8_buf, int buf_size)
{
    int utf8_len;

    if (buf_size <= 0)
    {
        return;
    }

    utf8_len = utf16_to_utf8_bytes(utf16_code, utf8_buf, buf_size - 1);
    if (utf8_len < 0)
    {
        utf8_buf[0] = '\0';
        return;
    }

    utf8_buf[utf8_len] = '\0';
}

static int is_custom_sjis_lead(uint8_t byte)
{
    return byte >= EVA_CUSTOM_LEAD_FIRST && byte <= EVA_CUSTOM_LEAD_LAST;
}

static int is_standard_sjis_lead(uint8_t byte)
{
    return (byte >= 0x81 && byte <= 0x9F) || (byte >= 0xE0 && byte <= 0xFC);
}

static int lookup_custom_utf16(uint16_t code, uint16_t *utf16_code)
{
    uint32_t index;
    uint32_t code_count;
    uint16_t mapped_code;

    if (!utf16_code || code < EVA_CUSTOM_SJIS_FIRST || code > EVA_CUSTOM_SJIS_LAST)
    {
        return 0;
    }

    index = code - EVA_CUSTOM_SJIS_FIRST;
    code_count = GB2312_CUSTOM_BIN_len / sizeof(uint16_t);
    if (index >= code_count)
    {
        return 0;
    }

    mapped_code = ((uint16_t *)GB2312_CUSTOM_BIN)[index];
    if (mapped_code == 0)
    {
        return 0;
    }

    *utf16_code = mapped_code;
    return 1;
}

static int lookup_sjis_utf16(uint16_t sjis, uint16_t *utf16_code)
{
    uint16_t *sjis_ranges = (uint16_t *)SJIS_bin;
    uint16_t *utf16_table = (uint16_t *)UTF16_bin;
    uint32_t utf16_count = UTF16_bin_len / sizeof(uint16_t);
    uint32_t range_count = SJIS_bin_len / (sizeof(uint16_t) * 2);
    uint32_t range_index;

    if (!utf16_code)
    {
        return 0;
    }

    for (range_index = 0; range_index < range_count; ++range_index)
    {
        uint32_t prefix = sjis_ranges[range_index << 1];
        uint32_t offset = sjis_ranges[(range_index << 1) + 1];
        uint32_t next_offset = utf16_count;
        uint32_t span;
        uint32_t table_offset;
        uint16_t mapped_code;

        if (range_index + 1 < range_count)
        {
            next_offset = sjis_ranges[((range_index + 1) << 1) + 1];
        }

        if (next_offset < offset)
        {
            return 0;
        }

        span = next_offset - offset;
        if (sjis < prefix || sjis >= prefix + span)
        {
            continue;
        }

        table_offset = offset + (sjis - prefix);
        if (table_offset >= utf16_count)
        {
            return 0;
        }

        mapped_code = utf16_table[table_offset];
        if (mapped_code == 0)
        {
            return 0;
        }

        *utf16_code = mapped_code;
        return 1;
    }

    return 0;
}

static int lookup_sjis_from_utf16(uint16_t utf16_code, uint16_t *sjis)
{
    uint16_t *sjis_ranges = (uint16_t *)SJIS_bin;
    uint16_t *utf16_table = (uint16_t *)UTF16_bin;
    uint32_t utf16_count = UTF16_bin_len / sizeof(uint16_t);
    uint32_t range_count = SJIS_bin_len / (sizeof(uint16_t) * 2);
    uint32_t range_index;

    if (!sjis || utf16_code == 0)
    {
        return 0;
    }

    for (range_index = 0; range_index < range_count; ++range_index)
    {
        uint32_t prefix = sjis_ranges[range_index << 1];
        uint32_t offset = sjis_ranges[(range_index << 1) + 1];
        uint32_t next_offset = utf16_count;
        uint32_t table_offset;

        if (range_index + 1 < range_count)
        {
            next_offset = sjis_ranges[((range_index + 1) << 1) + 1];
        }

        if (next_offset < offset || next_offset > utf16_count)
        {
            return 0;
        }

        for (table_offset = offset; table_offset < next_offset; ++table_offset)
        {
            if (utf16_table[table_offset] == utf16_code)
            {
                uint16_t candidate = (uint16_t)(prefix + table_offset - offset);

                /*
                 * The extended parser consumes 0xA6-0xDD as custom two-byte
                 * leads. Do not emit their original one-byte kana meanings.
                 */
                if (candidate <= 0xFF && is_custom_sjis_lead((uint8_t)candidate))
                {
                    continue;
                }

                *sjis = candidate;
                return 1;
            }
        }
    }

    return 0;
}

static int lookup_custom_from_utf16(uint16_t utf16_code, uint16_t *sjis)
{
    uint16_t *custom_table = (uint16_t *)GB2312_CUSTOM_BIN;
    uint32_t code_count = GB2312_CUSTOM_BIN_len / sizeof(uint16_t);
    uint32_t index;

    if (!sjis || utf16_code == 0)
    {
        return 0;
    }

    for (index = 0; index < code_count; ++index)
    {
        if (custom_table[index] == utf16_code)
        {
            *sjis = (uint16_t)(EVA_CUSTOM_SJIS_FIRST + index);
            return 1;
        }
    }

    return 0;
}

static int lookup_eva_sjis_from_utf16(uint16_t utf16_code, uint16_t *sjis)
{
    if (lookup_sjis_from_utf16(utf16_code, sjis))
    {
        return 1;
    }

    // The game text stream can still carry ASCII controls such as '\n'.
    if (utf16_code <= 0x7F)
    {
        *sjis = utf16_code;
        return 1;
    }

    return lookup_custom_from_utf16(utf16_code, sjis);
}

static int utf8_to_utf16_bytes(const char *input, int input_size, uint16_t *utf16_code)
{
    uint8_t byte0;
    uint8_t byte1;
    uint8_t byte2;
    uint16_t decoded_code;

    if (!input || input_size <= 0 || !utf16_code)
    {
        return EVA_ENCODING_ERROR_ARGUMENT;
    }

    byte0 = (uint8_t)input[0];
    if (byte0 <= 0x7F)
    {
        *utf16_code = byte0;
        return 1;
    }

    if (byte0 >= 0xC2 && byte0 <= 0xDF)
    {
        if (input_size < 2)
        {
            return EVA_ENCODING_ERROR_INPUT;
        }

        byte1 = (uint8_t)input[1];
        if ((byte1 & 0xC0) != 0x80)
        {
            return EVA_ENCODING_ERROR_INPUT;
        }

        *utf16_code = (uint16_t)(((byte0 & 0x1F) << 6) | (byte1 & 0x3F));
        return 2;
    }

    if (byte0 >= 0xE0 && byte0 <= 0xEF)
    {
        if (input_size < 3)
        {
            return EVA_ENCODING_ERROR_INPUT;
        }

        byte1 = (uint8_t)input[1];
        byte2 = (uint8_t)input[2];
        if ((byte1 & 0xC0) != 0x80 || (byte2 & 0xC0) != 0x80)
        {
            return EVA_ENCODING_ERROR_INPUT;
        }

        // Reject overlong UTF-8 and UTF-16 surrogate scalar values.
        if ((byte0 == 0xE0 && byte1 < 0xA0) || (byte0 == 0xED && byte1 >= 0xA0))
        {
            return EVA_ENCODING_ERROR_INPUT;
        }

        decoded_code = (uint16_t)(((byte0 & 0x0F) << 12) |
                                  ((byte1 & 0x3F) << 6) |
                                  (byte2 & 0x3F));
        *utf16_code = decoded_code;
        return 3;
    }

    // The table-backed game encoding cannot represent supplementary planes.
    return EVA_ENCODING_ERROR_UNMAPPABLE;
}

static void terminate_utf8_output(char *output, int output_size, int output_index)
{
    if (!output || output_size <= 0)
    {
        return;
    }

    if (output_index >= output_size)
    {
        output_index = output_size - 1;
    }

    output[output_index] = '\0';
}

static void terminate_eva_sjis_output(uint8_t *output, int output_size, int output_index)
{
    if (!output || output_size <= 0)
    {
        return;
    }

    if (output_index >= output_size)
    {
        output_index = output_size - 1;
    }

    output[output_index] = '\0';
}

uint16_t translate_code(u16 code)
{
    if (code >= 0xA600 && code <= 0xDDFF)
    {
        return modified_to_utf16(code);
    }
    return sjis_to_utf16(code);
}

/**
Use 0xA6-0xDD to store GB2312 Chinese Characters
*/
uint16_t modified_to_utf16(u16 code)
{
    uint16_t utf16_code;

#ifdef LOG
    logPrintf("Modified to UTF16: %x", code);
#endif

    if (!lookup_custom_utf16(code, &utf16_code))
    {
#ifdef LOG
        logPrintf("Modified code not found: %x", code);
#endif
        return 0x003f;
    }

    return utf16_code;
}

// FUN_08884680
uint16_t sjis_to_utf16(u16 sjis)
{
    uint16_t utf16_code;
#ifdef LOG
    logPrintf("SHIFT-JIS: %x", sjis);
#endif

    if (!lookup_sjis_utf16(sjis, &utf16_code))
    {
        // Return '?' if not found
        return 0x003f;
    }

    // Print UTF-16 and UTF-8 result for debugging
    char utf8_buf[4];
    utf16_to_utf8(utf16_code, utf8_buf, sizeof(utf8_buf));

#ifdef LOG
    logPrintf("UTF-16 Code: 0x%04X", utf16_code);
    logPrintf("UTF-8 Result: %s", utf8_buf);
#endif

    return utf16_code;
}

int eva_sjis_to_utf8(const uint8_t *input, int input_size, char *output, int output_size)
{
    int input_index = 0;
    int output_index = 0;

    if (!input || input_size < 0 || !output || output_size <= 0)
    {
        return EVA_ENCODING_ERROR_ARGUMENT;
    }

    output[0] = '\0';

    while (input_index < input_size)
    {
        uint8_t first_byte = input[input_index];
        uint16_t utf16_code;
        int consumed = 1;
        int utf8_size;

        if (first_byte < 0x20 || first_byte == 0x7F)
        {
            utf16_code = first_byte;
        }
        else if (is_custom_sjis_lead(first_byte))
        {
            uint16_t custom_code;

            if (input_index + 1 >= input_size)
            {
                terminate_utf8_output(output, output_size, output_index);
                return EVA_ENCODING_ERROR_INPUT;
            }

            custom_code = (uint16_t)((first_byte << 8) | input[input_index + 1]);
            if (!lookup_custom_utf16(custom_code, &utf16_code))
            {
                terminate_utf8_output(output, output_size, output_index);
                return EVA_ENCODING_ERROR_INPUT;
            }
            consumed = 2;
        }
        else if (is_standard_sjis_lead(first_byte))
        {
            uint16_t sjis_code;

            if (input_index + 1 >= input_size)
            {
                terminate_utf8_output(output, output_size, output_index);
                return EVA_ENCODING_ERROR_INPUT;
            }

            sjis_code = (uint16_t)((first_byte << 8) | input[input_index + 1]);
            if (!lookup_sjis_utf16(sjis_code, &utf16_code))
            {
                terminate_utf8_output(output, output_size, output_index);
                return EVA_ENCODING_ERROR_INPUT;
            }
            consumed = 2;
        }
        else if (!lookup_sjis_utf16(first_byte, &utf16_code))
        {
            terminate_utf8_output(output, output_size, output_index);
            return EVA_ENCODING_ERROR_INPUT;
        }

        utf8_size = utf16_to_utf8_bytes(utf16_code, output + output_index,
                                        output_size - output_index - 1);
        if (utf8_size < 0)
        {
            terminate_utf8_output(output, output_size, output_index);
            return utf8_size;
        }

        output_index += utf8_size;
        input_index += consumed;
    }

    output[output_index] = '\0';
    return output_index;
}

int utf8_to_eva_sjis(const char *input, int input_size, uint8_t *output, int output_size)
{
    int input_index = 0;
    int output_index = 0;

    if (!input || input_size < 0 || !output || output_size <= 0)
    {
        return EVA_ENCODING_ERROR_ARGUMENT;
    }

    output[0] = '\0';

    while (input_index < input_size)
    {
        uint16_t utf16_code;
        uint16_t sjis_code;
        int utf8_size = utf8_to_utf16_bytes(input + input_index, input_size - input_index,
                                            &utf16_code);
        int sjis_size;

        if (utf8_size < 0)
        {
            terminate_eva_sjis_output(output, output_size, output_index);
            return utf8_size;
        }

        if (!lookup_eva_sjis_from_utf16(utf16_code, &sjis_code))
        {
            terminate_eva_sjis_output(output, output_size, output_index);
            return EVA_ENCODING_ERROR_UNMAPPABLE;
        }

        sjis_size = sjis_code <= 0xFF ? 1 : 2;
        if (output_index + sjis_size >= output_size)
        {
            terminate_eva_sjis_output(output, output_size, output_index);
            return EVA_ENCODING_ERROR_OUTPUT;
        }

        if (sjis_size == 2)
        {
            output[output_index++] = (uint8_t)(sjis_code >> 8);
        }
        output[output_index++] = (uint8_t)(sjis_code & 0xFF);
        input_index += utf8_size;
    }

    output[output_index] = '\0';
    return output_index;
}

// FUN_08884724
// binary_search function
int binary_search(uint16_t target, int low, int high)
{

    u16 *DAT_08a3325c = (u16 *)(SJIS_bin);
    // u16 *UTF16_TABLE = (u16 *)(UTF16_bin);
    low = low & 0xFFFF;
    high = high & 0xFFFF;

    while (low <= high)
    {
        int mid = ((low + high) >> 1);

        // 0x44 0x29 0x8b 0x8f
        uint16_t mid_val = DAT_08a3325c[mid << 1] & 0xFFFF;
        uint16_t next_val = DAT_08a3325c[(mid << 1) + 2] & 0xFFFF;

        if (target >= mid_val && (mid == high || target < next_val))
        {
#ifdef LOG
            logPrintf("Found: %x", mid);
#endif
            return mid;
        }
        else if (mid_val < target)
        {
            low = (mid + 1);
        }
        else
        {
            high = (mid - 1);
        }
    }
#ifdef LOG
    logPrintf("Not Found: %x", target);
#endif

    return -1; // 如果未找到目标值，则返回 -1
}
