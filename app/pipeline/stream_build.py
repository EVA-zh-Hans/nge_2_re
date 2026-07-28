from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.parser.tools.bind import BindArchive
from app.parser.tools.hgar import HGArchive, HGArchiveFile
from app.parser.tools.text import TextArchive

from .catalog import ImageCatalog, TranslationCatalog
from .transforms import (
    compress_hgar_entry,
    decompress_hgar_entry,
    rebuild_hgpt,
    transform_evs,
    transform_text_archive,
)


ROOT = Path(__file__).resolve().parents[2]
HGAR_DIRS = ("btdemo", "btface", "btl", "chara", "event", "face", "free", "game", "im", "map")
TEXT_FILES = (Path("free/f2info.bin"), Path("free/f2tuto.bin"))
BIND_FILES = (Path("btl/btimtext.bin"), Path("game/imtext.bin"))


@dataclass
class BuildStats:
    text_files: int = 0
    text_entries_translated: int = 0
    bind_files: int = 0
    bind_text_entries_translated: int = 0
    archives: int = 0
    changed_archives: int = 0
    copied_archives: int = 0
    archive_entries: int = 0
    evs_files_changed: int = 0
    evs_entries_translated: int = 0
    hgpt_files_changed: int = 0
    hgpt_cache_hits: int = 0
    duplicate_archive_entries_preserved: int = 0
    verified_archives: int = 0
    timings: dict[str, float] = field(default_factory=dict)


@dataclass
class PendingArchive:
    archive: HGArchive
    source: Path
    target: Path
    image_replacements: list[tuple[HGArchiveFile, Future[bytes]]]
    changed: bool
    duplicate_count: int


