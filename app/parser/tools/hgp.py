#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import numpy as np
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional

try:
    from . import common
    from .pillow_png import read_png, write_indexed_png, write_rgb_png, write_rgba_png
except ImportError:
    import common
    from pillow_png import read_png, write_indexed_png, write_rgb_png, write_rgba_png

# region: --- 1. 核心数据模型 ---
# 这些类精确地映射了HGPT文件格式的各个逻辑部分，使得代码结构与文件结构保持一致。

class HgptHeader:
    """
    封装 HGPT 文件的核心头部信息。
    这对应文件开头的 16 字节（或更多，取决于扩展头）。
    """
    def __init__(self):
        self.magic_number: str = 'HGPT'
        self.pp_offset: int = 0
        self.has_extended_header: bool = False
        self.number_of_divisions: int = 0
        self.unknown_one: int = 0x0001
        self.unknown_two: int = 0
        self.unknown_three: int = 0x0013

class DisplayInfo:
    """
    对应 PP 段，封装图像的显示尺寸。
    """
    def __init__(self, width: int = 0, height: int = 0):
        self.width = width
        self.height = height

class DivisionInfo:
    """
    对应文件的扩展头部分，封装分区信息。
    仅当 header.has_extended_header 为 True 时存在。
    """
    def __init__(self, name: str = '', divisions: Optional[List[Tuple[int, int, int, int]]] = None):
        self.name = name
        self.divisions = divisions if divisions is not None else []

class Palette:
    """
    对应 PPC 段，封装调色板数据。
    仅当图像为调色板模式时存在。
    """
    def __init__(self, colors: Optional[List[Tuple[int, int, int, int]]] = None):
        self.colors = colors if colors is not None else []

    def __len__(self) -> int:
        return len(self.colors)

class HgptImage:
    """
    表示一个完整的 HGPT 图像，由多个专注的部分组成。
    这是整个解析和写入过程的核心对象。
    """
    def __init__(self, 
                 header: HgptHeader, 
                 display_info: DisplayInfo, 
                 content: list, 
                 palette: Optional[Palette] = None, 
                 division_info: Optional[DivisionInfo] = None):
        self.header = header
        self.display_info = display_info
        self.content = content  # 线性（非瓦片化）的像素数据
        self.palette = palette
        self.division_info = division_info

# endregion

# region: --- 2. 瓦片处理器 ---
# 使用策略模式，为每种像素格式提供一个专门的处理器。
# 这将格式相关的逻辑（如瓦片尺寸、像素编码）与文件读写流程解耦。

