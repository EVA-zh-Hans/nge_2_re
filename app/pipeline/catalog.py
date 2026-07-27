from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CevOverride:
    original: str | None
    translation: str
    source: str


@dataclass
class TranslationCatalog:
    generic: dict[str, str]
    cev: dict[tuple[str, int], CevOverride]
    generic_conflicts: list[dict[str, str]] = field(default_factory=list)
    used_generic: set[str] = field(default_factory=set)
    used_cev: set[tuple[str, int]] = field(default_factory=set)
    cev_original_mismatches: list[str] = field(default_factory=list)

    @classmethod
    def load(
        cls, generic_paths: list[Path], cev_dir: Path
    ) -> "TranslationCatalog":
        generic: dict[str, str] = {}
        generic_conflicts = []
        for path in generic_paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError(f"translation file must contain a list: {path}")
            for item in data:
                if not isinstance(item, dict):
                    continue
                key = item.get("key")
                translation = item.get("translation")
                if key and translation:
                    key = str(key)
                    translation = str(translation)
                    previous = generic.get(key)
                    if previous is not None and previous != translation:
                        generic_conflicts.append(
                            {
                                "key": key,
                                "previous": previous,
                                "replacement": translation,
                                "source": str(path),
                            }
                        )
                    generic[key] = translation

        cev: dict[tuple[str, int], CevOverride] = {}
        for path in sorted(cev_dir.rglob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            evs_name = path.stem
            if not evs_name.lower().endswith(".evs"):
                evs_name += ".evs"
            evs_name = evs_name.lower()
            for item in data:
                if not isinstance(item, dict) or not item.get("translation"):
                    continue
                entry_index = _parse_cev_entry_index(item)
                if entry_index is None or entry_index < 0:
                    continue
                key = (evs_name, entry_index)
                override = CevOverride(
                    original=item.get("original"),
                    translation=str(item["translation"]),
                    source=str(path),
                )
                previous = cev.get(key)
                if previous and previous != override:
                    raise ValueError(f"conflicting CEV override for {key}: {path}")
                cev[key] = override
        return cls(generic=generic, cev=cev, generic_conflicts=generic_conflicts)

    def generic_for(self, original: str) -> str | None:
        key = hashlib.md5(original.encode()).hexdigest()
        translation = self.generic.get(key)
        if translation:
            self.used_generic.add(key)
        return translation

    def cev_for(self, evs_name: str, entry_index: int, original: str) -> str | None:
        key = (evs_name.lower(), entry_index)
        override = self.cev.get(key)
        if override is None:
            return None
        if override.original is not None and override.original != original:
            self.cev_original_mismatches.append(
                f"{override.source}: {evs_name} entry {entry_index} original mismatch"
            )
            return None
        self.used_cev.add(key)
        return override.translation


@dataclass(frozen=True)
class ImageOverride:
    prefix: str
    path: Path
    digest: str


@dataclass
class ImageCatalog:
    by_length: dict[int, dict[str, ImageOverride]]
    total_files: int
    duplicate_files: int
    conflicts: list[dict[str, str]]
    used_paths: set[Path] = field(default_factory=set)

    @classmethod
    def load(cls, image_dir: Path) -> "ImageCatalog":
        by_length: dict[int, dict[str, ImageOverride]] = {}
        total_files = 0
        duplicate_files = 0
        conflicts = []
        for path in sorted(image_dir.rglob("*.png")):
            total_files += 1
            prefix = path.stem.rsplit("_", 1)[-1].lower()
            if len(prefix) < 6 or any(char not in "0123456789abcdef" for char in prefix):
                continue
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            override = ImageOverride(prefix=prefix, path=path, digest=digest)
            matches = by_length.setdefault(len(prefix), {})
            previous = matches.get(prefix)
            if previous is not None:
                if previous.digest == digest:
                    duplicate_files += 1
                    continue
                chosen = max(
                    (previous, override),
                    key=lambda item: (
                        len(item.path.relative_to(image_dir).parts),
                        item.path.as_posix(),
                    ),
                )
                conflicts.append(
                    {
                        "prefix": prefix,
                        "first": str(previous.path),
                        "second": str(path),
                        "chosen": str(chosen.path),
                    }
                )
                matches[prefix] = chosen
                continue
            matches[prefix] = override
        return cls(by_length, total_files, duplicate_files, conflicts)

    def find(self, full_hash: str) -> ImageOverride | None:
        candidates = []
        for length, overrides in self.by_length.items():
            override = overrides.get(full_hash[:length])
            if override is not None:
                candidates.append(override)
        if not candidates:
            return None
        digests = {candidate.digest for candidate in candidates}
        if len(digests) != 1:
            paths = ", ".join(str(candidate.path) for candidate in candidates)
            raise ValueError(f"ambiguous translated images for {full_hash}: {paths}")
        chosen = max(candidates, key=lambda candidate: len(candidate.prefix))
        self.used_paths.add(chosen.path)
        return chosen


def _parse_cev_entry_index(item: dict) -> int | None:
    value = item.get("entry_index")
    if value is None:
        key = item.get("key")
        if not isinstance(key, str) or ":" not in key:
            return None
        value = key.rsplit(":", 1)[1]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
