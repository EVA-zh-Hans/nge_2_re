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
    def prepare_translations(data):
        translations = {}
        skipped = 0
        for item in data:
            key = item.get("key")
            content = item.get("translation")
            if not key or not content:
                skipped += 1
                continue
            translations[key] = content
        return translations, skipped

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
        translations, skipped = TranslationDao.prepare_translations(data)
        with next(get_db()) as db:
            existing_by_key = {}
            keys = list(translations)
            for start in range(0, len(keys), 900):
                rows = (
                    db.query(Translation)
                    .filter(Translation.key.in_(keys[start:start + 900]))
                    .order_by(Translation.id)
                    .all()
                )
                for row in rows:
                    existing_by_key.setdefault(row.key, []).append(row)

            for key, content in translations.items():
                existing = existing_by_key.get(key, [])
                if existing:
                    existing[0].content = content
                    for duplicate in existing[1:]:
                        db.delete(duplicate)
                else:
                    db.add(Translation(key=key, content=content))
            db.commit()
        return len(translations), skipped

    @staticmethod
    def get_translation_by_key(key: str):
        with next(get_db()) as db:
            trans = db.query(Translation).filter(Translation.key == key).first()
            return trans.content if trans else ""