class TileProcessor(ABC):
    """
    处理瓦片化图像数据的抽象基类 (ABC)。
    定义了所有瓦片处理器必须遵守的接口。
    """
    def __init__(self, display_info: DisplayInfo):
        self.display_info = display_info

    @property
    @abstractmethod
    def pp_format(self) -> int:
        """返回此处理器对应的 PP 格式代码 (如 0x13, 0x14, 0x8800)。"""
        pass

    @property
    @abstractmethod
    def tile_width(self) -> int:
        """返回此格式的瓦片宽度。"""
        pass
        
    @property
    def tile_height(self) -> int:
        """瓦片高度通常是固定的 8。"""
        return 8

    @property
    @abstractmethod
    def bytes_per_pixel(self) -> float:
        """返回每个像素占用的字节数（可以是小数，如0.5）。"""
        pass
        
    @property
    def bytes_per_pixel_ppd_size(self) -> float:
        """返回在计算 PPD 大小时使用的每像素字节数（对于 RGBA 格式是特例）。"""
        return self.bytes_per_pixel

    def get_storage_dims(self) -> Tuple[int, int]:
        """计算存储数据的实际尺寸（对齐后的尺寸）。"""
        storage_width = common.align_size(self.display_info.width, self.tile_width)
        storage_height = common.align_size(self.display_info.height, self.tile_height)
        return storage_width, storage_height

    @abstractmethod
    def decode(self, f, number_of_pixels: int) -> list:
        """从文件流解码瓦片化的像素数据。"""
        pass

    @abstractmethod
    def encode(self, f, tiled_image_data: list):
        """将瓦片化的像素数据编码并写入文件流。"""
        pass

    def untile(self, tiled_data: list, storage_width: int, storage_height: int) -> list:
        """将瓦片数据重新排列为线性的像素数据（用于显示或导出）。使用 NumPy 优化。"""
        display_width = self.display_info.width
        display_height = self.display_info.height
        tile_w = self.tile_width
        tile_h = self.tile_height
        
        # 将输入转换为 NumPy 数组（如果还不是）
        # 优化：对于 list of integers (0-255)，使用 np.frombuffer 零拷贝转换
        if isinstance(tiled_data, list):
            # 检查是否为简单的整数列表（适用于 8-bit 调色板格式）
            if tiled_data and isinstance(tiled_data[0], int) and not isinstance(tiled_data[0], tuple):
                # 使用 np.frombuffer 零拷贝转换，避免 np.array() 的内存复制
                tiled_array = np.frombuffer(bytes(tiled_data), dtype=np.uint8)
            else:
                # 对于复杂类型（如 tuples），仍使用 np.array()
                tiled_array = np.array(tiled_data)
        else:
            tiled_array = tiled_data
        
        # 计算瓦片相关参数
        tiles_per_row = storage_width // tile_w
        tiles_per_col = storage_height // tile_h
        pixel_shape = tiled_array.shape[1:]

        # RGBA data has a trailing channel dimension which must not take part
        # in the tile-coordinate reshape.
        tiled_reshaped = tiled_array.reshape(
            tiles_per_col, tiles_per_row, tile_h, tile_w, *pixel_shape
        )
        
        # 转置轴以获得正确的布局：(tiles_per_col, tile_h, tiles_per_row, tile_w)
        transposed = tiled_reshaped.transpose(
            0, 2, 1, 3, *range(4, tiled_reshaped.ndim)
        )
        
        # 重塑为最终的图像形状：(storage_height, storage_width)
        untiled = transposed.reshape(storage_height, storage_width, *pixel_shape)
        
        # 裁剪到显示尺寸
        result = untiled[:display_height, :display_width]
        
        # 转换回列表（保持接口一致性）
        if pixel_shape:
            return [tuple(pixel) for pixel in result.reshape(-1, *pixel_shape).tolist()]
        return result.reshape(-1).tolist()

    def tile(self, content: list, storage_width: int, storage_height: int) -> list:
        """将线性的像素数据排列为瓦片数据（用于写入文件）。使用 NumPy 优化。"""
        display_width = self.display_info.width
        display_height = self.display_info.height
        tile_w = self.tile_width
        tile_h = self.tile_height
        
        # 将输入转换为 NumPy 数组
        # 优化：对于 list of integers (0-255)，使用 np.frombuffer 零拷贝转换
        if isinstance(content, list):
            # 检查是否为简单的整数列表（适用于 8-bit 调色板格式）
            if content and isinstance(content[0], int) and not isinstance(content[0], tuple):
                # 使用 np.frombuffer 零拷贝转换，避免 np.array() 的内存复制
                content_array = np.frombuffer(bytes(content), dtype=np.uint8)
            else:
                # 对于复杂类型（如 tuples），仍使用 np.array()
                content_array = np.array(content)
        else:
            content_array = content
        
        pixel_shape = content_array.shape[1:]

        # 重塑为图像，同时保留 RGBA 等像素的尾随通道维。
        image = content_array.reshape(display_height, display_width, *pixel_shape)
        
        # 填充到存储尺寸
        if storage_height > display_height or storage_width > display_width:
            padded = np.zeros(
                (storage_height, storage_width, *pixel_shape), dtype=image.dtype
            )
            padded[:display_height, :display_width] = image
        else:
            padded = image
        
        # 计算瓦片参数
        tiles_per_row = storage_width // tile_w
        tiles_per_col = storage_height // tile_h
        
        # 重塑为瓦片布局：(tiles_per_col, tile_h, tiles_per_row, tile_w)
        reshaped = padded.reshape(
            tiles_per_col, tile_h, tiles_per_row, tile_w, *pixel_shape
        )
        
        # 转置轴以获得瓦片格式：(tiles_per_col, tiles_per_row, tile_h, tile_w)
        transposed = reshaped.transpose(0, 2, 1, 3, *range(4, reshaped.ndim))
        
        # 展平为一维数组
        if pixel_shape:
            tiled = transposed.reshape(-1, *pixel_shape)
        else:
            tiled = transposed.reshape(-1)
        
        # 转换回列表
        return tiled.tolist()

