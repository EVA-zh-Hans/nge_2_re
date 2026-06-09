#!/usr/bin/env python3

import argparse
import io
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops


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


ATLAS_NAME = "staff21"
ATLAS_FILENAME = f"{ATLAS_NAME}.hpt"
ATLAS_WIDTH = 512
ATLAS_HEIGHT = 480
PHYSICAL_ROW_HEIGHT = 40
MAX_PHYSICAL_ROWS = ATLAS_HEIGHT // PHYSICAL_ROW_HEIGHT
LEFT_REGION = (0, 240)
RIGHT_REGION = (256, 496)
TITLE_REGION = (40, 472)
EXTRA_ROW_BASE = 214
ORIGINAL_COMMAND_COUNT = 196
ORIGINAL_INSERT_INDEX = 189
MAX_EXTRA_COMMANDS = 60

CTRL_PAGE_BREAK = 0x00001088

CTRL_TITLE = 0x00100208
CTRL_PAIR = 0x0000020A
CTRL_CENTERED = 0x00000208
CTRL_SECTION_GAP = 0x00000100

HGAR_ENCODED_IDENTIFIER = 0x90697026
HGAR_DECODED_IDENTIFIER = 111
@dataclass(frozen=True)
class CreditSection:
    title: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class RenderedEntry:
    text: str
    physical_row: int
    region_left: int
    region_right: int
    row_id: int


def load_manifest(path: Path) -> tuple[int, list[CreditSection]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    font_size = int(data.get("font_size", 24))
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


def text_bounds(font: ImageFont.FreeTypeFont, text: str) -> tuple[int, int, int, int]:
    return ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)


def _draw_text_with_glow(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    text: str,
    x: int,
    y: int,
) -> None:
    """Draw text with a glow effect by blurring and re-rendering the sharp core."""
    if not text.strip():
        return
    temp = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(temp)
    draw.text((x, y), text, font=font, fill=200)
    glow = temp.filter(ImageFilter.GaussianBlur(radius=3.0))
    draw_glow = ImageDraw.Draw(glow)
    draw_glow.text((x, y), text, font=font, fill=255)
    image.paste(ImageChops.lighter(image, glow))


def place_text(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    text: str,
    physical_row: int,
    region: tuple[int, int],
    row_id: int,
) -> tuple[RenderedEntry, tuple[int, int, int, int]]:
    left, right = region
    bbox = text_bounds(font, text)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    available = right - left
    if width > available:
        raise ValueError(f"text is too wide ({width}>{available}): {text}")

    x = left + (available - width) // 2 - bbox[0]
    row_top = physical_row * PHYSICAL_ROW_HEIGHT
    y = row_top + (PHYSICAL_ROW_HEIGHT - height) // 2 - bbox[1]
    _draw_text_with_glow(image, font, text, x, y)

    division_left = x + bbox[0]
    division = (division_left, row_top, width, PHYSICAL_ROW_HEIGHT)
    entry = RenderedEntry(text, physical_row, left, right, row_id)
    return entry, division


