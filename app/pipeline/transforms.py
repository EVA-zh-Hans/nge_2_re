from __future__ import annotations

import io
import struct
import zlib

from app.parser.tools import hgp
from app.parser.tools.evs import EvsWrapper
from app.parser.tools.info_text import normalize_info_text, normalize_tuto_text
from app.parser.tools.pillow_png import quantize_png, read_png
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
    target_palette_size = len(image.palette) if image.palette else None
    raw = override.path.read_bytes()
    translated = read_png(raw)
    if target_palette_size is not None and not translated.is_indexed:
        translated = read_png(quantize_png(raw, target_palette_size))

    if (translated.width, translated.height) != (
        image.display_info.width,
        image.display_info.height,
    ):
        raise ValueError(
            f"translated image size mismatch for {override.path}: expected "
            f"{image.display_info.width}x{image.display_info.height}, got "
            f"{translated.width}x{translated.height}"
        )

    palette = None
    if target_palette_size is not None:
        if translated.palette is None:
            raise ValueError(f"failed to quantize translated image: {override.path}")
        colors = list(translated.palette)
        if 0 < len(colors) < 16:
            colors.extend([(0, 0, 0, 255)] * (16 - len(colors)))
        elif 16 < len(colors) < 256:
            colors.extend([(0, 0, 0, 255)] * (256 - len(colors)))
        palette = hgp.Palette(colors)
        content = list(translated.pixels)
    else:
        content = translated.rgba_pixels()

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
