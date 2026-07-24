"""
Persist EVSWrapper
"""

import hashlib
import logging
from tqdm import tqdm

from ..db import get_db
from app.parser import tools

from ..entity.evs_entry import EVSEntry
from ..entity.sentence import Sentence
from ..entity.translation import Translation

logger = logging.getLogger(__name__)


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
                
                # 从缓存中获取内容（O(1) 字典查询）
                content = sentences_map.get(entry.sentence_key, b"")
                if entry.sentence_key in translations_map:
                    content = translations_map[entry.sentence_key]
                logger.debug("EVS content: %s", content)
                evs.add_entry(entry.type, entry.param, content)
            return evs
