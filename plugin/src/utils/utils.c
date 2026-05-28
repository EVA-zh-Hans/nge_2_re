#include "utils.h"

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>

/* ========== 辅助函数 ========== */

static int uint_to_str(unsigned long long val, char *buf, int base, int uppercase)
{
    const char *digits_lower = "0123456789abcdef";
    const char *digits_upper = "0123456789ABCDEF";
    const char *digits = uppercase ? digits_upper : digits_lower;

    char tmp[64];
    int  len = 0;

    if (val == 0) {
        buf[0] = '0';
        buf[1] = '\0';
        return 1;
    }

    while (val > 0) {
        tmp[len++] = digits[val % base];
        val /= base;
    }

    /* 反转 */
    for (int i = 0; i < len; i++)
        buf[i] = tmp[len - 1 - i];
    buf[len] = '\0';

    return len;
}

static int str_len(const char *s)
{
    int n = 0;
    while (s[n]) n++;
    return n;
}

/* ========== 核心实现 ========== */

int my_sprintf(char *buf, const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);

    int  pos = 0;   /* 写入位置 */

    for (int i = 0; fmt[i] != '\0'; i++) {

        if (fmt[i] != '%') {
            buf[pos++] = fmt[i];
            continue;
        }

        i++;  /* 跳过 '%' */

        /* ---------- 解析标志 flags ---------- */
        int flag_minus = 0;  /* 左对齐      */
        int flag_zero  = 0;  /* 补零        */
        int flag_plus  = 0;  /* 强制显示符号 */
        int flag_space = 0;  /* 空格填充符号 */
        int flag_hash  = 0;  /* '#' 前缀    */

        for (;;) {
            if      (fmt[i] == '-') { flag_minus = 1; i++; }
            else if (fmt[i] == '0') { flag_zero  = 1; i++; }
            else if (fmt[i] == '+') { flag_plus  = 1; i++; }
            else if (fmt[i] == ' ') { flag_space = 1; i++; }
            else if (fmt[i] == '#') { flag_hash  = 1; i++; }
            else break;
        }

        /* ---------- 解析宽度 width ---------- */
        int width = 0;
        if (fmt[i] == '*') {
            width = va_arg(args, int);
            if (width < 0) { flag_minus = 1; width = -width; }
            i++;
        } else {
            while (fmt[i] >= '0' && fmt[i] <= '9') {
                width = width * 10 + (fmt[i] - '0');
                i++;
            }
        }

        /* ---------- 解析精度 precision ---------- */
        int precision     = -1;  /* -1 表示未指定 */
        int has_precision =  0;
        if (fmt[i] == '.') {
            has_precision = 1;
            i++;
            if (fmt[i] == '*') {
                precision = va_arg(args, int);
                if (precision < 0) precision = 0;
                i++;
            } else {
                precision = 0;
                while (fmt[i] >= '0' && fmt[i] <= '9') {
                    precision = precision * 10 + (fmt[i] - '0');
                    i++;
                }
            }
        }

        /* ---------- 解析长度修饰符 ---------- */
        int mod_long      = 0;  /* l  */
        int mod_longlong  = 0;  /* ll */
        int mod_short     = 0;  /* h  */
        int mod_char      = 0;  /* hh */

        if (fmt[i] == 'l') {
            i++;
            if (fmt[i] == 'l') { mod_longlong = 1; i++; }
            else                  mod_long     = 1;
        } else if (fmt[i] == 'h') {
            i++;
            if (fmt[i] == 'h') { mod_char  = 1; i++; }
            else                  mod_short = 1;
        }

        /* ---------- 转换说明符 ---------- */
        char spec = fmt[i];

        /* ===== %% ===== */
        if (spec == '%') {
            buf[pos++] = '%';
            continue;
        }

        /* ===== %c ===== */
        if (spec == 'c') {
            char c = (char)va_arg(args, int);
            if (!flag_minus)
                for (int k = 1; k < width; k++) buf[pos++] = ' ';
            buf[pos++] = c;
            if (flag_minus)
                for (int k = 1; k < width; k++) buf[pos++] = ' ';
            continue;
        }

        /* ===== %s ===== */
        if (spec == 's') {
            const char *s = va_arg(args, const char *);
            if (!s) s = "(null)";

            int slen = str_len(s);
            if (has_precision && precision < slen) slen = precision;

            int pad = (width > slen) ? (width - slen) : 0;

            if (!flag_minus)
                for (int k = 0; k < pad; k++) buf[pos++] = ' ';
            for (int k = 0; k < slen; k++) buf[pos++] = s[k];
            if (flag_minus)
                for (int k = 0; k < pad; k++) buf[pos++] = ' ';
            continue;
        }

        /* ===== 整数类 %d %i %u %o %x %X %p ===== */
        if (spec == 'd' || spec == 'i' || spec == 'u' ||
            spec == 'o' || spec == 'x' || spec == 'X' || spec == 'p')
        {
            /* 1. 取值 */
            long long  sval = 0;
            unsigned long long uval = 0;
            int is_signed = (spec == 'd' || spec == 'i');

            if (spec == 'p') {
                uval = (unsigned long long)(uintptr_t)va_arg(args, void *);
            } else if (is_signed) {
                if      (mod_longlong) sval = va_arg(args, long long);
                else if (mod_long)     sval = va_arg(args, long);
                else if (mod_short)    sval = (short)va_arg(args, int);
                else if (mod_char)     sval = (signed char)va_arg(args, int);
                else                   sval = va_arg(args, int);
                uval = (unsigned long long)(sval < 0 ? -sval : sval);
            } else {
                if      (mod_longlong) uval = va_arg(args, unsigned long long);
                else if (mod_long)     uval = va_arg(args, unsigned long);
                else if (mod_short)    uval = (unsigned short)va_arg(args, unsigned int);
                else if (mod_char)     uval = (unsigned char)va_arg(args, unsigned int);
                else                   uval = va_arg(args, unsigned int);
            }

            /* 2. 选择进制 */
            int base      = 10;
            int uppercase = 0;
            if (spec == 'o')                  base = 8;
            else if (spec == 'x' || spec == 'p') base = 16;
            else if (spec == 'X') { base = 16; uppercase = 1; }

            /* 3. 数字串 */
            char num_buf[64];
            int  num_len = uint_to_str(uval, num_buf, base, uppercase);

            /* 4. 精度补零 */
            int prec_zeros = 0;
            if (has_precision && precision > num_len)
                prec_zeros = precision - num_len;

            /* 5. 前缀 */
            char prefix[4] = {0};
            int  prefix_len = 0;
            if (spec == 'p') {
                prefix[prefix_len++] = '0';
                prefix[prefix_len++] = 'x';
            } else if (is_signed) {
                if      (sval < 0)   prefix[prefix_len++] = '-';
                else if (flag_plus)  prefix[prefix_len++] = '+';
                else if (flag_space) prefix[prefix_len++] = ' ';
            } else if (flag_hash) {
                if (spec == 'o' && num_buf[0] != '0')
                    prefix[prefix_len++] = '0';
                else if (spec == 'x') { prefix[prefix_len++] = '0'; prefix[prefix_len++] = 'x'; }
                else if (spec == 'X') { prefix[prefix_len++] = '0'; prefix[prefix_len++] = 'X'; }
            }

            /* 6. 计算总长度与填充 */
            int total_len = prefix_len + prec_zeros + num_len;
            int pad       = (width > total_len) ? (width - total_len) : 0;
            char pad_char = (flag_zero && !flag_minus && !has_precision) ? '0' : ' ';

            /* 7. 写入 */
            if (!flag_minus && pad_char == ' ')
                for (int k = 0; k < pad; k++) buf[pos++] = ' ';

            for (int k = 0; k < prefix_len; k++) buf[pos++] = prefix[k];

            if (!flag_minus && pad_char == '0')
                for (int k = 0; k < pad; k++) buf[pos++] = '0';

            for (int k = 0; k < prec_zeros; k++) buf[pos++] = '0';
            for (int k = 0; k < num_len;    k++) buf[pos++] = num_buf[k];

            if (flag_minus)
                for (int k = 0; k < pad; k++) buf[pos++] = ' ';

            continue;
        }

        /* ===== %f 简易浮点 ===== */
        if (spec == 'f') {
            double val = va_arg(args, double);
            int    prec = has_precision ? precision : 6;

            /* 符号 */
            char sign = 0;
            if (val < 0)        { sign = '-'; val = -val; }
            else if (flag_plus) { sign = '+'; }
            else if (flag_space){ sign = ' '; }

            /* 整数部分 */
            unsigned long long int_part  = (unsigned long long)val;
            double             frac_part = val - (double)int_part;

            /* 小数部分：乘以 10^prec 四舍五入 */
            unsigned long long frac_int = 0;
            double multiplier = 1.0;
            for (int k = 0; k < prec; k++) multiplier *= 10.0;
            frac_int = (unsigned long long)(frac_part * multiplier + 0.5);

            /* 进位处理 */
            unsigned long long frac_limit = (unsigned long long)multiplier;
            if (frac_int >= frac_limit) { int_part++; frac_int -= frac_limit; }

            char int_buf[32], frac_buf[32];
            int  int_len  = uint_to_str(int_part,  int_buf,  10, 0);
            int  frac_len = prec > 0 ? uint_to_str(frac_int, frac_buf, 10, 0) : 0;

            /* 小数部分补前导零 */
            char frac_pad_buf[32] = {0};
            int  fp = 0;
            if (prec > 0) {
                int leading = prec - frac_len;
                for (int k = 0; k < leading;   k++) frac_pad_buf[fp++] = '0';
                for (int k = 0; k < frac_len;  k++) frac_pad_buf[fp++] = frac_buf[k];
                frac_pad_buf[fp] = '\0';
            }

            /* 总长度 */
            int total = (sign ? 1 : 0) + int_len + (prec > 0 ? 1 + prec : 0);
            int pad   = (width > total) ? (width - total) : 0;
            char pc   = (flag_zero && !flag_minus) ? '0' : ' ';

            if (!flag_minus && pc == ' ') for (int k = 0; k < pad; k++) buf[pos++] = ' ';
            if (sign) buf[pos++] = sign;
            if (!flag_minus && pc == '0') for (int k = 0; k < pad; k++) buf[pos++] = '0';

            for (int k = 0; k < int_len; k++) buf[pos++] = int_buf[k];
            if (prec > 0) {
                buf[pos++] = '.';
                for (int k = 0; k < prec; k++) buf[pos++] = frac_pad_buf[k];
            }
            if (flag_minus) for (int k = 0; k < pad; k++) buf[pos++] = ' ';
            continue;
        }

        /* 未识别的说明符：原样输出 */
        buf[pos++] = '%';
        buf[pos++] = spec;
    }

    buf[pos] = '\0';
    va_end(args);
    return pos;
}

char *strcpy(char *dest, const char *src)
{
    char *ret = dest;
    while ((*dest++ = *src++) != '\0')
        ;
    return ret;
}

// strlen(src) < n: only fill one '\0' at the end of dest
// strlen(src) == n: dest is not null-terminated
char *strcpyn(char *dest, const char *src, size_t n)
{
    char *ret = dest;
    size_t i;
    for (i = 0; i < n && src[i] != '\0'; i++)
        dest[i] = src[i];
    if (i < n)
        dest[i] = '\0';
    return ret;
}