def build_atlas(
    font_path: Path,
    title_font_path: Path,
    font_size: int,
    sections: list[CreditSection],
) -> tuple[HgptImage, Image.Image, list[tuple[int, int, int]], list[RenderedEntry]]:
    font = ImageFont.truetype(str(font_path), font_size)
    title_font = ImageFont.truetype(str(title_font_path), font_size)
    alpha_image = Image.new("L", (ATLAS_WIDTH, ATLAS_HEIGHT), 0)
    divisions = [(0, 0, ATLAS_WIDTH, ATLAS_HEIGHT)]
    commands: list[tuple[int, int, int]] = []
    entries: list[RenderedEntry] = []
    physical_row = 0
    next_row_id = EXTRA_ROW_BASE

    commands.append((CTRL_PAGE_BREAK, -1, -1))

    for section_index, section in enumerate(sections):
        needed_rows = 1 + (len(section.names) + 1) // 2
        if physical_row + needed_rows > MAX_PHYSICAL_ROWS:
            raise ValueError(
                f"credits require {physical_row + needed_rows} physical rows; "
                f"{ATLAS_FILENAME} supports {MAX_PHYSICAL_ROWS}"
            )

        entry, division = place_text(
            alpha_image, title_font, section.title, physical_row, TITLE_REGION, next_row_id
        )
        entries.append(entry)
        divisions.append(division)
        commands.append((CTRL_TITLE, next_row_id, -1))
        next_row_id += 1
        physical_row += 1

        for name_index in range(0, len(section.names), 2):
            left_name = section.names[name_index]
            right_name = (
                section.names[name_index + 1]
                if name_index + 1 < len(section.names)
                else None
            )
            if right_name is None:
                entry, division = place_text(
                    alpha_image,
                    font,
                    left_name,
                    physical_row,
                    TITLE_REGION,
                    next_row_id,
                )
                entries.append(entry)
                divisions.append(division)
                commands.append((CTRL_CENTERED, next_row_id, -1))
                next_row_id += 1
            else:
                left_entry, left_division = place_text(
                    alpha_image,
                    font,
                    left_name,
                    physical_row,
                    LEFT_REGION,
                    next_row_id,
                )
                entries.append(left_entry)
                divisions.append(left_division)
                left_row_id = next_row_id
                next_row_id += 1

                right_entry, right_division = place_text(
                    alpha_image,
                    font,
                    right_name,
                    physical_row,
                    RIGHT_REGION,
                    next_row_id,
                )
                entries.append(right_entry)
                divisions.append(right_division)
                commands.append((CTRL_PAIR, left_row_id, next_row_id))
                next_row_id += 1
            physical_row += 1

        if section_index + 1 < len(sections):
            commands.append((CTRL_SECTION_GAP, -1, -1))

    if len(commands) > MAX_EXTRA_COMMANDS:
        raise ValueError(f"too many generated commands: {len(commands)}>{MAX_EXTRA_COMMANDS}")

    # Blue glow palette matching the original game's color scheme.
    # Core text: RGB(0, 19, 255) — deep blue with full alpha.
    # Glow halo: same blue hue, lower alpha creates the spread effect.
    CORE_R, CORE_G, CORE_B = 0, 19, 255

    alpha_values = alpha_image.tobytes()
    content = [0 if alpha == 0 else 1 + (alpha >> 1) for alpha in alpha_values]

    palette_colors = [(0, 0, 0, 0)]  # index 0: transparent
    # Indices 1-127: blue at increasing alpha (glow halo → core)
    for idx in range(1, 128):
        palette_colors.append((CORE_R, CORE_G, CORE_B, idx * 2))
    # Index 128: full-core blue at alpha 255
    palette_colors.append((CORE_R, CORE_G, CORE_B, 255))
    # Indices 129-255: gradually blend from core blue toward white
    for idx in range(129, 256):
        blend = (idx - 128) / 128.0
        r = int(CORE_R + (255 - CORE_R) * blend)
        g = int(CORE_G + (255 - CORE_G) * blend)
        b = int(CORE_B + (255 - CORE_B) * blend)
        palette_colors.append((r, g, b, 255))

    header = HgptHeader()
    header.has_extended_header = True
    image = HgptImage(
        header=header,
        display_info=DisplayInfo(ATLAS_WIDTH, ATLAS_HEIGHT),
        content=content,
        palette=Palette(palette_colors),
        division_info=DivisionInfo(ATLAS_NAME, divisions),
    )
    return image, alpha_image, commands, entries


def render_header(
    commands: list[tuple[int, int, int]],
    division_count: int,
) -> str:
    command_lines = "\n".join(
        f"    {{0x{ctrl:08X}u, {left}, {right}}}," for ctrl, left, right in commands
    )
    return f"""/* Generated by scripts/staff/generate_staff_roll.py. Do not edit. */
#pragma once

#define STAFF_ROLL_EXTRA_ROW_BASE {EXTRA_ROW_BASE}
#define STAFF_ROLL_EXTRA_ROW_COUNT {division_count}
#define STAFF_ROLL_EXTRA_COMMAND_COUNT {len(commands)}
#define STAFF_ROLL_ORIGINAL_COMMAND_COUNT {ORIGINAL_COMMAND_COUNT}
#define STAFF_ROLL_INSERT_INDEX {ORIGINAL_INSERT_INDEX}
#define STAFF_ROLL_EXTENDED_COMMAND_COUNT \\
    (STAFF_ROLL_ORIGINAL_COMMAND_COUNT + STAFF_ROLL_EXTRA_COMMAND_COUNT)
#define STAFF_ROLL_ATLAS_NAME "{ATLAS_NAME}"

static const StaffScrollCmd g_staffRollExtraCommands[STAFF_ROLL_EXTRA_COMMAND_COUNT] = {{
{command_lines}
}};
"""


