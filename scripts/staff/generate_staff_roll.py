#!/usr/bin/env python3

import argparse
import io
import json
import math
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "app" / "parser" / "tools"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from hgar import HGArchive, HGArchiveFile  # noqa: E402
from hgp import (  # noqa: E402
    DisplayInfo,
    DivisionInfo,
    HgptHeader,
    HgptImage,
    HgptWriter,
    Palette,
)


ATLAS_NUMBER_BASE = 21
ATLAS_NUMBER_MAX = 999
ATLAS_WIDTH = 512
ATLAS_HEIGHT = 480
PHYSICAL_ROW_HEIGHT = 40
MAX_PHYSICAL_ROWS = ATLAS_HEIGHT // PHYSICAL_ROW_HEIGHT
LEFT_REGION = (0, 240)
RIGHT_REGION = (256, 496)
TITLE_REGION = (40, 472)
EXTRA_ROW_BASE = 214
MAX_ROW_ID = 0x7FFF
MIN_ENTRY_FONT_SIZE = 12
ORIGINAL_COMMAND_COUNT = 196
ORIGINAL_INSERT_INDEX = 189
ALPHA_GAMMA = 0.65
PALETTE_ALPHA_EXPONENT = 0.45
WHITE_BLEND_START = 176
HGAR_IDENTIFIER_PREFIX = 0x90697000

CTRL_PAGE_BREAK = 0x00001088
CTRL_TITLE = 0x00100208
CTRL_PAIR = 0x0000020A
CTRL_CENTERED = 0x00000208
CTRL_SECTION_GAP = 0x00000108

GENERATED_ATLAS_PATTERN = re.compile(r"^staff(\d{2,3})\.(?:hpt|png|json)$")
ARCHIVE_ATLAS_PATTERN = re.compile(r"^staff(\d{2,3})\.hpt$")


@dataclass(frozen=True)
class CreditSection:
    title: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class LayoutEntry:
    text: str
    region: tuple[int, int]
    row_id: int
    is_title: bool = False


@dataclass(frozen=True)
class LayoutRow:
    entries: tuple[LayoutEntry, ...]


@dataclass(frozen=True)
class RenderedEntry:
    text: str
    physical_row: int
    region_left: int
    region_right: int
    row_id: int


@dataclass(frozen=True)
class AtlasBuild:
    name: str
    image: HgptImage
    preview: Image.Image
    entries: tuple[RenderedEntry, ...]
    physical_rows: int

    @property
    def filename(self) -> str:
        return f"{self.name}.hpt"

    @property
    def first_row_id(self) -> int:
        return self.entries[0].row_id

    @property
    def division_count(self) -> int:
        return len(self.entries)


def atlas_name(index: int) -> str:
    number = ATLAS_NUMBER_BASE + index
    if number > ATLAS_NUMBER_MAX:
        raise ValueError(
            f"staff roll requires more than {ATLAS_NUMBER_MAX - ATLAS_NUMBER_BASE + 1} atlases"
        )
    return f"staff{number}"


