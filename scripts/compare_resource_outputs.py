#!/usr/bin/env python3

from __future__ import annotations

import argparse
import io
import json
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.parser.tools.evs import (  # noqa: E402
    HAS_CONTENT_SECTION,
    get_number_of_parameters,
)
from app.parser.tools.hgar import HGArchive  # noqa: E402
from app.parser.tools.hgp import HgptReader  # noqa: E402
from app.pipeline.transforms import decompress_hgar_entry  # noqa: E402


@dataclass
class Difference:
    path: str
    reason: str


def normalized_name(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("ascii").rstrip(" \t\r\n\0")
    return value.rstrip(" \t\r\n\0")


def entry_content(entry) -> bytes:
    return decompress_hgar_entry(entry.content) if entry.is_compressed else entry.content


def evs_semantic(content: bytes):
    if content[:4] != b".EVS":
        raise ValueError("missing EVS magic")
    count = struct.unpack_from("<I", content, 4)[0]
    offsets = struct.unpack_from(f"<{count}I", content, 8)
    entries = []
    for offset in offsets:
        entry_type, entry_size = struct.unpack_from("<HH", content, offset)
        parameter_count = get_number_of_parameters(entry_type)
        if parameter_count is None:
            raise ValueError(f"unknown EVS entry type 0x{entry_type:X}")
        parameter_offset = offset + 4
        parameters = struct.unpack_from(
            f"<{parameter_count}I", content, parameter_offset
        )
        content_size = entry_size - parameter_count * 4
        raw = b""
        if entry_type in HAS_CONTENT_SECTION:
            raw_offset = parameter_offset + parameter_count * 4
            raw = content[raw_offset:raw_offset + content_size].rstrip(b"\0")
        elif content_size:
            raise ValueError(f"unexpected EVS content for type 0x{entry_type:X}")
        entries.append((entry_type, parameters, raw))
    return entries


def text_semantic(content: bytes):
    if content[:4] != b"TEXT":
        raise ValueError("missing TEXT magic")
    count = struct.unpack_from("<I", content, 4)[0]
    entries = []
    for entry_index in range(count):
        entry_unknown, string_offset = struct.unpack_from(
            "<II", content, 16 + entry_index * 8
        )
        if string_offset + 8 > len(content):
            entries.append((entry_unknown, 0, 0, b""))
            continue
        unknown_first, unknown_second = struct.unpack_from(
            "<II", content, string_offset
        )
        string_start = string_offset + 8
        string_end = content.find(b"\0", string_start)
        if string_end < 0:
            string_end = len(content)
        entries.append(
            (
                entry_unknown,
                unknown_first,
                unknown_second,
                content[string_start:string_end],
            )
        )
    return entries


def bind_semantic(content: bytes):
    if content[:4] != b"BIND":
        raise ValueError("missing BIND magic")
    size_width, count = struct.unpack_from("<HH", content, 4)
    block_size, header_size = struct.unpack_from("<II", content, 8)
    if size_width not in (1, 2, 4):
        raise ValueError(f"invalid BIND size width {size_width}")
    sizes = []
    cursor = 16
    for _ in range(count):
        sizes.append(int.from_bytes(content[cursor:cursor + size_width], "little"))
        cursor += size_width
    entries = []
    cursor = header_size
    for size in sizes:
        raw = content[cursor:cursor + size]
        entries.append(text_semantic(raw) if raw.startswith(b"TEXT") else raw)
        cursor += ((size + block_size - 1) // block_size) * block_size
    return size_width, block_size, entries


def hgpt_semantic(content: bytes):
    image = HgptReader(io.BytesIO(content)).read()
    division = None
    if image.division_info:
        division = (
            image.division_info.name,
            tuple(image.division_info.divisions),
        )
    palette = tuple(image.palette.colors) if image.palette else None
    return (
        image.header.has_extended_header,
        image.header.unknown_one,
        image.header.unknown_two,
        image.header.unknown_three,
        image.display_info.width,
        image.display_info.height,
        division,
        palette,
        tuple(tuple(pixel) if isinstance(pixel, (list, tuple)) else pixel for pixel in image.content),
    )


def compare_hgar(reference: Path, candidate: Path) -> str | None:
    left = HGArchive(None, [])
    right = HGArchive(None, [])
    left.open(str(reference))
    right.open(str(candidate))
    if left.version != right.version:
        return f"HGAR version differs: {left.version} != {right.version}"
    if len(left.files) != len(right.files):
        return f"HGAR entry count differs: {len(left.files)} != {len(right.files)}"

    for index, (left_entry, right_entry) in enumerate(zip(left.files, right.files)):
        left_metadata = (
            normalized_name(left_entry.long_name),
            normalized_name(left_entry.short_name),
            left_entry.encoded_identifier,
            left_entry.is_compressed,
        )
        right_metadata = (
            normalized_name(right_entry.long_name),
            normalized_name(right_entry.short_name),
            right_entry.encoded_identifier,
            right_entry.is_compressed,
        )
        if left_metadata != right_metadata:
            return f"HGAR entry {index} metadata differs: {left_metadata} != {right_metadata}"

        left_content = entry_content(left_entry)
        right_content = entry_content(right_entry)
        if left_content == right_content:
            continue
        short_name = normalized_name(left_entry.short_name).lower()
        try:
            if short_name.endswith(".evs"):
                equal = evs_semantic(left_content) == evs_semantic(right_content)
            elif short_name.endswith((".hpt", ".zpt")):
                equal = hgpt_semantic(left_content) == hgpt_semantic(right_content)
            else:
                equal = False
        except Exception as exc:
            return f"HGAR entry {index} semantic parse failed: {exc}"
        if not equal:
            return f"HGAR entry {index} content differs: {short_name}"
    return None


def compare_trees(reference: Path, candidate: Path) -> dict:
    left_files = {
        path.relative_to(reference).as_posix(): path
        for path in reference.rglob("*")
        if path.is_file()
    }
    right_files = {
        path.relative_to(candidate).as_posix(): path
        for path in candidate.rglob("*")
        if path.is_file()
    }
    differences = []
    identical = 0
    semantic = 0

    for path in sorted(set(left_files) - set(right_files)):
        differences.append(Difference(path, "missing from candidate"))
    for path in sorted(set(right_files) - set(left_files)):
        differences.append(Difference(path, "missing from reference"))

    for relative_path in sorted(set(left_files) & set(right_files)):
        left = left_files[relative_path]
        right = right_files[relative_path]
        if left.read_bytes() == right.read_bytes():
            identical += 1
            continue
        if relative_path.lower().endswith(".har"):
            reason = compare_hgar(left, right)
            if reason is None:
                semantic += 1
                continue
        elif relative_path.lower().endswith(("f2info.bin", "f2tuto.bin")):
            reason = None if text_semantic(left.read_bytes()) == text_semantic(right.read_bytes()) else "TEXT content differs"
            if reason is None:
                semantic += 1
                continue
        elif relative_path.lower().endswith(("btimtext.bin", "imtext.bin")):
            reason = None if bind_semantic(left.read_bytes()) == bind_semantic(right.read_bytes()) else "BIND content differs"
            if reason is None:
                semantic += 1
                continue
        else:
            reason = "file bytes differ"
        differences.append(Difference(relative_path, reason))

    return {
        "reference": str(reference),
        "candidate": str(candidate),
        "reference_files": len(left_files),
        "candidate_files": len(right_files),
        "byte_identical_files": identical,
        "semantically_equal_files": semantic,
        "different_files": len(differences),
        "differences": [asdict(difference) for difference in differences],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare database and streaming resource output trees"
    )
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--allow-differences", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = compare_trees(args.reference.resolve(), args.candidate.resolve())
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"identical={report['byte_identical_files']} "
        f"semantic={report['semantically_equal_files']} "
        f"different={report['different_files']}"
    )
    print(f"report: {args.json}")
    if report["different_files"] and not args.allow_differences:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
