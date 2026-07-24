"""
Persist EVSWrapper
"""

import hashlib
import json
import logging
import os
from typing import Optional
from tqdm import tqdm

from ..db import get_db
from app.parser import tools
from app.utils.evs import get_avatar_and_exp

from ..entity.evs_entry import EVSEntry
from ..entity.hgar import Hgar
from ..entity.hgar_file import HgarFile
from ..entity.sentence import Sentence
from ..entity.translation import Translation

logger = logging.getLogger(__name__)

HAS_CONTENT_SECTION = (0x01, 0x8C, 0x8D, 0xA3, 0x8E, 0x95)


def _is_cev_translatable_original(text: str) -> bool:
    return bool(text and text.strip() and not text.isascii())


class EVSDao:
    def save(hgar_file_id: int, evs_file: tools.EvsWrapper, db=None):
        """
        保存 EVS 条目到数据库
        
        Args:
            hgar_file_id: HGAR 文件 ID
            evs_file: EVS 包装器对象
            db: 可选的数据库会话，用于批量操作（避免重复创建会话）
        """
        # 如果没有提供 db 会话，创建新的
        if db is None:
            with next(get_db()) as db:
                EVSDao._save_with_session(hgar_file_id, evs_file, db)
        else:
            EVSDao._save_with_session(hgar_file_id, evs_file, db)
    
    @staticmethod
    def _save_with_session(hgar_file_id: int, evs_file: tools.EvsWrapper, db):
        """
        使用给定的数据库会话保存 EVS 数据（内部方法）
        优化：使用 bulk_insert_mappings 绕过 ORM 开销
        优化：批量查询已存在的 Sentence key，避免循环中的 N 次查询
        """
        # 第一步：收集所有潜在的 sentence key（空间换时间）
        all_hashed_keys = set()
        entry_data = []  # 保存所有 entry 数据，用于后续处理
        
        for type, params, content in evs_file.entries:
            if content is None or len(content) == 0:
                entry_data.append((type, params, None, None))  # (type, params, content, hashed_str)
                continue
            
            # Hash the content
            hash_object = hashlib.md5(content.encode())
            hashed_str = hash_object.hexdigest()
            all_hashed_keys.add(hashed_str)
            entry_data.append((type, params, content, hashed_str))
        
        # 第二步：一次性批量查询已存在的 Sentence key（将 N 次查询合并为 1 次）
        existing_keys = set()
        if all_hashed_keys:
            # 使用 IN 子句一次性查询所有已存在的 key
            existing_sentences = db.query(Sentence.key).filter(
                Sentence.key.in_(all_hashed_keys)
            ).all()
            existing_keys = {row[0] for row in existing_sentences}
        
        # 第三步：构建映射数据（只对比内存集合，不再查询数据库）
        sentence_mappings = []
        evs_mappings = []
        sentence_keys_seen = set()  # 用于去重，避免同一批次中重复插入
        
        for type, params, content, hashed_str in tqdm(entry_data, desc="Processing EVS entries", unit="entry"):
            logger.debug("evs %s %s %s", type, params, content)
            
            # Entry Content 为空
            if content is None:
                evs_mappings.append({
                    'type': type,
                    'param': params,
                    'sentence_key': None,
                    'hgar_file_id': hgar_file_id,
                })
                continue

            # 检查是否需要插入新的 Sentence（只对比内存集合，O(1) 操作）
            if hashed_str not in sentence_keys_seen:
                # 如果数据库中不存在，且当前批次中也没处理过，则添加到插入列表
                if hashed_str not in existing_keys:
                    sentence_mappings.append({
                        'key': hashed_str,
                        'content': content,
                    })
                    logger.debug("Evs add: %s", hashed_str)
                sentence_keys_seen.add(hashed_str)

            evs_mappings.append({
                'type': type,
                'param': params,
                'sentence_key': hashed_str,
                'hgar_file_id': hgar_file_id,
            })
        
        # 使用 bulk_insert_mappings 批量插入 Sentence（绕过 ORM 开销）
        if sentence_mappings:
            db.bulk_insert_mappings(Sentence, sentence_mappings)
        
        # 使用 bulk_insert_mappings 批量插入 EVS Entry（绕过 ORM 开销）
        if evs_mappings:
            db.bulk_insert_mappings(EVSEntry, evs_mappings)
        
        # 注意：不在这里提交，由调用者统一提交

    def form_evs_wrapper(hgar_file_id: int) -> tools.EvsWrapper:
        with next(get_db()) as db:
            # 获取所有EVS条目
            evs_entries = (
                db.query(EVSEntry)
                .filter(EVSEntry.hgar_file_id == hgar_file_id)
                .order_by(EVSEntry.id.asc())
                .all()
            )
            logger.debug("Loaded %d EVS entries for hgar_file_id=%s", len(evs_entries), hgar_file_id)
            
            # 提取所有非null的sentence_key
            sentence_keys = {entry.sentence_key for entry in evs_entries if entry.sentence_key is not None}
            
            # 一次性批量加载所有Translation
            translations_map = {}
            if sentence_keys:
                translations = (
                    db.query(Translation)
                    .filter(Translation.key.in_(sentence_keys))
                    .all()
                )
                translations_map = {t.key: t.content for t in translations}
            
            # 一次性批量加载所有Sentence
            sentences_map = {}
            if sentence_keys:
                sentences = (
                    db.query(Sentence)
                    .filter(Sentence.key.in_(sentence_keys))
                    .all()
                )
                sentences_map = {s.key: s.content for s in sentences}
            
            evs = tools.EvsWrapper()
            for entry in tqdm(evs_entries, desc="Forming EVS wrapper", unit="entry"):
                if entry.sentence_key is None:
                    evs.add_entry(entry.type, entry.param, b"")
                    continue
                
                content = sentences_map.get(entry.sentence_key, b"")
                if entry.translation:
                    content = entry.translation
                elif entry.sentence_key in translations_map:
                    content = translations_map[entry.sentence_key]
                logger.debug("EVS content: %s", content)
                evs.add_entry(entry.type, entry.param, content)
            return evs

    @staticmethod
    def _entry_context(evs_entry: EVSEntry) -> str:
        if evs_entry.param and len(evs_entry.param) >= 2:
            avatar, exp = get_avatar_and_exp(evs_entry.param[0], evs_entry.param[1])
        else:
            avatar, exp = f"function_{evs_entry.type}", None
        return f"AVA: {avatar}\nEXP: {exp}"

    @staticmethod
    def export_cev_translations(output_dir: str) -> int:
        """
        Export CEV event translations as one JSON file per EVS.

        The per-entry key uses the EVS-local entry index instead of the
        deduplicated sentence key, so repeated originals can be translated
        independently.
        """
        cev_dir = os.path.join(output_dir, "cev")
        os.makedirs(cev_dir, exist_ok=True)

        exported = 0
        with next(get_db()) as db:
            cev_files = (
                db.query(Hgar.relative_path, Hgar.name, HgarFile.id, HgarFile.short_name)
                .join(HgarFile, HgarFile.hgar_id == Hgar.id)
                .filter(Hgar.name.like("cev%"))
                .filter(HgarFile.short_name.like("%.evs"))
                .order_by(Hgar.relative_path.asc(), Hgar.name.asc(), HgarFile.short_name.asc())
                .all()
            )

            for _, _, hgar_file_id, evs_name in cev_files:
                evs_entries = (
                    db.query(EVSEntry)
                    .filter(EVSEntry.hgar_file_id == hgar_file_id)
                    .order_by(EVSEntry.id.asc())
                    .all()
                )
                sentence_keys = {
                    entry.sentence_key
                    for entry in evs_entries
                    if entry.sentence_key is not None
                }
                sentences_map = {}
                translations_map = {}
                if sentence_keys:
                    sentences = db.query(Sentence).filter(Sentence.key.in_(sentence_keys)).all()
                    translations = db.query(Translation).filter(Translation.key.in_(sentence_keys)).all()
                    sentences_map = {sentence.key: sentence.content for sentence in sentences}
                    translations_map = {translation.key: translation.content for translation in translations}

                data = []
                for entry_index, evs_entry in enumerate(evs_entries):
                    if (
                        evs_entry.sentence_key is None
                        or evs_entry.type not in HAS_CONTENT_SECTION
                    ):
                        continue

                    original = sentences_map.get(evs_entry.sentence_key, "")
                    if not _is_cev_translatable_original(original):
                        continue

                    translation = evs_entry.translation or translations_map.get(
                        evs_entry.sentence_key, ""
                    )
                    data.append(
                        {
                            "key": f"{evs_name}:{entry_index:06d}",
                            "entry_index": entry_index,
                            "original": original,
                            "translation": translation,
                            "context": EVSDao._entry_context(evs_entry),
                        }
                    )

                output_name = evs_name[:-4] if evs_name.endswith(".evs") else evs_name
                output_path = os.path.join(cev_dir, f"{output_name}.json")
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                exported += 1

        return exported

    @staticmethod
    def _parse_cev_entry_index(item: dict) -> Optional[int]:
        entry_index = item.get("entry_index")
        if entry_index is not None:
            try:
                return int(entry_index)
            except (TypeError, ValueError):
                return None

        key = item.get("key")
        if not isinstance(key, str) or ":" not in key:
            return None
        try:
            return int(key.rsplit(":", 1)[1])
        except ValueError:
            return None

    @staticmethod
    def import_cev_translations(input_dir: str) -> tuple[int, int]:
        """
        Import split CEV EVS translations from a directory of JSON files.

        Returns:
            (imported, skipped)
        """
        imported = 0
        skipped = 0

        if not os.path.isdir(input_dir):
            raise FileNotFoundError(f"CEV translation directory not found: {input_dir}")

        with next(get_db()) as db:
            for root, _, files in os.walk(input_dir):
                for file in sorted(files):
                    if not file.endswith(".json"):
                        continue

                    file_path = os.path.join(root, file)
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if not isinstance(data, list):
                        skipped += 1
                        continue

                    stem = file[:-5]
                    evs_name = stem if stem.endswith(".evs") else f"{stem}.evs"
                    hgar_file = (
                        db.query(HgarFile)
                        .join(Hgar, HgarFile.hgar_id == Hgar.id)
                        .filter(Hgar.name.like("cev%"))
                        .filter(HgarFile.short_name == evs_name)
                        .first()
                    )
                    if hgar_file is None:
                        skipped += len(data)
                        logger.warning("CEV EVS not found for %s", file_path)
                        continue

                    evs_entries = (
                        db.query(EVSEntry)
                        .filter(EVSEntry.hgar_file_id == hgar_file.id)
                        .order_by(EVSEntry.id.asc())
                        .all()
                    )
                    sentence_keys = {
                        entry.sentence_key
                        for entry in evs_entries
                        if entry.sentence_key is not None
                    }
                    sentences_map = {}
                    if sentence_keys:
                        sentences = db.query(Sentence).filter(Sentence.key.in_(sentence_keys)).all()
                        sentences_map = {sentence.key: sentence.content for sentence in sentences}

                    for item in data:
                        if not isinstance(item, dict):
                            skipped += 1
                            continue

                        translation = item.get("translation")
                        if not translation:
                            skipped += 1
                            continue

                        entry_index = EVSDao._parse_cev_entry_index(item)
                        if entry_index is None or entry_index >= len(evs_entries) or entry_index < 0:
                            skipped += 1
                            continue

                        evs_entry = evs_entries[entry_index]
                        if evs_entry.sentence_key is None:
                            skipped += 1
                            continue

                        original = item.get("original")
                        current_original = sentences_map.get(evs_entry.sentence_key)
                        if original is not None and current_original != original:
                            skipped += 1
                            logger.warning(
                                "Original mismatch in %s at entry %s",
                                file_path,
                                entry_index,
                            )
                            continue

                        evs_entry.translation = translation
                        imported += 1

            db.commit()

        return imported, skipped
