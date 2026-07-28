"""
Persist HGPT Image
参考 EVSDao 的设计模式实现 HGPT 的去重存储和重建
"""

import hashlib
import io
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
import logging
from tqdm import tqdm

from ..db import get_db
from app.parser.tools import hgp
from app.parser.tools.pillow_png import (
    convert_indexed_to_rgba_png,
    quantize_png,
    quantize_png_fallback,
    read_png,
    write_indexed_png,
    write_rgba_png,
)

from ..entity.hgpt import Hgpt

logger = logging.getLogger(__name__)


class HgptDao:
    @staticmethod
    def save(hgpt_data: bytes, db=None, existing_keys: set = None) -> str:
        """
        保存 HGPT 数据到数据库（去重）
        
        Args:
            hgpt_data: 原始解压后的 HGPT 二进制数据
            db: 可选的数据库会话，用于批量操作（避免重复创建会话）
            existing_keys: 可选的内存中已存在的 key 集合，用于加速去重判断
            
        Returns:
            str: HGPT 的 hash key
        """
        # 1. 计算 hash（用于去重）
        hash_object = hashlib.md5(hgpt_data)
        hashed_key = hash_object.hexdigest()
        
        # 优先使用内存中的已存 key 集合进行判断（解决 N+1 问题）
        if existing_keys is not None:
            if hashed_key in existing_keys:
                return hashed_key
        
        # 如果没有提供 db 会话，创建新的
        if db is None:
            with next(get_db()) as db:
                res = HgptDao._save_with_session(hgpt_data, hashed_key, db, skip_query=(existing_keys is not None))
        else:
            res = HgptDao._save_with_session(hgpt_data, hashed_key, db, skip_query=(existing_keys is not None))

        # 如果保存成功且提供了集合，更新集合
        if existing_keys is not None:
            existing_keys.add(hashed_key)
            
        return res
    
    @staticmethod
    def save_batch(hgpt_data_list: list[bytes], db, existing_keys: set = None) -> dict:
        """
        批量保存 HGPT 数据到数据库（去重）
        使用 bulk_insert_mappings 进行高性能批量插入，绕过 ORM 开销
        
        Args:
            hgpt_data_list: HGPT 二进制数据列表
            db: 数据库会话
            existing_keys: 可选的内存中已存在的 key 集合，用于加速去重判断
            
        Returns:
            dict: {hashed_key: hashed_key} 映射，用于后续关联
        """
        if not hgpt_data_list:
            return {}
        
        # 1. 计算所有 hash
        hgpt_dict = {}  # {hashed_key: hgpt_data}
        for hgpt_data in hgpt_data_list:
            hash_object = hashlib.md5(hgpt_data)
            hashed_key = hash_object.hexdigest()
            
            # 去重检查
            if existing_keys is not None:
                if hashed_key in existing_keys:
                    continue
            
            # 避免重复处理相同 key
            if hashed_key not in hgpt_dict:
                hgpt_dict[hashed_key] = hgpt_data
        
        if not hgpt_dict:
            return {}
        
        # 2. 批量检查数据库中已存在的 key
        keys_to_check = list(hgpt_dict.keys())
        existing_in_db = set(r[0] for r in db.query(Hgpt.key).filter(Hgpt.key.in_(keys_to_check)).all())
        
        # 3. 过滤出需要插入的数据
        to_insert = {}
        for hashed_key, hgpt_data in hgpt_dict.items():
            if hashed_key not in existing_in_db:
                to_insert[hashed_key] = hgpt_data
        
        if not to_insert:
            # 更新 existing_keys
            if existing_keys is not None:
                existing_keys.update(keys_to_check)
            return {k: k for k in keys_to_check}
        
        # 4. 批量解析和准备数据
        mappings = []
        for hashed_key, hgpt_data in tqdm(to_insert.items(), desc="Preparing HGPT data", unit="hgpt"):
            try:
                # 解析 HGPT 文件
                file_stream = io.BytesIO(hgpt_data)
                reader = hgp.HgptReader(file_stream)
                hgpt_image = reader.read()
                
                # 导出为 PNG
                png_data = HgptDao._export_to_png(hgpt_image)
                
                # 提取格式信息
                pp_format = HgptDao._get_pp_format(hgpt_image)
                palette_size = len(hgpt_image.palette) if (hgpt_image.palette and hasattr(hgpt_image.palette, '__len__')) else None
                
                # 准备字典映射
                mapping = {
                    'key': hashed_key,
                    'content': hgpt_data,
                    'png_image': png_data,
                    'has_extended_header': hgpt_image.header.has_extended_header,
                    'unknown_two': hgpt_image.header.unknown_two,
                    'unknown_three': hgpt_image.header.unknown_three,
                    'width': hgpt_image.display_info.width,
                    'height': hgpt_image.display_info.height,
                    'pp_format': pp_format,
                    'palette_size': palette_size,
                    'division_name': hgpt_image.division_info.name if hgpt_image.division_info else None,
                    'divisions': hgpt_image.division_info.divisions if hgpt_image.division_info else None,
                }
                mappings.append(mapping)
                
            except Exception as e:
                logger.warning("  [HGPT] Parse error for %s: %s", hashed_key[:8], e)
                # 如果解析失败，仍然保存原始数据
                mapping = {
                    'key': hashed_key,
                    'content': hgpt_data,
                    'png_image': None,
                    'has_extended_header': False,
                    'unknown_two': 0,
                    'unknown_three': 0x0013,
                    'width': 0,
                    'height': 0,
                    'pp_format': None,
                    'palette_size': None,
                    'division_name': None,
                    'divisions': None,
                }
                mappings.append(mapping)
        
        # 5. 使用 bulk_insert_mappings 批量插入（绕过 ORM 开销）
        if mappings:
            db.bulk_insert_mappings(Hgpt, mappings)
            logger.debug("  [HGPT] Bulk inserted %d records", len(mappings))
        
        # 6. 更新 existing_keys
        if existing_keys is not None:
            existing_keys.update(keys_to_check)
        
        # 7. 返回所有 key 的映射
        return {k: k for k in keys_to_check}
    
    @staticmethod
    def _save_with_session(hgpt_data: bytes, hashed_key: str, db, skip_query: bool = False) -> str:
        """
        使用给定的数据库会话保存 HGPT 数据（内部方法）
        """
        # 2. 检查是否已存在（如果外部已验证，则跳过）
        if not skip_query:
            existing = db.query(Hgpt).filter(Hgpt.key == hashed_key).first()
            if existing:
                logger.debug("  [HGPT] Duplicate found: %s... (skipping)", hashed_key[:8])
                return hashed_key
        
        # 3. 解析 HGPT 文件（使用 BytesIO，无需临时文件）
        try:
            # 使用 BytesIO 将字节数据转换为文件流
            file_stream = io.BytesIO(hgpt_data)
            reader = hgp.HgptReader(file_stream)
            hgpt_image = reader.read()
            
            # 4. 导出为 PNG（用于预览和翻译）
            png_data = HgptDao._export_to_png(hgpt_image)
            
            # 5. 提取格式信息
            pp_format = HgptDao._get_pp_format(hgpt_image)
            palette_size = len(hgpt_image.palette) if (hgpt_image.palette and hasattr(hgpt_image.palette, '__len__')) else None
            
            # 6. 创建数据库记录
            hgpt_record = Hgpt(
                key=hashed_key,
                content=hgpt_data,
                png_image=png_data,
                has_extended_header=hgpt_image.header.has_extended_header,
                unknown_two=hgpt_image.header.unknown_two,
                unknown_three=hgpt_image.header.unknown_three,
                width=hgpt_image.display_info.width,
                height=hgpt_image.display_info.height,
                pp_format=pp_format,
                palette_size=palette_size,
                division_name=hgpt_image.division_info.name if hgpt_image.division_info else None,
                divisions=hgpt_image.division_info.divisions if hgpt_image.division_info else None,
            )
            
            db.add(hgpt_record)
            # 不在这里提交，让调用者统一提交
            # db.commit()
            
            logger.debug("  [HGPT] Saved: %s... (%dx%d)", hashed_key[:8], hgpt_image.display_info.width, hgpt_image.display_info.height)
            return hashed_key
            
        except Exception as e:
            logger.warning("  [HGPT] Parse error: %s", e)
            # 如果解析失败，仍然保存原始数据
            hgpt_record = Hgpt(
                key=hashed_key,
                content=hgpt_data,
                png_image=None,
                has_extended_header=False,
                unknown_two=0,
                unknown_three=0x0013,
                width=0,
                height=0,
                pp_format=None,
                palette_size=None,
            )
            db.add(hgpt_record)
            # 不在这里提交，让调用者统一提交
            # db.commit()
            return hashed_key
    
    @staticmethod
    def get_hgpt_data(hgpt_key: str) -> bytes:
        """
        重建 HGPT 数据（从数据库中的结构化数据重新生成）
        优先使用翻译后的 PNG，如果没有则使用原始 PNG
        
        Args:
            hgpt_key: HGPT 的 hash key
            
        Returns:
            bytes: 重新生成的 HGPT 二进制数据
        """
        with next(get_db()) as db:
            hgpt = db.query(Hgpt).filter(Hgpt.key == hgpt_key).first()
            if not hgpt:
                raise ValueError(f"HGPT not found: {hgpt_key}")
            
            # 使用翻译后的 PNG，未翻译直接使用原数据
            if hgpt.png_translated:
                return HgptDao._rebuild_from_png(hgpt)
            else:
                # 回退：如果没有 PNG，使用原始数据
                return hgpt.content
    
    @staticmethod
    def get_png_image(hgpt_key: str) -> bytes:
        """
        获取 PNG 图像数据（用于预览）
        
        Args:
            hgpt_key: HGPT 的 hash key
            
        Returns:
            bytes: PNG 图像数据
        """
        with next(get_db()) as db:
            hgpt = db.query(Hgpt).filter(Hgpt.key == hgpt_key).first()
            if not hgpt:
                raise ValueError(f"HGPT not found: {hgpt_key}")
            return hgpt.png_image
    
    @staticmethod
    def _export_to_png(hgpt_image: hgp.HgptImage) -> bytes:
        """
        将 HgptImage 对象导出为 PNG 字节数据
        
        Args:
            hgpt_image: 解析后的 HGPT 图像对象
            
        Returns:
            bytes: PNG 图像数据
        """
        if hgpt_image.palette:
            return write_indexed_png(
                hgpt_image.display_info.width,
                hgpt_image.display_info.height,
                hgpt_image.content,
                hgpt_image.palette.colors,
            )
        return write_rgba_png(
            hgpt_image.display_info.width,
            hgpt_image.display_info.height,
            hgpt_image.content,
        )
    
    @staticmethod
    def _get_pp_format(hgpt_image: hgp.HgptImage) -> int:
        """
        推断 PP format（从 palette 或内容推断）
        
        Args:
            hgpt_image: 解析后的 HGPT 图像对象
            
        Returns:
            int: PP format 值
        """
        if hgpt_image.palette:
            palette_len = len(hgpt_image.palette)
            if palette_len <= 16:
                return 0x14  # 4-bit paletted
            else:
                return 0x13  # 8-bit paletted
        else:
            return 0x8800  # 32-bit RGBA
    
    @staticmethod
    def _rebuild_from_png(hgpt: Hgpt) -> bytes:
        """
        从数据库中的 PNG 和元数据重建 HGPT 文件
        优先使用翻译后的 PNG，如果没有则使用原始 PNG
        
        Args:
            hgpt: Hgpt 数据库记录
            
        Returns:
            bytes: 重新生成的 HGPT 二进制数据
        """
        # 1. 读取 PNG 图像（优先使用翻译版本）
        png_data = hgpt.png_translated if hgpt.png_translated else hgpt.png_image
        decoded = read_png(png_data)
        
        # 2. 重建 HgptHeader
        header = hgp.HgptHeader()
        header.has_extended_header = hgpt.has_extended_header
        header.unknown_two = hgpt.unknown_two
        header.unknown_three = hgpt.unknown_three
        
        # 3. 重建 DisplayInfo
        display_info = hgp.DisplayInfo(width=hgpt.width, height=hgpt.height)
        
        # 4. 重建 DivisionInfo（如果有）
        division_info = None
        if hgpt.division_name or hgpt.divisions:
            division_info = hgp.DivisionInfo(
                name=hgpt.division_name or '',
                divisions=hgpt.divisions or []
            )
        
        # 5. 重建图像内容和调色板
        palette = None
        content = []
        
        if decoded.palette is not None:
            # 调色板模式
            colors = list(decoded.palette)
            
            # 扩展调色板到标准大小
            if 0 < len(colors) < 16:
                colors.extend([(0, 0, 0, 255)] * (16 - len(colors)))
            elif 16 < len(colors) < 256:
                colors.extend([(0, 0, 0, 255)] * (256 - len(colors)))
            
            palette = hgp.Palette(colors)
            content = list(decoded.pixels)
        else:
            content = decoded.rgba_pixels()
        
        # 6. 构建 HgptImage 对象
        hgpt_image = hgp.HgptImage(
            header=header,
            display_info=display_info,
            content=content,
            palette=palette,
            division_info=division_info
        )
        
        # 7. 写入到内存流（使用 BytesIO，无需临时文件）
        output = io.BytesIO()
        writer = hgp.HgptWriter(hgpt_image)
        writer.write(output)
        return output.getvalue()
    
    @staticmethod
    def import_translated_png(hgpt_key: str, translated_png_data: bytes):
        """
        导入翻译后的 PNG 图像（存储到 png_translated 字段）
        
        Args:
            hgpt_key: HGPT 的 hash key
            translated_png_data: 翻译后的 PNG 图像数据
        """
        with next(get_db()) as db:
            hgpt = db.query(Hgpt).filter(Hgpt.key == hgpt_key).first()
            if not hgpt:
                raise ValueError(f"HGPT not found: {hgpt_key}")
            
            # 验证 PNG 尺寸（必须与原始图像一致）
            decoded = read_png(translated_png_data)
            width, height = decoded.width, decoded.height
            if width != hgpt.width or height != hgpt.height:
                raise ValueError(
                    f"Size mismatch: expected {hgpt.width}x{hgpt.height}, "
                    f"got {width}x{height}"
                )
            
            # 存储翻译版本
            hgpt.png_translated = translated_png_data
            db.commit()
            print(f"  [HGPT] Imported translation for {hgpt_key[:8]}... ({width}x{height})")
    
    @staticmethod
    def export_all_images(output_dir: str) -> Dict[str, List[Tuple[str, str]]]:
        """
        导出所有 HGPT 图像到指定目录
        按照 HAR 文件组织，文件名包含短名称和 hash
        只创建包含图像的目录
        
        Args:
            output_dir: 输出目录路径
            
        Returns:
            Dict[har_name, List[(filename, hgpt_key)]]: 导出的文件映射
        """
        from ..entity.hgar import Hgar
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        exported_images = {}
        seen_keys = set()  # 用于去重
        har_images_temp = {}  # 临时存储每个 HAR 的图像
        
        with next(get_db()) as db:
            # 遍历所有 HGAR 文件
            hgar_list = db.query(Hgar).all()
            
            for hgar in tqdm(hgar_list, desc="Exporting HGARs", unit="hgar"):
                har_name = hgar.name.replace('.har', '')
                har_images_temp[har_name] = []
                
                # 遍历该 HAR 中的所有文件
                for hgar_file in hgar.files:
                    if not hgar_file.hgpt_key:
                        continue
                    
                    # 去重：同一图像只导出一次
                    if hgar_file.hgpt_key in seen_keys:
                        continue
                    seen_keys.add(hgar_file.hgpt_key)
                    
                    # 获取 HGPT 记录
                    hgpt = db.query(Hgpt).filter(Hgpt.key == hgar_file.hgpt_key).first()
                    if not hgpt or not hgpt.png_image:
                        continue
                    
                    # 生成文件名：短名称_hash[:8].png
                    short_name = hgar_file.short_name or f"id{hgar_file.identifier}"
                    short_name = short_name.replace('.hpt', '').replace('.zpt', '')
                    filename = f"{short_name}_{hgpt.key[:8]}.png"
                    
                    har_images_temp[har_name].append((filename, hgpt.png_image))
                
                # 只有当该 HAR 有图像时，才创建目录并导出
                if har_images_temp[har_name]:
                    har_dir = output_path / har_name
                    har_dir.mkdir(exist_ok=True)
                    
                    exported_images[har_name] = []
                    for filename, png_data in har_images_temp[har_name]:
                        # 导出原始 PNG（用于翻译）
                        file_path = har_dir / filename
                        with open(file_path, 'wb') as f:
                            f.write(png_data)
                        
                        # 从文件名提取 hash
                        hash_part = filename.split('_')[-1].replace('.png', '')
                        exported_images[har_name].append((filename, hash_part))
                    
                    logger.debug("  [Export] %s: %d images", har_name, len(exported_images[har_name]))
            
            # 删除空文件夹
            for item in output_path.iterdir():
                if item.is_dir() and not list(item.iterdir()):
                    shutil.rmtree(item)
                    logger.debug("  [Export] Removed empty directory: %s", item.name)
        
        total_images = sum(len(imgs) for imgs in exported_images.values())
        logger.debug("\n  [Export] Total: %d unique images exported to %s", total_images, output_dir)
        return exported_images
    
    @staticmethod
    def import_translated_images(translation_dir: str) -> int:
        """
        从指定目录批量导入翻译后的图像
        根据文件名中的 hash 匹配图像
        自动转换图像格式以匹配原始HGPT格式（调色板/RGBA）
        
        Args:
            translation_dir: 包含翻译图像的目录
            
        Returns:
            int: 成功导入的图像数量
        """
        translation_path = Path(translation_dir)
        if not translation_path.exists():
            raise ValueError(f"Translation directory not found: {translation_dir}")
        
        imported_count = 0
        
        # 递归查找所有 PNG 文件
        png_files = list(translation_path.rglob("*.png"))
        
        logger.debug("  [Import] Found %d PNG files in %s", len(png_files), translation_dir)
        
        with next(get_db()) as db:
            for png_file in tqdm(png_files, desc="Importing translated images", unit="image"):
                # 从文件名提取 hash（格式：xxx_HASH8.png）
                filename = png_file.stem  # 去掉 .png
                parts = filename.split('_')
                
                if len(parts) < 2:
                    logger.debug("  [Import] Skip (no hash): %s", png_file.name)
                    continue
                
                hash_short = parts[-1]  # 最后一部分是 hash
                
                # 在数据库中查找匹配的 HGPT（hash 前缀匹配）
                hgpt_list = db.query(Hgpt).filter(Hgpt.key.like(f"{hash_short}%")).all()
                
                if not hgpt_list:
                    logger.debug("  [Import] Skip (not found): %s (hash: %s)", png_file.name, hash_short)
                    continue
                
                if len(hgpt_list) > 1:
                    logger.warning("  [Import] Warning: Multiple matches for %s, using first", hash_short)
                
                hgpt = hgpt_list[0]
                
                # 读取翻译后的 PNG
                with open(png_file, 'rb') as f:
                    translated_png_raw = f.read()
                
                try:
                    # 验证尺寸并转换格式
                    decoded = read_png(translated_png_raw)
                    width, height = decoded.width, decoded.height
                    
                    if width != hgpt.width or height != hgpt.height:
                        logger.warning("  [Import] Skip (size mismatch): %s (expected %dx%d, got %dx%d)", png_file.name, hgpt.width, hgpt.height, width, height)
                        continue
                    
                    # 根据原始格式转换PNG
                    needs_palette = hgpt.palette_size is not None  # 原始是调色板格式
                    is_currently_palette = decoded.is_indexed
                    
                    if needs_palette and not is_currently_palette:
                        # 需要调色板但当前是RGBA，转换为调色板
                        logger.debug("  [Import] Converting RGBA to palette: %s", png_file.name)
                        translated_png = HgptDao._convert_rgba_to_palette(
                            translated_png_raw, hgpt.palette_size
                        )
                    elif not needs_palette and is_currently_palette:
                        # 需要RGBA但当前是调色板，转换为RGBA
                        logger.debug("  [Import] Converting palette to RGBA: %s", png_file.name)
                        translated_png = HgptDao._convert_palette_to_rgba(translated_png_raw)
                    else:
                        # 格式匹配，直接使用
                        translated_png = translated_png_raw
                    
                    # 导入转换后的翻译版本
                    hgpt.png_translated = translated_png
                    imported_count += 1
                    logger.debug("  [Import] ✓ %s -> %s...", png_file.name, hgpt.key[:8])
                    
                except Exception as e:
                    logger.exception("  [Import] Error: %s - %s", png_file.name, e)
                    continue
            
            db.commit()
        
        logger.debug("\n  [Import] Successfully imported %d translated images", imported_count)
        return imported_count
    
    @staticmethod
    def _convert_rgba_to_palette(png_data: bytes, target_palette_size: int) -> bytes:
        """
        将RGBA格式的PNG转换为调色板格式
        使用 pngquant 命令行工具进行高质量量化，完美保留透明度
        如果 pngquant 不可用，使用备用方法
        
        Args:
            png_data: RGBA格式的PNG数据
            target_palette_size: 目标调色板大小（16或256）
            
        Returns:
            bytes: 调色板格式的PNG数据
        """
        return quantize_png(png_data, target_palette_size)
    
    @staticmethod
    def _convert_rgba_to_palette_fallback(png_data: bytes, target_palette_size: int) -> bytes:
        """
        备用的简单颜色量化（当 Pillow 不可用时）
        """
        return quantize_png_fallback(png_data, target_palette_size)
    
    @staticmethod
    def _convert_palette_to_rgba(png_data: bytes) -> bytes:
        """
        将调色板格式的PNG转换为RGBA格式
        
        Args:
            png_data: 调色板格式的PNG数据
            
        Returns:
            bytes: RGBA格式的PNG数据
        """
        return convert_indexed_to_rgba_png(png_data)
