from ..db import get_db

# Entities
from ..entity.translation import Translation


class TranslationDao:
    @staticmethod
    def delete_all():
        with next(get_db()) as db:
            db.query(Translation).delete()
            db.commit()
    
    @staticmethod
    def save(translation: Translation):
        with next(get_db()) as db:
            db.add(translation)
            db.commit()
            db.refresh(translation)
            return translation

    @staticmethod
    def save_translations(data):
        """
        翻译JSON 结构：
        data = [
            {
                key:
                content:
            }
        ]
        """
        imported = 0
        skipped = 0
        with next(get_db()) as db:
            for d in data:
                key = d.get("key")
                translation_content = d.get("translation")
                if not key or not translation_content:
                    skipped += 1
                    continue

                # 检查是否已存在该 key
                existing = db.query(Translation).filter(Translation.key == key).first()
                if existing:
                    # 更新已存在的记录
                    existing.content = translation_content
                else:
                    # 创建新记录
                    translation = Translation(key=key, content=translation_content)
                    db.add(translation)
                imported += 1
            db.commit()
        return imported, skipped

    @staticmethod
    def get_translation_by_key(key: str):
        with next(get_db()) as db:
            trans = db.query(Translation).filter(Translation.key == key).first()
            return trans.content if trans else ""
