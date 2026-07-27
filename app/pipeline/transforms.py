from __future__ import annotations

import io
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from app.parser.tools import hgp, png
from app.parser.tools.evs import EvsWrapper
from app.parser.tools.info_text import normalize_info_text, normalize_tuto_text
from app.parser.tools.text import TextArchive

from .catalog import ImageOverride, TranslationCatalog


def decompress_hgar_entry(content: bytes) -> bytes:
    if len(content) < 4:
        raise ValueError("compressed HGAR entry is shorter than its size header")
    expected_size = struct.unpack("<I", content[:4])[0]
    decompressed = zlib.decompress(content[4:], -15)
    if len(decompressed) != expected_size:
        raise ValueError(
            f"compressed HGAR size mismatch: expected {expected_size}, got {len(decompressed)}"
        )
    return decompressed


def compress_hgar_entry(content: bytes) -> bytes:
    compressed = zlib.compress(content)
    return struct.pack("<I", len(content)) + compressed[2:-4]


def transform_text_archive(
    archive: TextArchive,
    filename: str,
    catalog: TranslationCatalog,
) -> int:
    normalizer = None
    lower_filename = filename.lower()
    if lower_filename == "f2info.bin":
        normalizer = normalize_info_text
    elif lower_filename == "f2tuto.bin":
        normalizer = normalize_tuto_text

    rebuilt_strings = []
    rebuilt_entries = []
    string_indexes: dict[tuple[str, int | None, int | None], int] = {}
    applied = 0

    for entry_index, (entry_unknown, original_string_index) in enumerate(archive.entries):
        unknown_first, unknown_second, value = archive.strings[original_string_index]
        original = value or ""
        translation = catalog.generic_for(original)
        translated = translation.replace("\\n", "\n") if translation else original
        if translation and normalizer:
            translated, _ = normalizer(
                translated, entry_label=f"{filename} entry {entry_index}"
            )
        if translation:
            applied += 1

        key = (translated, unknown_first, unknown_second)
        string_index = string_indexes.get(key)
        if string_index is None:
            string_index = len(rebuilt_strings)
            string_indexes[key] = string_index
            rebuilt_strings.append((unknown_first, unknown_second, translated))
        rebuilt_entries.append((entry_unknown, string_index))

    if applied:
        archive.strings = rebuilt_strings
        archive.entries = rebuilt_entries
    return applied


def transform_evs(
    content: bytes,
    evs_name: str,
    catalog: TranslationCatalog,
) -> tuple[bytes, int]:
    wrapper = EvsWrapper()
    wrapper.open_bytes(content)
    entries = []
    applied = 0
    for entry_index, (entry_type, parameters, original) in enumerate(wrapper.entries):
        translated = None
        if original is not None:
            translated = catalog.cev_for(evs_name, entry_index, original)
            if translated is None and original:
                translated = catalog.generic_for(original)
        if translated:
            entries.append((entry_type, parameters, translated))
            applied += 1
        else:
            entries.append((entry_type, parameters, original))
    if not applied:
        return content, 0
    wrapper.entries = entries
    return wrapper.save_bytes(), applied


def rebuild_hgpt(original: bytes, override: ImageOverride) -> bytes:
    image = hgp.HgptReader(io.BytesIO(original)).read()
    translated_png = _normalize_png_format(
        override.path.read_bytes(),
        target_palette_size=len(image.palette) if image.palette else None,
    )
    reader = png.Reader(bytes=translated_png)
    width, height, rows, info = reader.read()
    if (width, height) != (image.display_info.width, image.display_info.height):
        raise ValueError(
            f"translated image size mismatch for {override.path}: expected "
            f"{image.display_info.width}x{image.display_info.height}, got {width}x{height}"
        )

    palette = None
    content = []
    if "palette" in info:
        colors = [
            (color[0], color[1], color[2], color[3] if len(color) > 3 else 255)
            for color in info["palette"]
        ]
        if 0 < len(colors) < 16:
            colors.extend([(0, 0, 0, 255)] * (16 - len(colors)))
        elif 16 < len(colors) < 256:
            colors.extend([(0, 0, 0, 255)] * (256 - len(colors)))
        palette = hgp.Palette(colors)
        content = [pixel for row in rows for pixel in row]
    else:
        pixel_depth = 4 if info.get("alpha") else 3
        if info.get("greyscale"):
            raise ValueError(f"translated image must be RGB, RGBA, or indexed: {override.path}")
        for row in rows:
            for index in range(0, len(row), pixel_depth):
                content.append(
                    (
                        row[index],
                        row[index + 1],
                        row[index + 2],
                        row[index + 3] if pixel_depth == 4 else 255,
                    )
                )

    rebuilt = hgp.HgptImage(
        header=image.header,
        display_info=image.display_info,
        content=content,
        palette=palette,
        division_info=image.division_info,
    )
    output = io.BytesIO()
    hgp.HgptWriter(rebuilt).write(output)
    return output.getvalue()


def _normalize_png_format(raw: bytes, target_palette_size: int | None) -> bytes:
    reader = png.Reader(bytes=raw)
    _, _, _, info = reader.read()
    is_palette = "palette" in info
    if target_palette_size is not None and not is_palette:
        return _convert_rgba_to_palette(raw, target_palette_size)
    if target_palette_size is None and is_palette:
        return _convert_palette_to_rgba(raw)
    return raw


def _convert_rgba_to_palette(raw: bytes, palette_size: int) -> bytes:
    with tempfile.TemporaryDirectory(prefix="nge2-pngquant-") as directory:
        input_path = Path(directory) / "input.png"
        output_path = Path(directory) / "output.png"
        input_path.write_bytes(raw)
        try:
            subprocess.run(
                [
                    "pngquant",
                    "--force",
                    "--speed",
                    "1",
                    str(palette_size),
                    str(input_path),
                    "--output",
                    str(output_path),
                    "-v",
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        if output_path.is_file():
            return output_path.read_bytes()
    return _convert_rgba_to_palette_fallback(raw, palette_size)


def _convert_rgba_to_palette_fallback(raw: bytes, palette_size: int) -> bytes:
    reader = png.Reader(bytes=raw)
    width, height, rows, info = reader.read()
    depth = 4 if info.get("alpha") else 3
    pixels = []
    for row in rows:
        for index in range(0, len(row), depth):
            pixels.append(
                (
                    row[index],
                    row[index + 1],
                    row[index + 2],
                    row[index + 3] if depth == 4 else 255,
                )
            )
    colors = []
    color_indexes = {}
    for pixel in pixels:
        if pixel not in color_indexes and len(colors) < palette_size:
            color_indexes[pixel] = len(colors)
            colors.append(pixel)
    colors.extend([(0, 0, 0, 255)] * (palette_size - len(colors)))
    indexes = [color_indexes.get(pixel, 0) for pixel in pixels]
    output = io.BytesIO()
    writer = png.Writer(width, height, palette=colors, bitdepth=8)
    writer.write(
        output,
        [indexes[index:index + width] for index in range(0, len(indexes), width)],
    )
    return output.getvalue()


def _convert_palette_to_rgba(raw: bytes) -> bytes:
    reader = png.Reader(bytes=raw)
    width, height, rows, info = reader.read()
    palette = info["palette"]
    rgba_rows = []
    for row in rows:
        rgba_row = []
        for index in row:
            color = palette[index]
            rgba_row.extend((*color[:3], color[3] if len(color) > 3 else 255))
        rgba_rows.append(rgba_row)
    output = io.BytesIO()
    png.Writer(width, height, greyscale=False, alpha=True).write(output, rgba_rows)
    return output.getvalue()
