import os
import argparse

from app.parser import tools

from app.database.dao.hgar import HGARDao
from app.database.dao.sentence import SentenceDao
from app.database.dao.translation import TranslationDao
from app.database.dao.hgpt import HgptDao
from app.database.dao.text_entry import TextEntryDao
from app.database.dao.bind import BindDao

from app.database.db import Base, engine, get_db
from app.utils.evs import get_avatar_and_exp

HGAR_PREFIX = ["a", "b2a", "b2s", "bb", "bs", "cev", "e", "f", "levent", "n", "tev"]


class App:
    def __init__(self):
        # Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        pass

    @staticmethod
    def import_har(dir_path: str):
        # 解析为绝对路径
        base_path = os.path.abspath(dir_path)
        # 获取基础目录名（如 "btdemo", "event" 等）
        base_dir_name = os.path.basename(base_path)
        
        # 收集所有 HAR 文件路径
        har_files = []
        for root, _, files in os.walk(base_path):
            for file in files:
                if file.endswith(".har"):
                    full_path = os.path.join(root, file)
                    # 计算相对于base_path的相对路径
                    relative_to_base = os.path.relpath(root, base_path)
                    
                    # 构建完整的相对路径（包含基础目录名）
                    if relative_to_base == '.':
                        # 文件直接在基础目录下
                        relative_dir = base_dir_name
                    else:
                        # 文件在子目录下
                        relative_dir = os.path.join(base_dir_name, relative_to_base)
                    
                    har_files.append((full_path, relative_dir))
        
        # 使用单个数据库会话批量处理所有文件
        from app.database.db import get_db
        with next(get_db()) as db:
            for full_path, relative_dir in har_files:
                App.decompile_hgar(full_path, relative_dir, db=db)
            
            # 统一提交所有数据（只提交一次！）
            db.commit()
    
    @staticmethod
    def compile_hgar(name: str, output_dir: str):
        hgar: tools.HGArchive = HGARDao.get_hgar_by_name(name)
        hgar.save(os.path.join(output_dir, name))
        pass
    
    @staticmethod
    def output_hgar(output_dir: str, prefix: str = None):
        """
        导出 HGAR 文件，按原始目录结构
        
        Args:
            output_dir: 输出目录
            prefix: 可选的前缀过滤（如 'a', 'cev' 等），如果为 None 则导出所有
        """
        os.makedirs(output_dir, exist_ok=True)
        count = 0
        
        if prefix:
            # 按前缀过滤
            print(f"Exporting HAR files with prefix: {prefix}")
            # 需要获取relative_path，所以使用完整查询
            from app.database.entity.hgar import Hgar
            from app.database.db import get_db
            with next(get_db()) as db:
                hgars_with_path = db.query(Hgar).filter(Hgar.name.like(f"{prefix}%")).all()
                for hgar_entity in hgars_with_path:
                    hgar = HGARDao.get_hgar_by_name(hgar_entity.name)
                    # 创建子目录如果需要
                    if hgar_entity.relative_path:
                        target_dir = os.path.join(output_dir, hgar_entity.relative_path)
                    else:
                        target_dir = output_dir
                    os.makedirs(target_dir, exist_ok=True)
                    output_path = os.path.join(target_dir, hgar_entity.name)
                    hgar.save(output_path)
                    count += 1
        else:
            # 导出所有 HAR，按目录结构（逐个处理避免内存占用）
            print(f"Exporting all HAR files with original directory structure")
            from app.database.entity.hgar import Hgar
            from app.database.db import get_db
            
            with next(get_db()) as db:
                # 只获取基本信息，不加载文件内容
                hgar_entities = db.query(Hgar.id, Hgar.name, Hgar.relative_path).all()
                total = len(hgar_entities)
                
                for idx, (hgar_id, name, relative_path) in enumerate(hgar_entities, 1):
                    print(f"  [{idx}/{total}] Exporting {relative_path}/{name if relative_path else name}")
                    
                    # 逐个加载和保存
                    hgar = HGARDao.get_hgar_by_name_and_rel_path(name, relative_path)
                    
                    # 创建子目录如果需要
                    if relative_path:
                        target_dir = os.path.join(output_dir, relative_path)
                    else:
                        target_dir = output_dir
                    os.makedirs(target_dir, exist_ok=True)
                    output_path = os.path.join(target_dir, name)
                    hgar.save(output_path)
                    count += 1
        
        print(f"Exported {count} HAR files to {output_dir}")
    
    @staticmethod
    def decompile_hgar(path: str, relative_path: str = "", db=None):
        """
        解压并保存 HGAR 文件到数据库
        
        Args:
            path: HAR 文件路径
            relative_path: 相对路径
            db: 可选的数据库会话，用于批量操作（避免重复提交）
        """
        hgar = tools.HGArchive(None, [])
        hgar.open(path)

        filename = os.path.basename(path)
        print(f"Extracted filename: {filename} (path: {relative_path})")

        # Store HGAR & HGAR Files into DB（不提交，由调用者统一提交）
        HGARDao.save(filename, hgar, relative_path, db=db)
        
        # Logging the HGAR info
        # hgar.info()

    @staticmethod
    def output_evs(path: str, prefix: str = None):
        """
        输出 EVS 原文 JSON
        
        Args:
            path: 输出目录
            prefix: 可选的前缀过滤（如 'a', 'cev' 等），如果为 None 则导出所有
        """
        os.makedirs(path, exist_ok=True)
        
        if prefix:
            # 如果指定了前缀，使用旧的逻辑（按前缀导出，主要用于 event 目录）
            print(f"Exporting {prefix}")
            results = SentenceDao.export_sentence_entry(prefix)
            if results:
                list = []
                for sentence, evs_entry in results:
                    # 对于非对话类型（如 function 149），参数可能为空
                    if len(evs_entry.param) >= 2:
                        avatar, exp = get_avatar_and_exp(evs_entry.param[0], evs_entry.param[1])
                    else:
                        avatar, exp = f"function_{evs_entry.type}", None
                    key = sentence.key
                    original = sentence.content
                    list.append(
                        {
                            "key": key,
                            "original": original,
                            "context": f"AVA: {avatar}\nEXP: {exp}",
                        }
                    )
                # Write to file
                with open(f"{path}/{prefix}.json", "w", encoding="utf-8") as f:
                    import json
                    f.write(json.dumps(list, indent=4, ensure_ascii=False))
        else:
            # 导出所有：先按前缀导出 event 目录，再按 relative_path 导出其他目录
            
            # 1. 导出 event 目录（按前缀分类）
            print("Exporting event directory by prefix...")
            for prefix_item in HGAR_PREFIX:
                print(f"  Exporting {prefix_item}")
                results = SentenceDao.export_sentence_entry(prefix_item)
                if not results:
                    continue
                    
                list = []
                for sentence, evs_entry in results:
                    # 对于非对话类型（如 function 149），参数可能为空
                    if len(evs_entry.param) >= 2:
                        avatar, exp = get_avatar_and_exp(evs_entry.param[0], evs_entry.param[1])
                    else:
                        avatar, exp = f"function_{evs_entry.type}", None
                    key = sentence.key
                    original = sentence.content
                    list.append(
                        {
                            "key": key,
                            "original": original,
                            "context": f"AVA: {avatar}\nEXP: {exp}",
                        }
                    )
                # Write to file
                with open(f"{path}/{prefix_item}.json", "w", encoding="utf-8") as f:
                    import json
                    f.write(json.dumps(list, indent=4, ensure_ascii=False))
            
            # 2. 导出其他目录（按 relative_path 分类）
            print("Exporting other directories by path...")
            all_paths = SentenceDao.get_all_relative_paths()
            for rel_path in all_paths:
                # 跳过 event 目录（已经按前缀处理过了）
                if rel_path == 'event' or rel_path.startswith('event/'):
                    continue
                
                print(f"  Exporting {rel_path}")
                results = SentenceDao.export_sentence_by_path(rel_path)
                if not results:
                    continue
                
                list = []
                for sentence, evs_entry in results:
                    # 对于非对话类型（如 function 149），参数可能为空
                    if len(evs_entry.param) >= 2:
                        avatar, exp = get_avatar_and_exp(evs_entry.param[0], evs_entry.param[1])
                    else:
                        avatar, exp = f"function_{evs_entry.type}", None
                    key = sentence.key
                    original = sentence.content
                    list.append(
                        {
                            "key": key,
                            "original": original,
                            "context": f"AVA: {avatar}\nEXP: {exp}",
                        }
                    )
                
                # 文件名使用路径（将 / 替换为 _）
                filename = rel_path.replace('/', '_')
                with open(f"{path}/{filename}.json", "w", encoding="utf-8") as f:
                    import json
                    f.write(json.dumps(list, indent=4, ensure_ascii=False))

    @staticmethod
    def import_translation(filepath: str):
        # Drop all translations
        # TranslationDao.delete_all()
        # Windows 默认编码可能不是 UTF-8，导致读取包含多字节字符的文件时抛出
        # “'gbk' codec can't decode byte ...” 等错误，因此显式使用 UTF-8。
        with open(filepath, "r", encoding="utf-8") as f:
            import json

            data = json.load(f)
            TranslationDao.save_translations(data)
        pass

    @staticmethod
    def output_translation(output_dir: str, prefix: str = None):
        """
        导出翻译 JSON
        
        Args:
            output_dir: 输出目录
            prefix: 可选的前缀过滤（如 'a', 'cev' 等），如果为 None 则导出所有
        """
        os.makedirs(output_dir, exist_ok=True)
        
        if prefix:
            # 如果指定了前缀，使用旧的逻辑（按前缀导出，主要用于 event 目录）
            print(f"Exporting {prefix}")
            results = SentenceDao.export_sentence_entry(prefix)
            if results:
                list = []
                for sentence, evs_entry in results:
                    # 对于非对话类型（如 function 149），参数可能为空
                    if len(evs_entry.param) >= 2:
                        avatar, exp = get_avatar_and_exp(evs_entry.param[0], evs_entry.param[1])
                    else:
                        avatar, exp = f"function_{evs_entry.type}", None
                    key = sentence.key
                    original = sentence.content
                    list.append(
                        {
                            "key": key,
                            "original": original,
                            "translation": TranslationDao.get_translation_by_key(key),
                            "context": f"AVA: {avatar}\nEXP: {exp}",
                        }
                    )
                # Write to file
                with open(f"{output_dir}/{prefix}.json", "w", encoding="utf-8") as f:
                    import json
                    f.write(json.dumps(list, indent=4, ensure_ascii=False))
        else:
            # 导出所有：先按前缀导出 event 目录，再按 relative_path 导出其他目录
            
            # 1. 导出 event 目录（按前缀分类）
            print("Exporting event directory by prefix...")
            for prefix_item in HGAR_PREFIX:
                print(f"  Exporting {prefix_item}")
                results = SentenceDao.export_sentence_entry(prefix_item)
                if not results:
                    continue
                    
                list = []
                for sentence, evs_entry in results:
                    # 对于非对话类型（如 function 149），参数可能为空
                    if len(evs_entry.param) >= 2:
                        avatar, exp = get_avatar_and_exp(evs_entry.param[0], evs_entry.param[1])
                    else:
                        avatar, exp = f"function_{evs_entry.type}", None
                    key = sentence.key
                    original = sentence.content
                    list.append(
                        {
                            "key": key,
                            "original": original,
                            "translation": TranslationDao.get_translation_by_key(key),
                            "context": f"AVA: {avatar}\nEXP: {exp}",
                        }
                    )
                # Write to file
                with open(f"{output_dir}/{prefix_item}.json", "w", encoding="utf-8") as f:
                    import json
                    f.write(json.dumps(list, indent=4, ensure_ascii=False))
            
            # 2. 导出其他目录（按 relative_path 分类）
            print("Exporting other directories by path...")
            all_paths = SentenceDao.get_all_relative_paths()
            for path in all_paths:
                # 跳过 event 目录（已经按前缀处理过了）
                if path == 'event' or path.startswith('event/'):
                    continue
                
                print(f"  Exporting {path}")
                results = SentenceDao.export_sentence_by_path(path)
                if not results:
                    continue
                
                list = []
                for sentence, evs_entry in results:
                    # 对于非对话类型（如 function 149），参数可能为空
                    if len(evs_entry.param) >= 2:
                        avatar, exp = get_avatar_and_exp(evs_entry.param[0], evs_entry.param[1])
                    else:
                        avatar, exp = f"function_{evs_entry.type}", None
                    key = sentence.key
                    original = sentence.content
                    list.append(
                        {
                            "key": key,
                            "original": original,
                            "translation": TranslationDao.get_translation_by_key(key),
                            "context": f"AVA: {avatar}\nEXP: {exp}",
                        }
                    )
                
                # 文件名使用路径（将 / 替换为 _）
                filename = path.replace('/', '_')
                with open(f"{output_dir}/{filename}.json", "w", encoding="utf-8") as f:
                    import json
                    f.write(json.dumps(list, indent=4, ensure_ascii=False))

    @staticmethod
    def output_images(output_dir: str):
        """
        导出所有 HGPT 图像到指定目录
        按照 HAR 文件组织，文件名包含短名称和 hash
        """
        print(f"Exporting HGPT images to {output_dir}")
        HgptDao.export_all_images(output_dir)

    @staticmethod
    def import_images(translation_dir: str):
        """
        从指定目录导入翻译后的图像
        根据文件名中的 hash 匹配图像
        """
        print(f"Importing translated images from {translation_dir}")
        HgptDao.import_translated_images(translation_dir)
    
    @staticmethod
    def import_text(text_file_path: str):
        """
        导入 TEXT 文件（如 f2tuto.bin, f2info.bin）
        解析并存储到数据库
        """
        from app.parser.tools import text as text_module
        from app.database.entity.text_entry import TextEntry
        
        # 确保表存在
        Base.metadata.create_all(bind=engine)
        
        print(f"Importing TEXT file: {text_file_path}")
        
        # 使用 TextArchive 解析文件
        text_archive = text_module.TextArchive()
        text_archive.open(text_file_path)
        
        # 获取文件名
        filename = os.path.basename(text_file_path)
        
        # 保存到数据库
        TextEntryDao.save_text_file(filename, text_archive)
    
    @staticmethod
    def export_text(output_dir: str, filename: str = None):
        """
        导出 TEXT 文件为原始二进制格式
        应用数据库中的翻译
        
        Args:
            output_dir: 输出目录
            filename: 可选的特定文件名（如 f2info.bin），不指定则导出所有
        """
        from app.parser.tools import text as text_module
        
        os.makedirs(output_dir, exist_ok=True)
        
        with next(get_db()) as db:
            from app.database.entity.text_entry import TextEntry
            
            # 获取所有已导入的 TEXT 文件
            if filename:
                files = db.query(TextEntry.filename).filter(
                    TextEntry.filename == filename
                ).distinct().all()
            else:
                files = db.query(TextEntry.filename).distinct().all()
            
            count = 0
            for (file_name,) in files:
                print(f"Exporting {file_name}")
                
                # 创建新的 TextArchive
                text_archive = text_module.TextArchive()
                
                # 从数据库重建
                TextEntryDao.rebuild_text_archive(file_name, text_archive)
                
                # 保存为二进制文件
                output_path = os.path.join(output_dir, file_name)
                text_archive.save(output_path)
                count += 1
        
        print(f"Exported {count} TEXT files to {output_dir}")
    
    @staticmethod
    def export_text_json(output_dir: str, filename: str = None):
        """
        导出 TEXT 文件为 JSON（用于 Paratranz）
        
        Args:
            output_dir: 输出目录
            filename: 可选的特定文件名
        """
        os.makedirs(output_dir, exist_ok=True)
        
        with next(get_db()) as db:
            from app.database.entity.text_entry import TextEntry
            
            # 获取所有已导入的 TEXT 文件
            if filename:
                files = db.query(TextEntry.filename).filter(
                    TextEntry.filename == filename
                ).distinct().all()
            else:
                files = db.query(TextEntry.filename).distinct().all()
            
            count = 0
            for (file_name,) in files:
                json_path = os.path.join(output_dir, f"{file_name}.json")
                TextEntryDao.export_text_translations(file_name, json_path)
                count += 1
        
        print(f"Exported {count} TEXT files as JSON")
    
    @staticmethod
    def import_bind(bind_file_path: str):
        """
        导入 BIND 文件（如 imtext.bin, btimtext.bin）
        解析并存储到数据库
        """
        from app.parser.tools import bind as bind_module
        from app.database.entity.bind_entry import BindEntry
        
        # 确保表存在
        Base.metadata.create_all(bind=engine)
        
        print(f"Importing BIND file: {bind_file_path}")
        
        # 使用 BindArchive 解析文件
        bind_archive = bind_module.BindArchive()
        bind_archive.open(bind_file_path)
        
        # 获取文件名
        filename = os.path.basename(bind_file_path)
        
        # 保存到数据库
        BindDao.save_bind_file(filename, bind_archive)
    
    @staticmethod
    def export_bind(output_dir: str, filename: str = None):
        """
        导出 BIND 文件为原始二进制格式
        应用数据库中的翻译
        
        Args:
            output_dir: 输出目录
            filename: 可选的特定文件名（如 imtext.bin），不指定则导出所有
        """
        from app.parser.tools import bind as bind_module
        
        os.makedirs(output_dir, exist_ok=True)
        
        # 获取所有已导入的 BIND 文件
        if filename:
            filenames = [filename]
        else:
            filenames = BindDao.get_all_bind_filenames()
        
        count = 0
        for file_name in filenames:
            print(f"Exporting {file_name}")
            
            # 创建新的 BindArchive
            bind_archive = bind_module.BindArchive()
            
            # 从数据库重建
            BindDao.rebuild_bind_archive(file_name, bind_archive)
            
            # 保存为二进制文件
            output_path = os.path.join(output_dir, file_name)
            bind_archive.save(output_path)
            count += 1
        
        print(f"Exported {count} BIND files to {output_dir}")
    
    @staticmethod
    def export_bind_json(output_dir: str, filename: str = None):
        """
        导出 BIND 文件为 JSON（用于 Paratranz）
        
        Args:
            output_dir: 输出目录
            filename: 可选的特定文件名
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # 获取所有已导入的 BIND 文件
        if filename:
            filenames = [filename]
        else:
            filenames = BindDao.get_all_bind_filenames()
        
        count = 0
        for file_name in filenames:
            json_path = os.path.join(output_dir, f"{file_name}.json")
            BindDao.export_bind_translations(file_name, json_path)
            count += 1
        
        print(f"Exported {count} BIND files as JSON")

    @staticmethod
    def export_eboot_trans(translation_path: str, output_path: str = "EBTRANS.BIN"):
        """
        生成 EBOOT 翻译二进制文件（EBTRANS.BIN）
        
        Args:
            translation_path: 翻译 JSON 文件路径或包含 chunk_*.json 的目录
            output_path: 输出文件路径，默认为 EBTRANS.BIN
        """
        from app.elf_patch.patcher import Patcher, TranslationHeader
        
        print(f"正在生成 EBOOT 翻译文件...")
        print(f"翻译文件路径: {translation_path}")
        print(f"输出文件路径: {output_path}")
        
        patcher = Patcher()
        try:
            patcher.load_translation(translation_path)
        except Exception as e:
            print(f"错误：加载翻译文件失败: {e}")
            raise
        
        try:
            entries = patcher.patch_translation()
        except Exception as e:
            print(f"错误：处理翻译条目失败: {e}")
            raise
        
        print(f"成功处理 {len(entries)} 个翻译条目（共 {len(patcher.data)} 个条目）")
        
        header = TranslationHeader(num=len(entries))
        try:
            # 确保输出目录存在
            output_dir = os.path.dirname(output_path) or '.'
            os.makedirs(output_dir, exist_ok=True)
            
            with open(output_path, "wb") as f:
                f.write(header.to_bytes())
                for entry in entries:
                    f.write(entry.to_bytes())
            print(f"成功生成 EBTRANS.BIN: {output_path}")
        except Exception as e:
            print(f"错误：写入输出文件失败: {e}")
            raise
    
    def compile():
        pass


if __name__ == "__main__":
    # HGAR ARG
    parser = argparse.ArgumentParser(description="Import/Export NGE2 Game Assets")

    # Import All HGAR files
    parser.add_argument("--import_har", type=str, help="The path to the HAR file")

    # TODO: Import TEXT/BIN files

    # Export EVS Original
    parser.add_argument(
        "--export_evs", type=str, help="Path for exporting EVS Originals"
    )
    parser.add_argument(
        "--evs_prefix", type=str, help="Optional: filter by prefix (e.g., 'a', 'cev')"
    )

    # Import Translations
    parser.add_argument(
        "--import_translation",
        type=str,
        help="Path of the translation file from Paratranz",
    )

    # Export Translations
    parser.add_argument(
        "--export_translation", type=str, help="Path for exporting translations"
    )
    parser.add_argument(
        "--translation_prefix", type=str, help="Optional: filter by prefix (e.g., 'a', 'cev')"
    )

    # Output HGAR
    parser.add_argument(
        "--output_hgar", type=str, help="Path for exporting HGAR files"
    )
    parser.add_argument(
        "--hgar_prefix", type=str, help="Optional: filter by prefix (e.g., 'a', 'cev')"
    )

    # Export Images (HGPT)
    parser.add_argument(
        "--export_images", type=str, help="Path for exporting HGPT images as PNG"
    )

    # Import Translated Images
    parser.add_argument(
        "--import_images",
        type=str,
        help="Path to the directory containing translated PNG images",
    )
    
    # Import TEXT (f2tuto.bin, f2info.bin)
    parser.add_argument(
        "--import_text",
        type=str,
        help="Path to TEXT file (f2tuto.bin, f2info.bin, etc.)",
    )
    
    # Export TEXT
    parser.add_argument(
        "--export_text",
        type=str,
        help="Path for exporting TEXT files",
    )
    parser.add_argument(
        "--text_filename",
        type=str,
        help="Optional: specific TEXT filename to export",
    )
    
    # Export TEXT as JSON
    parser.add_argument(
        "--export_text_json",
        type=str,
        help="Path for exporting TEXT files as JSON (Paratranz format)",
    )
    
    # 初始化数据库
    parser.add_argument("--init_db", action="store_true", help="Initialize the database")
    # Import BIND (imtext.bin, btimtext.bin)
    parser.add_argument(
        "--import_bind",
        type=str,
        help="Path to BIND file (imtext.bin, btimtext.bin, etc.)",
    )
    
    # Export BIND
    parser.add_argument(
        "--export_bind",
        type=str,
        help="Path for exporting BIND files",
    )
    parser.add_argument(
        "--bind_filename",
        type=str,
        help="Optional: specific BIND filename to export",
    )
    
    # Export BIND as JSON
    parser.add_argument(
        "--export_bind_json",
        type=str,
        help="Path for exporting BIND files as JSON (Paratranz format)",
    )
    
    # Export EBOOT Translation (EBTRANS.BIN)
    parser.add_argument(
        "--export_eboot_trans",
        type=str,
        help="Path to translation JSON file or directory containing chunk_*.json files",
    )
    parser.add_argument(
        "--eboot_trans_output",
        type=str,
        default="EBTRANS.BIN",
        help="Output path for EBTRANS.BIN (default: EBTRANS.BIN)",
    )

    args = parser.parse_args()
    if args.init_db:
        print("Initializing database...")
        App()
    elif args.import_har:
        App.import_har(args.import_har)
    elif args.export_evs:
        App.output_evs(args.export_evs, prefix=args.evs_prefix)
    elif args.import_translation:
        App.import_translation(args.import_translation)
    elif args.export_translation:
        App.output_translation(args.export_translation, prefix=args.translation_prefix)
    elif args.output_hgar:
        App.output_hgar(args.output_hgar, prefix=args.hgar_prefix)
    elif args.export_images:
        App.output_images(args.export_images)
    elif args.import_images:
        App.import_images(args.import_images)
    elif args.import_text:
        App.import_text(args.import_text)
    elif args.export_text:
        App.export_text(args.export_text, filename=args.text_filename)
    elif args.export_text_json:
        App.export_text_json(args.export_text_json, filename=args.text_filename)
    elif args.import_bind:
        App.import_bind(args.import_bind)
    elif args.export_bind:
        App.export_bind(args.export_bind, filename=args.bind_filename)
    elif args.export_bind_json:
        App.export_bind_json(args.export_bind_json, filename=args.bind_filename)
    elif args.export_eboot_trans:
        App.export_eboot_trans(args.export_eboot_trans, args.eboot_trans_output)