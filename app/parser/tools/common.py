#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import struct
import os
import sys
from functools import lru_cache

from app.utils.map import CUSTOM_ENCODE_MAP

# Check encoding only when stdout exposes an encoding.
if sys.stdout and hasattr(sys.stdout, 'encoding') and sys.stdout.encoding:
    if (sys.stdout.encoding.lower().strip().replace('-', '').replace(' ', '') != 'utf8'):
        print("Your system\'s default terminal/screen encoding is not UTF-8.\n"
              "Please rerun this script by first setting\n"
              "PYTHONIOENCODING to utf-8.\n"
              "On Windows:\n"
              "set PYTHONIOENCODING=utf-8\n"
              "On Unix:\n"
              "export PYTHONIOENCODING=utf-8")
        sys.exit(-1)

# Common helper functions
def read_uint8(file_handle):
    return ord(file_handle.read(1))

def read_uint16(file_handle):
    return struct.unpack('H', file_handle.read(2))[0]

def read_uint32(file_handle):
    return struct.unpack('I', file_handle.read(4))[0]

def write_uint8(file_handle, value):
    return file_handle.write(struct.pack('B', value))

def write_uint16(file_handle, value):
    return file_handle.write(struct.pack('H', value))

def write_uint32(file_handle, value):
    return file_handle.write(struct.pack('I', value))

def calculate_word_aligned_length(unaligned_length):
    return 4 * int((unaligned_length + 3) / 4)

def get_file_size(file_handle):
    return os.fstat(file_handle.fileno()).st_size
    
def align_size(unaligned_size, alignment):
    return alignment * int((unaligned_size + alignment - 1) / alignment)

def zero_pad_and_align_string(content):
    # Pad string to a size divisible by 4
    padded_length = 4 * int((len(content) + 4) / 4)
    return (content + b'\0\0\0\0')[0:padded_length]

def from_eva_sjis(content):
    # Convert nge2 SJIS to unicode
    try:
        content = content.decode('shift_jis')

    except UnicodeDecodeError:
        raise Exception('There seems to be a character that cannot be converted to unicode. Check the text:' + repr(content))

    # Convert special NGE2 characters
    #content = content.replace('Θ', 'J.')
    #content = content.replace('Α', 'A.')
    #content = content.replace('Τ', 'T.')
    #content = content.replace('Ν', 'N²')
    #content = content.replace('Σ', 'S²')
    #content = content.replace('Ｓ', 'S')

    return content

# ===== 性能优化：字符编码缓存机制 =====
# 构建自定义字符映射字典（仅在模块加载时执行一次，避免每次编码时遍历列表）
_CUSTOM_CHAR_MAP = {entry['char']: bytes.fromhex(entry['custom_code'][2:]) for entry in CUSTOM_ENCODE_MAP}

@lru_cache(maxsize=2048)
def _encode_char_cached(char):
    """
    缓存单个字符的编码结果
    
    优化原理：
    1. 使用LRU缓存避免重复编码相同字符（常用汉字/假名会被反复使用）
    2. 预先将CUSTOM_ENCODE_MAP转为字典，O(1)查找替代O(n)遍历
    3. 减少try-except开销，只在首次编码字符时触发
    """
    # FIXME: 这些应该在原文进行修正
    # 1. '-' 转换为 'ー'
    # 英文输入法下的连字符是(-, U+002D)
    # 中文输入法下的破折号是（—, U+2014）
    # 日文中常用的长音符号是(ー, U+30FC)
    # 另外还存在一种破折号（―, U+2015） 
    # GB2312 会将破折号映射为 U+2015 (HORIZONTAL BAR), 而 GBK 映射到 U+2014 与现在输入法行为相符。
    if char == '—':
        # U+2014 maps to custom code A6 0A, whose second byte is interpreted
        # as a line feed by some game text parsers. U+2015 is native Shift_JIS.
        char = '―'
    
    # 2. '~'和'～'转换
    # 英文输入法下的波浪号是（~, U+007E）
    # 中文输入法往往会输入全角波浪号（～, U+FF5E），而日文则使用波浪号（〜, U+301C）
    # CP932: \uff5e FULLWIDTH TILDE (U+FF5E)
    # SHIFT_JIS: \u301c WAVE DASH (U+301C)
    if char == '~' or char == '～':
        char = '〜'
    
    # 首先尝试将字符编码为 Shift_JIS
    try:
        return char.encode('shift_jis')
    except UnicodeEncodeError:
        # 然后尝试将字符编码为 GB2312（修改后）
        # Find the Entry in which its 'char' equals to char in CUSTOM_ENCODE_MAP
        encoded_char = _CUSTOM_CHAR_MAP.get(char)
        if encoded_char is not None:
            return encoded_char
        # FIXME: If no custom code is found, fallback to a placeholder character
        return b'?'  # Fallback to a placeholder character

def to_eva_sjis(content):
    """
    Convert special NGE2 characters
    Convert unicode to nge2 SJIS
    
    优化原理：
    1. 使用生成器表达式 + b''.join() 替代 bytearray().extend() 循环
       - 减少函数调用开销（extend被调用27640次）
       - 一次性分配内存，避免多次扩容
    2. 每个字符的编码结果会被_encode_char_cached缓存
       - 常用字符（如"的""了""是"等）只需编码一次
       - 后续直接返回缓存结果，避免重复的encode()和异常处理
    3. 预计性能提升：从7.9秒降至1-2秒（减少80%以上）
    """
    # We let most remain as regular ASCII
    #content = content.replace('N²', 'Ν')
    #content = content.replace('S²', 'Σ')
    return b''.join(_encode_char_cached(char) for char in content)

def unique_color(index, total):
    if index == -1:
        return (0, 0, 0)

    if total == 0:
        return (255, 255, 255)

    fractional = index/float(total)
    sectofractional = 6 * fractional
    sectointeger = int(sectofractional)
    sectoremainder = sectofractional - sectointeger
    subsectofractional = min(int(sectoremainder * 256), 255)
    subremaindersectofractional = min(int((1 - sectoremainder) * 256), 255)

    if sectointeger == 0:
        return (255, subsectofractional, 0)

    if sectointeger == 1:
        return (subremaindersectofractional, 255, 0)

    if sectointeger == 2:
        return (0, 255, subsectofractional)

    if sectointeger == 3:
        return (0, subremaindersectofractional, 255)

    if sectointeger == 4:
        return (subsectofractional, 0, 255)

    return (255, 0, subremaindersectofractional)