def load_manifest(path: Path) -> tuple[int, list[CreditSection]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    font_size = int(data.get("font_size", 22))
    if font_size <= 0:
        raise ValueError("font_size must be positive")

    sections = []
    for index, item in enumerate(data.get("sections", [])):
        title = str(item.get("title", "")).strip()
        names = tuple(str(name).strip() for name in item.get("names", []) if str(name).strip())
        if not title:
            raise ValueError(f"sections[{index}].title is empty")
        if not names:
            raise ValueError(f"sections[{index}].names is empty")
        sections.append(CreditSection(title=title, names=names))

    if not sections:
        raise ValueError("credits manifest contains no sections")
    return font_size, sections


def layout_sections(
    sections: list[CreditSection],
) -> tuple[list[LayoutRow], list[tuple[int, int, int]]]:
    rows: list[LayoutRow] = []
    commands = [(CTRL_PAGE_BREAK, -1, -1)]
    next_row_id = EXTRA_ROW_BASE

    for section_index, section in enumerate(sections):
        title_entry = LayoutEntry(
            text=section.title,
            region=TITLE_REGION,
            row_id=next_row_id,
            is_title=True,
        )
        rows.append(LayoutRow((title_entry,)))
        commands.append((CTRL_TITLE, next_row_id, -1))
        commands.append((CTRL_SECTION_GAP, -1, -1))
        next_row_id += 1

        for name_index in range(0, len(section.names), 2):
            left_name = section.names[name_index]
            if name_index + 1 >= len(section.names):
                entry = LayoutEntry(left_name, TITLE_REGION, next_row_id)
                rows.append(LayoutRow((entry,)))
                commands.append((CTRL_CENTERED, next_row_id, -1))
                next_row_id += 1
                continue

            right_name = section.names[name_index + 1]
            left_entry = LayoutEntry(left_name, LEFT_REGION, next_row_id)
            right_entry = LayoutEntry(right_name, RIGHT_REGION, next_row_id + 1)
            rows.append(LayoutRow((left_entry, right_entry)))
            commands.append((CTRL_PAIR, next_row_id, next_row_id + 1))
            next_row_id += 2

        if section_index + 1 < len(sections):
            commands.append((CTRL_SECTION_GAP, -1, -1))

    if next_row_id - 1 > MAX_ROW_ID:
        raise ValueError(
            f"staff roll row id {next_row_id - 1} exceeds signed 16-bit limit {MAX_ROW_ID}"
        )
    return rows, commands


def text_bounds(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int, int, int]:
    return ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)


def _draw_text_with_glow(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    text: str,
    x: int,
    y: int,
) -> None:
    if not text.strip():
        return
    temp = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(temp)
    draw.text((x, y), text, font=font, fill=240)
    glow = temp.filter(ImageFilter.GaussianBlur(radius=1.8))
    ImageDraw.Draw(glow).text((x, y), text, font=font, fill=255)
    image.paste(ImageChops.lighter(image, glow))


def place_text(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    entry: LayoutEntry,
    physical_row: int,
) -> tuple[RenderedEntry, tuple[int, int, int, int]]:
    left, right = entry.region
    available = right - left
    fitted_font = font
    bbox = text_bounds(fitted_font, entry.text)
    while bbox[2] - bbox[0] > available and fitted_font.size > MIN_ENTRY_FONT_SIZE:
        fitted_font = font.font_variant(size=fitted_font.size - 1)
        bbox = text_bounds(fitted_font, entry.text)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    if width > available:
        raise ValueError(f"text is too wide ({width}>{available}): {entry.text}")

    x = left + (available - width) // 2 - bbox[0]
    row_top = physical_row * PHYSICAL_ROW_HEIGHT
    y = row_top + (PHYSICAL_ROW_HEIGHT - height) // 2 - bbox[1]
    _draw_text_with_glow(image, fitted_font, entry.text, x, y)

    rendered = RenderedEntry(entry.text, physical_row, left, right, entry.row_id)
    return rendered, (x + bbox[0], row_top, width, PHYSICAL_ROW_HEIGHT)


def build_palette() -> list[tuple[int, int, int, int]]:
    core_r, core_g, core_b = 0, 19, 255
    colors = [(0, 0, 0, 0)]
    for index in range(1, 256):
        alpha = round(255 * ((index / 255) ** PALETTE_ALPHA_EXPONENT))
        t = max(0.0, (index - WHITE_BLEND_START) / (255 - WHITE_BLEND_START))
        blend = t * t * (3 - 2 * t)
        r = int(core_r + (255 - core_r) * blend)
        g = int(core_g + (255 - core_g) * blend)
        b = int(core_b + (255 - core_b) * blend)
        colors.append((r, g, b, alpha))
    return colors