class StreamBuilder:
    def __init__(
        self,
        source: Path,
        output: Path,
        downloads: Path,
        images: Path,
        staff_output: Path,
        staff_header: Path,
        include_staff: bool,
        image_workers: int = 4,
    ) -> None:
        self.source = source.resolve()
        self.output = output.resolve()
        self.downloads = downloads.resolve()
        self.images = images.resolve()
        self.staff_output = staff_output.resolve()
        self.staff_header = staff_header.resolve()
        self.include_staff = include_staff
        if image_workers < 1:
            raise ValueError("image_workers must be at least 1")
        self.image_workers = image_workers
        self.archive_window = image_workers * 2
        self.stats = BuildStats()
        self.translations: TranslationCatalog | None = None
        self.image_catalog: ImageCatalog | None = None
        self._rebuilt_hgpt: dict[str, Future[bytes]] = {}

    def build(self) -> dict:
        self._validate_inputs()
        started = time.perf_counter()

        self._timed("load_catalogs", self._load_catalogs)
        self._timed("transform_text", self._transform_text_files)
        self._timed("transform_bind", self._transform_bind_files)
        self._timed("transform_hgar", self._transform_hgar_files)
        if self.include_staff:
            self._timed("generate_and_inject_staff_roll", self._generate_staff_roll)

        self.stats.timings["total"] = time.perf_counter() - started
        return self._report()

    def _timed(self, name: str, operation) -> None:
        started = time.perf_counter()
        operation()
        self.stats.timings[name] = time.perf_counter() - started
        print(f"{name}: {self.stats.timings[name]:.3f}s", flush=True)

    def _validate_inputs(self) -> None:
        required = [
            self.source,
            self.downloads / "evs_trans.json",
            self.downloads / "utf8/EVS/cev",
            self.downloads / "utf8/free/info.json",
            self.downloads / "utf8/free/tuto.json",
            self.downloads / "utf8/game/btimtext.json",
            self.downloads / "utf8/game/imtext.json",
            self.images,
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError("missing streaming pipeline inputs:\n" + "\n".join(missing))

    def _load_catalogs(self) -> None:
        generic_paths = [
            self.downloads / "evs_trans.json",
            self.downloads / "utf8/free/info.json",
            self.downloads / "utf8/free/tuto.json",
            self.downloads / "utf8/game/btimtext.json",
            self.downloads / "utf8/game/imtext.json",
        ]
        self.translations = TranslationCatalog.load(
            generic_paths, self.downloads / "utf8/EVS/cev"
        )
        self.image_catalog = ImageCatalog.load(self.images)

    def _transform_text_files(self) -> None:
        assert self.translations is not None
        for relative_path in TEXT_FILES:
            source = self.source / relative_path
            archive = TextArchive()
            archive.open(str(source))
            applied = transform_text_archive(
                archive, source.name, self.translations
            )
            target = self.output / relative_path
            if applied:
                _atomic_save(archive.save, target)
            else:
                _atomic_copy(source, target)
            self.stats.text_files += 1
            self.stats.text_entries_translated += applied

    def _transform_bind_files(self) -> None:
        assert self.translations is not None
        for relative_path in BIND_FILES:
            source = self.source / relative_path
            archive = BindArchive()
            archive.open(str(source))
            applied = 0
            for entry_index, entry in enumerate(archive.entries):
                if not entry.content.startswith(b"TEXT"):
                    continue
                text_archive = TextArchive()
                text_archive.open_bytes(entry.content)
                entry_applied = transform_text_archive(
                    text_archive,
                    f"{source.name}#{entry_index}",
                    self.translations,
                )
                if entry_applied:
                    entry.content = text_archive.serialize()
                    applied += entry_applied
            target = self.output / relative_path
            if applied:
                _atomic_save(archive.save, target)
            else:
                _atomic_copy(source, target)
            self.stats.bind_files += 1
            self.stats.bind_text_entries_translated += applied

    def _transform_hgar_files(self) -> None:
        paths = []
        for directory in HGAR_DIRS:
            paths.extend((self.source / directory).rglob("*.har"))
        paths.sort(key=lambda path: path.relative_to(self.source).as_posix())
        pending: deque[PendingArchive] = deque()
        completed = 0
        with ThreadPoolExecutor(
            max_workers=self.image_workers,
            thread_name_prefix="hgpt",
        ) as executor:
            for source in paths:
                target = self.output / source.relative_to(self.source)
                pending.append(self._prepare_hgar(source, target, executor))
                if len(pending) >= self.archive_window:
                    self._finish_hgar(pending.popleft())
                    completed += 1
                    self._report_hgar_progress(completed, len(paths))
            while pending:
                self._finish_hgar(pending.popleft())
                completed += 1
                self._report_hgar_progress(completed, len(paths))

    def _prepare_hgar(
        self,
        source: Path,
        target: Path,
        executor: ThreadPoolExecutor,
    ) -> PendingArchive:
        assert self.translations is not None
        assert self.image_catalog is not None
        archive = HGArchive(None, [])
        archive.open(str(source))
        changed = False
        image_replacements = []
        seen_keys = set()
        duplicate_count = 0

        for entry in archive.files:
            short_name = _normalized_name(entry.short_name)
            duplicate_key = (short_name, entry.encoded_identifier)
            if duplicate_key in seen_keys:
                duplicate_count += 1
            seen_keys.add(duplicate_key)

            lower_name = short_name.lower()
            if not lower_name.endswith((".evs", ".hpt", ".zpt")):
                continue
            content = (
                decompress_hgar_entry(entry.content)
                if entry.is_compressed
                else entry.content
            )

            replacement = None
            if lower_name.endswith(".evs"):
                transformed, applied = transform_evs(
                    content, short_name, self.translations
                )
                if applied:
                    replacement = transformed
                    self.stats.evs_files_changed += 1
                    self.stats.evs_entries_translated += applied
            else:
                content_hash = hashlib.md5(content).hexdigest()
                image_override = self.image_catalog.find(content_hash)
                if image_override is not None:
                    future = self._rebuilt_hgpt.get(content_hash)
                    if future is None:
                        future = executor.submit(rebuild_hgpt, content, image_override)
                        self._rebuilt_hgpt[content_hash] = future
                    else:
                        self.stats.hgpt_cache_hits += 1
                    image_replacements.append((entry, future))
                    self.stats.hgpt_files_changed += 1
                    changed = True

            if replacement is not None:
                entry.content = (
                    compress_hgar_entry(replacement)
                    if entry.is_compressed
                    else replacement
                )
                entry.size = len(entry.content)
                changed = True

        return PendingArchive(
            archive=archive,
            source=source,
            target=target,
            image_replacements=image_replacements,
            changed=changed,
            duplicate_count=duplicate_count,
        )

    def _finish_hgar(self, pending: PendingArchive) -> None:
        for entry, future in pending.image_replacements:
            replacement = future.result()
            entry.content = (
                compress_hgar_entry(replacement)
                if entry.is_compressed
                else replacement
            )
            entry.size = len(entry.content)

        if pending.changed:
            _atomic_save_archive(pending.archive, pending.target)
            self.stats.changed_archives += 1
            self.stats.verified_archives += 1
        else:
            _atomic_copy(pending.source, pending.target)
            self.stats.copied_archives += 1
        self.stats.archives += 1
        self.stats.archive_entries += len(pending.archive.files)
        self.stats.duplicate_archive_entries_preserved += pending.duplicate_count

    @staticmethod
    def _report_hgar_progress(completed: int, total: int) -> None:
        if completed % 100 == 0 or completed == total:
            print(f"processed HGAR {completed}/{total}", flush=True)

    def _generate_staff_roll(self) -> None:
        from scripts.staff.generate_staff_roll import write_outputs

        write_outputs(
            manifest_path=ROOT / "resources/staff_roll/credits.json",
            font_path=ROOT / "resources/assets/font/SourceHanSerifSC-Heavy.otf",
            title_font_path=ROOT / "resources/assets/font/SourceHanSansSC-Medium.otf",
            output_dir=self.staff_output,
            header_path=self.staff_header,
            inject_path=self.output / "game/staff.har",
        )

    def _report(self) -> dict:
        assert self.translations is not None
        assert self.image_catalog is not None
        unique_images = sum(len(items) for items in self.image_catalog.by_length.values())
        return {
            "source": str(self.source),
            "output": str(self.output),
            "settings": {"image_workers": self.image_workers},
            "stats": asdict(self.stats),
            "catalogs": {
                "generic_translations": len(self.translations.generic),
                "generic_translations_matched": len(self.translations.used_generic),
                "generic_translation_conflicts": self.translations.generic_conflicts,
                "generic_translations_unmatched": sorted(
                    set(self.translations.generic) - self.translations.used_generic
                ),
                "cev_translations": len(self.translations.cev),
                "cev_translations_matched": len(self.translations.used_cev),
                "cev_translations_unmatched": [
                    f"{name}:{index}"
                    for name, index in sorted(
                        set(self.translations.cev) - self.translations.used_cev
                    )
                ],
                "cev_original_mismatches": self.translations.cev_original_mismatches,
                "translated_image_files": self.image_catalog.total_files,
                "translated_images_unique": unique_images,
                "translated_image_duplicates": self.image_catalog.duplicate_files,
                "translated_image_conflicts": self.image_catalog.conflicts,
                "translated_images_matched": len(self.image_catalog.used_paths),
                "translated_images_unmatched": [
                    str(override.path)
                    for overrides in self.image_catalog.by_length.values()
                    for override in overrides.values()
                    if override.path not in self.image_catalog.used_paths
                ],
            },
        }


def _normalized_name(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("ascii").rstrip(" \t\r\n\0")
    return value.rstrip(" \t\r\n\0")


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copyfile(source, temporary_path)
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_save(save, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        save(str(temporary_path))
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_save_archive(archive: HGArchive, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        archive.save(str(temporary_path))
        verification = HGArchive(None, [])
        verification.open(str(temporary_path))
        expected = [
            (
                _normalized_name(entry.short_name),
                entry.encoded_identifier,
                entry.content,
            )
            for entry in archive.files
        ]
        actual = [
            (
                _normalized_name(entry.short_name),
                entry.encoded_identifier,
                entry.content,
            )
            for entry in verification.files
        ]
        if actual != expected:
            raise ValueError(f"HGAR round-trip verification failed: {target}")
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build translated resources without an intermediate database"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "temp/ULJS00064/PSP_GAME/USRDIR",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build/direct/ULJS00064/PSP_GAME/USRDIR",
    )
    parser.add_argument("--downloads", type=Path, default=ROOT / "temp/downloads")
    parser.add_argument(
        "--images", type=Path, default=ROOT / "resources/trans_pic/trans"
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "build/direct/resource-report.json"
    )
    parser.add_argument(
        "--staff-output",
        type=Path,
        default=ROOT / "build/direct/generated/staff_roll",
    )
    parser.add_argument(
        "--staff-header",
        type=Path,
        default=ROOT / "plugin/src/runtime/patches/generated_staff_roll.h",
    )
    parser.add_argument("--image-workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--skip-staff", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    builder = StreamBuilder(
        source=args.source,
        output=args.output,
        downloads=args.downloads,
        images=args.images,
        staff_output=args.staff_output,
        staff_header=args.staff_header,
        include_staff=not args.skip_staff,
        image_workers=args.image_workers,
    )
    report = builder.build()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"report: {args.report}")


if __name__ == "__main__":
    main()