class TileProcessor13(TileProcessor):
    """处理器，用于 pp_format 0x13 (8-bit paletted, 256色)。"""
    @property
    def pp_format(self): return 0x13
    @property
    def tile_width(self): return 16
    @property
    def bytes_per_pixel(self): return 1.0

    def decode(self, f, number_of_pixels):
        # 批量读取：一次性读取所有字节，使用 np.frombuffer 零拷贝转换为 numpy 数组
        # 优化：避免 list() 和 np.array() 的内存复制开销
        data = f.read(number_of_pixels)
        return np.frombuffer(data, dtype=np.uint8)

    def encode(self, f, tiled_image_data):
        # 批量写入：如果已经是 numpy 数组，使用 tobytes() 更高效
        if isinstance(tiled_image_data, np.ndarray):
            f.write(tiled_image_data.tobytes())
        else:
            f.write(bytes(tiled_image_data))

class TileProcessor14(TileProcessor):
    """处理器，用于 pp_format 0x14 (4-bit paletted, 16色)。"""
    @property
    def pp_format(self): return 0x14
    @property
    def tile_width(self): return 32
    @property
    def bytes_per_pixel(self): return 0.5
    
    def decode(self, f, number_of_pixels):
        # 批量读取：一次性读取所有字节，使用 numpy 向量化操作解包
        byte_count = (number_of_pixels + 1) // 2
        raw_data = f.read(byte_count)
        
        # 使用 np.frombuffer 零拷贝读取原始字节
        raw_array = np.frombuffer(raw_data, dtype=np.uint8)
        
        # 向量化解包：低4位和高4位
        low_nibbles = raw_array & 0x0F
        high_nibbles = (raw_array >> 4) & 0x0F
        
        # 交错合并：低4位和高4位交替
        data = np.empty(number_of_pixels, dtype=np.uint8)
        data[0::2] = low_nibbles[:len(data[0::2])]
        if number_of_pixels > 1:
            data[1::2] = high_nibbles[:len(data[1::2])]
        
        return data

    def encode(self, f, tiled_image_data):
        # 批量写入：使用 numpy 向量化操作打包 4-bit 数据
        if isinstance(tiled_image_data, np.ndarray):
            data_array = tiled_image_data
        else:
            data_array = np.array(tiled_image_data, dtype=np.uint8)
        
        data_len = len(data_array)
        byte_count = (data_len + 1) // 2
        
        # 向量化打包：低4位和高4位
        low_nibbles = data_array[0::2] & 0x0F
        high_nibbles = (data_array[1::2] & 0x0F) << 4 if data_len > 1 else np.array([], dtype=np.uint8)
        
        # 合并：每个字节 = 高4位 | 低4位
        packed_data = np.zeros(byte_count, dtype=np.uint8)
        packed_data[:len(low_nibbles)] = low_nibbles
        if len(high_nibbles) > 0:
            # 高4位需要左移4位后与低4位合并
            min_len = min(len(packed_data), len(high_nibbles))
            packed_data[:min_len] |= high_nibbles[:min_len]
        
        f.write(packed_data.tobytes())

class TileProcessor8800(TileProcessor):
    """处理器，用于 pp_format 0x8800 (32-bit RGBA)。"""
    @property
    def pp_format(self): return 0x8800
    @property
    def tile_width(self): return 4
    @property
    def bytes_per_pixel(self): return 4.0
    @property
    def bytes_per_pixel_ppd_size(self): return 1.0 # PPD尺寸计算的特殊情况

    def _decode_alpha(self, encoded_alpha):
        return min(encoded_alpha << 1, 0xFF)

    def _encode_alpha(self, alpha):
        alpha >>= 1
        return 0x80 if alpha == 0x7F else alpha

    def decode(self, f, number_of_pixels):
        # 批量读取：一次性读取所有 RGBA 数据
        raw_data = f.read(number_of_pixels * 4)
        
        data = []
        for i in range(number_of_pixels):
            offset = i * 4
            r = raw_data[offset]
            g = raw_data[offset + 1]
            b = raw_data[offset + 2]
            a_encoded = raw_data[offset + 3]
            data.append((r, g, b, self._decode_alpha(a_encoded)))
        return data

    def encode(self, f, tiled_image_data):
        # 批量写入：先构建完整的 RGBA 字节数组，然后一次性写入
        pixel_count = len(tiled_image_data)
        packed_data = bytearray(pixel_count * 4)
        
        for i, pixel in enumerate(tiled_image_data):
            r, g, b, a = pixel
            offset = i * 4
            packed_data[offset] = r
            packed_data[offset + 1] = g
            packed_data[offset + 2] = b
            packed_data[offset + 3] = self._encode_alpha(a)
        
        f.write(packed_data)
            