def render_atlas(
    name: str,
    rows: list[LayoutRow],
    body_font: ImageFont.FreeTypeFont,
    title_font: ImageFont.FreeTypeFont,
    palette_colors: list[tuple[int, int, int, int]],
) -> AtlasBuild:
    alpha_image = Image.new("L", (ATLAS_WIDTH, ATLAS_HEIGHT), 0)
    divisions = [(0, 0, ATLAS_WIDTH, ATLAS_HEIGHT)]
    rendered_entries: list[RenderedEntry] = []

    for physical_row, row in enumerate(rows):
        for entry in row.entries:
            font = title_font if entry.is_title else body_font
            rendered, division = place_text(alpha_image, font, entry, physical_row)
            rendered_entries.append(rendered)
            divisions.append(division)

    content = [
        0
        if alpha == 0
        else min(255, round(255 * ((alpha / 255) ** ALPHA_GAMMA)))
        for alpha in alpha_image.tobytes()
    ]
    header = HgptHeader()
    header.has_extended_header = True
    image = HgptImage(
        header=header,
        display_info=DisplayInfo(ATLAS_WIDTH, ATLAS_HEIGHT),
        content=content,
        palette=Palette(palette_colors),
        division_info=DivisionInfo(name, divisions),
    )
    preview = Image.new("RGBA", (ATLAS_WIDTH, ATLAS_HEIGHT))
    preview.putdata([palette_colors[index] for index in content])
    return AtlasBuild(name, image, preview, tuple(rendered_entries), len(rows))


def build_atlases(
    font_path: Path,
    title_font_path: Path,
    font_size: int,
    sections: list[CreditSection],
) -> tuple[list[AtlasBuild], list[tuple[int, int, int]]]:
    rows, commands = layout_sections(sections)
    body_font = ImageFont.truetype(str(font_path), font_size)
    title_font = ImageFont.truetype(str(title_font_path), font_size)
    palette_colors = build_palette()
    atlases = []
    for index, start in enumerate(range(0, len(rows), MAX_PHYSICAL_ROWS)):
        chunk = rows[start:start + MAX_PHYSICAL_ROWS]
        atlases.append(
            render_atlas(atlas_name(index), chunk, body_font, title_font, palette_colors)
        )
    return atlases, commands


def build_atlas(
    font_path: Path,
    title_font_path: Path,
    font_size: int,
    sections: list[CreditSection],
) -> tuple[HgptImage, Image.Image, list[tuple[int, int, int]], list[RenderedEntry]]:
    atlases, commands = build_atlases(font_path, title_font_path, font_size, sections)
    if len(atlases) != 1:
        raise ValueError(f"credits require {len(atlases)} atlases; use build_atlases")
    atlas = atlases[0]
    return atlas.image, atlas.preview, commands, list(atlas.entries)


def render_header(
    commands: list[tuple[int, int, int]],
    atlases: list[AtlasBuild],
) -> str:
    command_lines = "\n".join(
        f"    {{0x{ctrl:08X}u, {left}, {right}}}," for ctrl, left, right in commands
    )
    atlas_lines = "\n".join(
        f'    {{"{atlas.name}", {atlas.first_row_id}, {atlas.division_count}}},'
        for atlas in atlases
    )
    total_rows = sum(atlas.division_count for atlas in atlases)
    return f"""/* Generated by scripts/staff/generate_staff_roll.py. Do not edit. */
#pragma once

#define STAFF_ROLL_EXTRA_ROW_BASE {EXTRA_ROW_BASE}
#define STAFF_ROLL_EXTRA_ROW_COUNT {total_rows}
#define STAFF_ROLL_ATLAS_COUNT {len(atlases)}
#define STAFF_ROLL_EXTRA_COMMAND_COUNT {len(commands)}
#define STAFF_ROLL_ORIGINAL_COMMAND_COUNT {ORIGINAL_COMMAND_COUNT}
#define STAFF_ROLL_INSERT_INDEX {ORIGINAL_INSERT_INDEX}
#define STAFF_ROLL_EXTENDED_COMMAND_COUNT \\
    (STAFF_ROLL_ORIGINAL_COMMAND_COUNT + STAFF_ROLL_EXTRA_COMMAND_COUNT)

typedef struct StaffRollAtlasInfo {{
    const char *name;
    int16_t first_row;
    int16_t row_count;
}} StaffRollAtlasInfo;

static const StaffRollAtlasInfo g_staffRollAtlases[STAFF_ROLL_ATLAS_COUNT] = {{
{atlas_lines}
}};

static const StaffScrollCmd g_staffRollExtraCommands[STAFF_ROLL_EXTRA_COMMAND_COUNT] = {{
{command_lines}
}};
"""