def compress_hgar_entry(raw: bytes) -> bytes:
    compressed = zlib.compress(raw)
    return struct.pack("<I", len(raw)) + compressed[2:-4]


def normalized_name(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("ascii").rstrip(" \t\r\n\0")
    return value.rstrip(" \t\r\n\0")


def inject_hgar(har_path: Path, hgpt_data: bytes) -> None:
    archive = HGArchive(None, [])
    archive.open(str(har_path))
    if archive.version != 3:
        raise ValueError(f"{har_path} is HGAR v{archive.version}; expected v3")

    compressed = compress_hgar_entry(hgpt_data)
    target = None
    for item in archive.files:
        item.short_name = normalized_name(item.short_name)
        if normalized_name(item.long_name) == ATLAS_FILENAME:
            target = item

    if target is None:
        probe = HGArchiveFile(b"", "", 0, encoded_identifier=HGAR_ENCODED_IDENTIFIER)
        probe.decode_identifier(archive.identifier_limit)
        if probe.identifier != HGAR_DECODED_IDENTIFIER or not probe.is_compressed:
            raise ValueError("staff21 HGAR identifier constant is invalid")
        used_ids = {item.identifier for item in archive.files}
        if HGAR_DECODED_IDENTIFIER in used_ids:
            raise ValueError(
                f"HGAR identifier {HGAR_DECODED_IDENTIFIER} is already used in {har_path}"
            )
        target = HGArchiveFile(
            long_name=b"staff21.hpt\0",
            short_name=ATLAS_FILENAME,
            size=len(compressed),
            encoded_identifier=HGAR_ENCODED_IDENTIFIER,
            content=compressed,
        )
        target.identifier = HGAR_DECODED_IDENTIFIER
        target.is_compressed = True
        archive.files.append(target)
        archive.calculate_identifier_limit()
    else:
        target.content = compressed
        target.size = len(compressed)
        target.encoded_identifier |= 0x80000000
        target.is_compressed = True

    archive.save(str(har_path))

    verification = HGArchive(None, [])
    verification.open(str(har_path))
    matches = [
        item
        for item in verification.files
        if normalized_name(item.long_name) == ATLAS_FILENAME
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {ATLAS_FILENAME} after injection, found {len(matches)}"
        )


def write_outputs(
    manifest_path: Path,
    font_path: Path,
    title_font_path: Path,
    output_dir: Path,
    header_path: Path,
    inject_path: Path | None,
) -> None:
    font_size, sections = load_manifest(manifest_path)
    image, preview, commands, entries = build_atlas(font_path, title_font_path, font_size, sections)
    output_dir.mkdir(parents=True, exist_ok=True)
    header_path.parent.mkdir(parents=True, exist_ok=True)

    hgpt_buffer = io.BytesIO()
    HgptWriter(image).write(hgpt_buffer)
    hgpt_data = hgpt_buffer.getvalue()

    hgpt_path = output_dir / ATLAS_FILENAME
    hgpt_path.write_bytes(hgpt_data)
    preview.save(output_dir / f"{ATLAS_NAME}.png")
    header_path.write_text(
        render_header(commands, len(image.division_info.divisions) - 1),
        encoding="ascii",
    )
    metadata = {
        "atlas": ATLAS_FILENAME,
        "physical_rows": 1 + max(entry.physical_row for entry in entries),
        "division_count": len(image.division_info.divisions) - 1,
        "command_count": len(commands),
        "entries": [
            {
                "text": entry.text,
                "physical_row": entry.physical_row,
                "row_id": entry.row_id,
            }
            for entry in entries
        ],
    }
    (output_dir / "staff21.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if inject_path is not None:
        if not inject_path.is_file():
            raise FileNotFoundError(f"staff archive not found: {inject_path}")
        inject_hgar(inject_path, hgpt_data)


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
        default=ROOT / "plugin" / "assets" / "fonts" / "ChillRoundFBold.ttf",
    )
    parser.add_argument(
        "--title-font",
        type=Path,
        default=ROOT / "resources" / "assets" / "font" / "SourceHanSerifSC-Heavy.otf",
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