def get_tile_processor(pp_format: int, display_info: DisplayInfo) -> TileProcessor:
    """工厂函数，根据 pp_format 返回相应的处理器实例。"""
    if pp_format == 0x13:
        return TileProcessor13(display_info)
    elif pp_format == 0x14:
        return TileProcessor14(display_info)
    elif pp_format == 0x8800:
        return TileProcessor8800(display_info)
    else:
        raise ValueError(f'Unsupported pp_format: 0x{pp_format:X}')

# endregion

# region: --- 3. 文件读写器 ---
# 这部分逻辑负责处理文件的 I/O 操作，将字节流转换为 HgptImage 对象，反之亦然。

class HgptReader:
    """
    从文件流中读取数据并构建一个 HgptImage 对象。
    这是一个建造者（Builder），它按照 HGPT 格式的规则逐步组装出最终产品。
    """
    def __init__(self, file_source):
        """
        Args:
            file_source: 可以是文件路径 (str) 或文件流对象 (file-like object)
        """
        self.file_source = file_source
        self._should_close = isinstance(file_source, str)

    def read(self) -> HgptImage:
        """执行读取和构建操作。"""
        if self._should_close:
            # 如果是文件路径，打开文件
            with open(self.file_source, 'rb') as f:
                return self._read_from_stream(f)
        else:
            # 如果是文件流，直接使用
            return self._read_from_stream(self.file_source)
    
    def _read_from_stream(self, f) -> HgptImage:
        """从文件流读取并构建 HgptImage。"""
        header, division_info = self._read_header_and_divisions(f)
        
        if f.tell() != header.pp_offset:
            raise Exception(f'Current position {f.tell()} does not match PP offset {header.pp_offset}')
        
        pp_header = common.read_uint32(f)
        if pp_header & 0xFFFF != 0x7070:
            raise Exception('Missing or invalid PP header!')
        pp_format = (pp_header >> 16) & 0xFFFF
        
        display_info = DisplayInfo(width=common.read_uint16(f), height=common.read_uint16(f))
        f.seek(8, os.SEEK_CUR)  # Skip padding

        processor = get_tile_processor(pp_format, display_info)
        self._read_and_verify_ppd(f, processor)
        
        storage_width, storage_height = processor.get_storage_dims()
        num_pixels = storage_width * storage_height
        
        tiled_data = processor.decode(f, num_pixels)
        content = processor.untile(tiled_data, storage_width, storage_height)
        
        palette = self._read_palette(f, pp_format)

        return HgptImage(header, display_info, content, palette, division_info)

    def _read_header_and_divisions(self, f) -> Tuple[HgptHeader, Optional[DivisionInfo]]:
        """读取文件头和（可选的）扩展头/分区信息。"""
        header = HgptHeader()
        header.magic_number = f.read(4).decode('ascii', 'ignore')
        if header.magic_number != 'HGPT':
            raise Exception('Not an HGPT file!')
            
        header.pp_offset = common.read_uint16(f)
        header.has_extended_header = (common.read_uint16(f) == 1)
        header.number_of_divisions = common.read_uint16(f)
        header.unknown_one = common.read_uint16(f)
        header.unknown_two = common.read_uint32(f)
        
        division_info = None
        if header.has_extended_header:
            num_divisions_repeat = common.read_uint16(f)
            if header.number_of_divisions != num_divisions_repeat:
                raise Exception("Number of divisions mismatch!")
            
            header.unknown_three = common.read_uint16(f)
            name = f.read(8).decode('utf-8').strip('\x00')
            divisions = [(common.read_uint16(f), common.read_uint16(f), 
                          common.read_uint16(f), common.read_uint16(f))
                         for _ in range(header.number_of_divisions)]
            division_info = DivisionInfo(name, divisions)
            
            divisions_size = 12 + 8 * header.number_of_divisions
            divisions_padded_size = common.align_size(divisions_size, 16)
            f.seek(divisions_padded_size - divisions_size, os.SEEK_CUR)
            
        return header, division_info

    def _read_and_verify_ppd(self, f, processor: TileProcessor):
        """读取并验证 PPD 段的信息。"""
        ppd_header = common.read_uint32(f)
        if ppd_header & 0x00FFFFFF != 0x00647070:
            raise Exception('Missing ppd header!')
        
        ppd_format = (ppd_header >> 24) & 0xFF
        if ppd_format != (processor.pp_format & 0xFF):
            raise Exception('PPD format does not match PP format')
        
        # 此处可以加入更多来自原始代码的严格验证
        f.seek(4, os.SEEK_CUR) # skip ppd_display_width/height
        f.seek(4, os.SEEK_CUR) # skip padding
        f.seek(4, os.SEEK_CUR) # skip ppd_sixteenths_width/height
        f.seek(4, os.SEEK_CUR) # skip ppd_size
        f.seek(12, os.SEEK_CUR) # skip padding
        
    def _read_palette(self, f, pp_format: int) -> Optional[Palette]:
        """读取 PPC 段（调色板）。"""
        if pp_format == 0x8800:
            return None
            
        ppc_header = common.read_uint32(f)
        if ppc_header != 0x00637070:
            raise Exception('Missing ppc header!')
            
        f.seek(2, os.SEEK_CUR)
        palette_total = common.read_uint16(f) * 8
        f.seek(8, os.SEEK_CUR)
        
        def decode_alpha(encoded_alpha):
            return min(encoded_alpha << 1, 0xFF)
            
        colors = [(common.read_uint8(f), common.read_uint8(f), common.read_uint8(f), decode_alpha(common.read_uint8(f)))
                  for _ in range(palette_total)]
        return Palette(colors)