def encode_hgpt(image: HgptImage) -> bytes:
    buffer = io.BytesIO()
    HgptWriter(image).write(buffer)
    return buffer.getvalue()


def compress_hgar_entry(raw: bytes) -> bytes:
    compressed = zlib.compress(raw)
    return struct.pack("<I", len(raw)) + compressed[2:-4]


def normalized_name(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("ascii").rstrip(" \t\r\n\0")
    return value.rstrip(" \t\r\n\0")


def is_generated_archive_atlas(name: str) -> bool:
    match = ARCHIVE_ATLAS_PATTERN.fullmatch(name)
    return bool(match and int(match.group(1)) >= ATLAS_NUMBER_BASE)


def _find_encoded_identifier(
    identifier_limit: int,
    used_encoded: set[int],
    used_decoded: set[int],
) -> tuple[int, int]:
    for suffix in range(0x26, 0x10000):
        encoded = HGAR_IDENTIFIER_PREFIX + suffix
        if encoded in used_encoded:
            continue
        probe = HGArchiveFile(b"", "", 0, encoded_identifier=encoded)
        probe.decode_identifier(identifier_limit)
        if probe.identifier not in used_decoded:
            return encoded, probe.identifier
    raise ValueError("unable to allocate a unique HGAR identifier for staff atlas")


def inject_hgar(har_path: Path, hgpt_data: dict[str, bytes]) -> None:
    archive = HGArchive(None, [])
    archive.open(str(har_path))
    if archive.version != 3:
        raise ValueError(f"{har_path} is HGAR v{archive.version}; expected v3")

    desired_names = set(hgpt_data)
    retained_files = []
    existing_targets = {}
    for item in archive.files:
        item.short_name = normalized_name(item.short_name)
        name = normalized_name(item.long_name)
        if is_generated_archive_atlas(name):
            if name in desired_names:
                existing_targets[name] = item
                retained_files.append(item)
            continue
        retained_files.append(item)
    archive.files = retained_files

    final_file_count = len(retained_files) + len(desired_names - set(existing_targets))
    if final_file_count > 16384:
        raise ValueError(
            f"HGAR would contain {final_file_count} files; identifier format supports 16384"
        )
    original_limit = archive.identifier_limit
    current_limit = 32
    while final_file_count > current_limit // 2:
        current_limit *= 2
    if current_limit > 32768:
        current_limit = 32768

    used_encoded = {item.encoded_identifier for item in archive.files}
    used_decoded = set()
    for item in archive.files:
        item.decode_identifier(current_limit)
        if item.identifier in used_decoded:
            raise ValueError(
                f"HGAR identifier collision after limit change {original_limit}->{current_limit}"
            )
        used_decoded.add(item.identifier)

    for name in sorted(desired_names):
        compressed = compress_hgar_entry(hgpt_data[name])
        target = existing_targets.get(name)
        if target is None:
            encoded, decoded = _find_encoded_identifier(
                current_limit, used_encoded, used_decoded
            )
            target = HGArchiveFile(
                long_name=(name + "\0").encode("ascii"),
                short_name=name,
                size=len(compressed),
                encoded_identifier=encoded,
                content=compressed,
            )
            target.identifier = decoded
            target.is_compressed = True
            archive.files.append(target)
            used_encoded.add(encoded)
            used_decoded.add(decoded)
        else:
            target.content = compressed
            target.size = len(compressed)
            target.encoded_identifier |= 0x80000000
            target.is_compressed = True

    archive.calculate_identifier_limit()
    if archive.identifier_limit != current_limit:
        raise ValueError(
            f"unexpected HGAR identifier limit {archive.identifier_limit}; expected {current_limit}"
        )
    archive.save(str(har_path))

    verification = HGArchive(None, [])
    verification.open(str(har_path))
    names = [normalized_name(item.long_name) for item in verification.files]
    for name in desired_names:
        if names.count(name) != 1:
            raise ValueError(f"expected one {name} after injection, found {names.count(name)}")
    stale = [name for name in names if is_generated_archive_atlas(name) and name not in desired_names]
    if stale:
        raise ValueError(f"stale generated staff atlases remain after injection: {stale}")
    decoded_ids = [item.identifier for item in verification.files]
    if len(decoded_ids) != len(set(decoded_ids)):
        raise ValueError("HGAR contains duplicate decoded identifiers after injection")


def _clean_generated_outputs(output_dir: Path, desired_names: set[str]) -> None:
    for path in output_dir.iterdir():
        match = GENERATED_ATLAS_PATTERN.fullmatch(path.name)
        if not match:
            continue
        stem = path.name.split(".", 1)[0]
        if stem not in desired_names:
            path.unlink()


def _combined_preview(atlases: list[AtlasBuild]) -> Image.Image:
    columns = min(4, len(atlases))
    rows = math.ceil(len(atlases) / columns)
    image = Image.new("RGBA", (columns * ATLAS_WIDTH, rows * ATLAS_HEIGHT), 0)
    for index, atlas in enumerate(atlases):
        x = (index % columns) * ATLAS_WIDTH
        y = (index // columns) * ATLAS_HEIGHT
        image.alpha_composite(atlas.preview, (x, y))
    return image


def write_outputs(
    manifest_path: Path,
    font_path: Path,
    title_font_path: Path,
    output_dir: Path,
    header_path: Path,
    inject_path: Path | None,
) -> None:
    font_size, sections = load_manifest(manifest_path)
    atlases, commands = build_atlases(font_path, title_font_path, font_size, sections)
    output_dir.mkdir(parents=True, exist_ok=True)
    header_path.parent.mkdir(parents=True, exist_ok=True)
    desired_names = {atlas.name for atlas in atlases}
    _clean_generated_outputs(output_dir, desired_names)

    encoded_atlases = {}
    atlas_metadata = []
    for atlas in atlases:
        hgpt_data = encode_hgpt(atlas.image)
        encoded_atlases[atlas.filename] = hgpt_data
        (output_dir / atlas.filename).write_bytes(hgpt_data)
        atlas.preview.save(output_dir / f"{atlas.name}.png")
        metadata = {
            "atlas": atlas.filename,
            "first_row_id": atlas.first_row_id,
            "physical_rows": atlas.physical_rows,
            "division_count": atlas.division_count,
            "entries": [
                {
                    "text": entry.text,
                    "physical_row": entry.physical_row,
                    "row_id": entry.row_id,
                }
                for entry in atlas.entries
            ],
        }
        (output_dir / f"{atlas.name}.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        atlas_metadata.append(metadata)

    _combined_preview(atlases).save(output_dir / "staff_roll.png")
    (output_dir / "staff_roll.json").write_text(
        json.dumps(
            {
                "atlas_count": len(atlases),
                "physical_rows": sum(atlas.physical_rows for atlas in atlases),
                "division_count": sum(atlas.division_count for atlas in atlases),
                "command_count": len(commands),
                "atlases": atlas_metadata,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    header_path.write_text(render_header(commands, atlases), encoding="ascii")

    if inject_path is not None:
        if not inject_path.is_file():
            raise FileNotFoundError(f"staff archive not found: {inject_path}")
        inject_hgar(inject_path, encoded_atlases)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and inject translated staff roll")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "resources" / "staff_roll" / "credits.json",
    )
    parser.add_argument(
        "--font",
        type=Path,
        default=ROOT / "resources" / "assets" / "font" / "SourceHanSerifSC-Heavy.otf",
    )
    parser.add_argument(
        "--title-font",
        type=Path,
        default=ROOT / "resources" / "assets" / "font" / "SourceHanSansSC-Regular.otf",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "build" / "generated" / "staff_roll",
    )
    parser.add_argument(
        "--header",
        type=Path,
        default=ROOT / "plugin" / "src" / "runtime" / "patches" / "generated_staff_roll.h",
    )
    parser.add_argument("--inject-har", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    write_outputs(
        manifest_path=args.manifest,
        font_path=args.font,
        title_font_path=args.title_font,
        output_dir=args.output_dir,
        header_path=args.header,
        inject_path=args.inject_har,
    )


if __name__ == "__main__":
    main()
