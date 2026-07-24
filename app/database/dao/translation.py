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
        with next(get_db()) as db:
            for d in data:
                # 检查是否已存在该 key
                existing = db.query(Translation).filter(Translation.key == d["key"]).first()
                if existing:
                    # 更新已存在的记录
                    existing.content = d["translation"]
                else:
                    # 创建新记录
                    translation = Translation(key=d["key"], content=d["translation"])
                    db.add(translation)
            db.commit()

    @staticmethod
    def get_translation_by_key(key: str):
        with next(get_db()) as db:
            trans = db.query(Translation).filter(Translation.key == key).first()
            return trans.content if trans else ""