class HgptWriter:
    """将一个 HgptImage 对象写入到文件。"""
    def __init__(self, hgpt_image: HgptImage):
        self.image = hgpt_image

    def write(self, file_target):
        """
        执行写入操作。
        
        Args:
            file_target: 可以是文件路径 (str) 或文件流对象 (file-like object)
        """
        if isinstance(file_target, str):
            # 如果是文件路径，打开文件
            with open(file_target, 'wb') as f:
                self._write_to_stream(f)
        else:
            # 如果是文件流，直接使用
            self._write_to_stream(file_target)
    
    def _write_to_stream(self, f):
        """将 HGPT 数据写入文件流。"""
        palette_len = len(self.image.palette.colors) if self.image.palette else 0
        if palette_len == 0:
            pp_format = 0x8800
        elif palette_len <= 16:
            pp_format = 0x14
        elif palette_len <= 256:
            pp_format = 0x13
        else:
            raise ValueError(f"Invalid palette size: {palette_len}")
        
        processor = get_tile_processor(pp_format, self.image.display_info)
        
        self._write_header_and_divisions(f)
        self._write_pp_ppd(f, processor)
        
        storage_width, storage_height = processor.get_storage_dims()
        tiled_data = processor.tile(self.image.content, storage_width, storage_height)
        processor.encode(f, tiled_data)
        
        self._write_palette(f, processor)

    def _write_header_and_divisions(self, f):
        """写入文件头和（可选的）扩展头/分区信息。"""
        f.write(self.image.header.magic_number.encode('ascii'))
        
        divisions_padded_size = 0
        if self.image.header.has_extended_header and self.image.division_info:
            div_info = self.image.division_info
            divisions_size = 12 + len(div_info.divisions) * 8
            divisions_padded_size = common.align_size(divisions_size, 16)
        pp_offset = 16 + divisions_padded_size
        
        common.write_uint16(f, pp_offset)
        common.write_uint16(f, 1 if self.image.header.has_extended_header else 0)
        num_divisions = len(self.image.division_info.divisions) if self.image.division_info else 0
        common.write_uint16(f, num_divisions)
        common.write_uint16(f, self.image.header.unknown_one)
        unknown_two = 0xFFFFFFFF if self.image.header.has_extended_header else 0x00000000
        common.write_uint32(f, unknown_two)
        
        if self.image.header.has_extended_header and self.image.division_info:
            div_info = self.image.division_info
            common.write_uint16(f, len(div_info.divisions))
            common.write_uint16(f, self.image.header.unknown_three)
            f.write((div_info.name.encode('utf-8') + b'\0' * 8)[:8])
            for div in div_info.divisions:
                common.write_uint16(f, div[0]) # x
                common.write_uint16(f, div[1]) # y
                common.write_uint16(f, div[2]) # width
                common.write_uint16(f, div[3]) # height
            
            padding_size = divisions_padded_size - (12 + len(div_info.divisions) * 8)
            f.write(b'\0' * padding_size)

    def _write_pp_ppd(self, f, processor: TileProcessor):
        """写入 PP 和 PPD 段。"""
        pp_header = 0x7070 | (processor.pp_format << 16)
        ppd_header = 0x647070 | ((processor.pp_format & 0xFF) << 24)
        
        common.write_uint32(f, pp_header)
        common.write_uint16(f, self.image.display_info.width)
        common.write_uint16(f, self.image.display_info.height)
        f.write(b'\0' * 8)
        
        common.write_uint32(f, ppd_header)
        common.write_uint16(f, self.image.display_info.width)
        common.write_uint16(f, self.image.display_info.height)
        f.write(b'\0' * 4)
        
        sixteenths_w = common.align_size(self.image.display_info.width, 16)
        sixteenths_h = common.align_size(self.image.display_info.height, 8)
        common.write_uint16(f, sixteenths_w)
        common.write_uint16(f, sixteenths_h)
        
        storage_w, storage_h = processor.get_storage_dims()
        num_pixels = storage_w * storage_h
        ppd_size = int(num_pixels * processor.bytes_per_pixel_ppd_size) + 0x20
        common.write_uint32(f, ppd_size)
        f.write(b'\0' * 12)
        
    def _write_palette(self, f, processor: TileProcessor):
        """写入 PPC 段（调色板）。"""
        if processor.pp_format == 0x8800 or not self.image.palette:
            return
            
        common.write_uint32(f, 0x00637070)
        f.write(b'\0' * 2)
        common.write_uint16(f, len(self.image.palette) // 8)
        f.write(b'\0' * 8)
        
        def encode_alpha(alpha):
            alpha >>= 1
            return 0x80 if alpha == 0x7F else alpha
            
        for r, g, b, a in self.image.palette.colors:
            common.write_uint8(f, r)
            common.write_uint8(f, g)
            common.write_uint8(f, b)
            common.write_uint8(f, encode_alpha(a))

# endregion

# region: --- 4. 导出与导入功能 ---
# 这些是高级别的用户接口函数，用于在 HGPT 和 PNG/JSON 之间进行转换。

def export_hgpt(file_path: str):
    """将 HGPT 文件导出为 .png 和 .json 文件。"""
    print(f'# Exporting {file_path}:')
    hgpt_image = HgptReader(file_path).read()
    
    output_path_metadata = file_path + '.PICTURE.json'
    output_path_picture = file_path + '.PICTURE.png'
    output_path_helper = file_path + '.PICTURE.HELPER.png'

    metadata_dict = {
        "has_extended_header": hgpt_image.header.has_extended_header,
        "unknown_two": hgpt_image.header.unknown_two,
        "unknown_three": hgpt_image.header.unknown_three,
        "width": hgpt_image.display_info.width,
        "height": hgpt_image.display_info.height,
    }
    
    if hgpt_image.division_info:
        metadata_dict["division_name"] = hgpt_image.division_info.name
        metadata_dict["divisions"] = hgpt_image.division_info.divisions
        
    if hgpt_image.palette:
        metadata_dict["palette_total"] = len(hgpt_image.palette)

    with open(output_path_metadata, 'w', encoding='utf-8') as f:
        json.dump(metadata_dict, f, indent=4, ensure_ascii=False)
        
    with open(output_path_picture, 'wb') as f:
        if hgpt_image.palette:
            f.write(
                write_indexed_png(
                    hgpt_image.display_info.width,
                    hgpt_image.display_info.height,
                    hgpt_image.content,
                    hgpt_image.palette.colors,
                )
            )
        else: # RGBA
            f.write(
                write_rgba_png(
                    hgpt_image.display_info.width,
                    hgpt_image.display_info.height,
                    hgpt_image.content,
                )
            )

    print(f'  -> Created {output_path_picture}')
    print(f'  -> Created {output_path_metadata}')

    # Create divisions helper file
    if hgpt_image.division_info and hgpt_image.division_info.divisions:
        width, height = hgpt_image.display_info.width, hgpt_image.display_info.height
        canvas = [common.unique_color(-1, None)] * (width * height)
        
        for i, (dx, dy, dw, dh) in enumerate(hgpt_image.division_info.divisions):
            draw_color = common.unique_color(i, len(hgpt_image.division_info.divisions))
            # Draw rectangle logic
            for y in range(dy, dy + dh):
                for x in range(dx, dx + dw):
                    if (x == dx or x == dx + dw - 1 or y == dy or y == dy + dh - 1) and (0 <= x < width and 0 <= y < height):
                        canvas[y * width + x] = draw_color
        
        with open(output_path_helper, 'wb') as f:
            f.write(write_rgb_png(width, height, canvas))
        print(f'  -> Created {output_path_helper}')


def import_hgpt(base_path: str):
    """从 .png 和 .json 文件导入并创建 HGPT 文件。"""
    print(f'# Importing from {base_path}:')
    
    input_path_metadata = base_path + '.PICTURE.json'
    input_path_picture = base_path + '.PICTURE.png'
    
    if not os.path.exists(input_path_picture):
        raise FileNotFoundError(f"Picture file not found: {input_path_picture}")

    metadata_dict = {}
    if os.path.exists(input_path_metadata):
        with open(input_path_metadata, 'r', encoding='utf-8') as f:
            metadata_dict = json.load(f)

    header = HgptHeader()
    header.has_extended_header = metadata_dict.get('has_extended_header', False)
    header.unknown_two = metadata_dict.get('unknown_two', 0)
    header.unknown_three = metadata_dict.get('unknown_three', 0x0013)
    
    decoded = read_png(input_path_picture)
    width, height = decoded.width, decoded.height
    
    display_info = DisplayInfo(width=width, height=height)
    
    division_info = None
    if header.has_extended_header or 'divisions' in metadata_dict:
        header.has_extended_header = True
        division_info = DivisionInfo(
            name=metadata_dict.get('division_name', ''),
            divisions=metadata_dict.get('divisions', [])
        )
    
    palette = None
    content = []
    
    if decoded.palette is not None:
        colors = list(decoded.palette)

        # Extend palette to fit standard sizes
        if 0 < len(colors) < 16:
            colors.extend([(0,0,0,255)] * (16 - len(colors)))
        elif 16 < len(colors) < 256:
            colors.extend([(0,0,0,255)] * (256 - len(colors)))
        
        palette = Palette(colors)
        content = list(decoded.pixels)
    else: # RGBA
        content = decoded.rgba_pixels()
    
    hgpt_image = HgptImage(header, display_info, content, palette, division_info)
    HgptWriter(hgpt_image).write(base_path)
    
    print(f'  -> Created {base_path}')

# endregion

# region: --- 5. 主程序入口 ---

if __name__ == '__main__':
    import sys
    import traceback
    
    if len(sys.argv) < 3:
        print('Usage: hgpt_refactored.py <action> <path>')
        print('Actions:')
        print('  -e, --export <picture.hpt>             # Exports to .hpt.PICTURE.png/.json')
        print('  -i, --import <picture.hpt.PICTURE.png> # Imports from .png and .json to .hpt')
        sys.exit(0)

    action = sys.argv[1]
    input_path = os.path.normpath(sys.argv[2])

    try:
        if action in ('-e', '--export'):
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Input file not found: {input_path}")
            export_hgpt(input_path)

        elif action in ('-i', '--import'):
            base_path = input_path
            suffixes = ['.PICTURE.json', '.PICTURE.png']
            for suffix in suffixes:
                if base_path.lower().endswith(suffix.lower()):
                    base_path = base_path[:-len(suffix)]
                    break
            else:
                 raise ValueError(f"For import, the input path must end with one of {suffixes}")
            import_hgpt(base_path)
        else:
            raise ValueError(f'Unknown action: {action}')
            
    except Exception as e:
        print('\n--- ERROR ---')
        print(f'{type(e).__name__}: {e}')
        traceback.print_exc()
        sys.exit(-1)

    print('\nOperation completed successfully.')
    sys.exit(0)
# endregion
