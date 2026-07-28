from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Sequence, Union

from PIL import Image


RgbaColor = tuple[int, int, int, int]
PngSource = Union[bytes, bytearray, memoryview, str, Path, BinaryIO]


@dataclass(frozen=True)
class DecodedPng:
    width: int
    height: int
    pixels: bytes
    palette: tuple[RgbaColor, ...] | None = None

    @property
    def is_indexed(self) -> bool:
        return self.palette is not None

    def rgba_bytes(self) -> bytes:
        if self.palette is None:
            return self.pixels
        output = bytearray(len(self.pixels) * 4)
        for pixel_index, palette_index in enumerate(self.pixels):
            offset = pixel_index * 4
            output[offset:offset + 4] = bytes(self.palette[palette_index])
        return bytes(output)

    def rgba_pixels(self) -> list[RgbaColor]:
        rgba = self.rgba_bytes()
        return [
            (rgba[index], rgba[index + 1], rgba[index + 2], rgba[index + 3])
            for index in range(0, len(rgba), 4)
        ]


def read_png(source: PngSource) -> DecodedPng:
    stream = io.BytesIO(bytes(source)) if isinstance(source, (bytes, bytearray, memoryview)) else source
    with Image.open(stream) as image:
        if image.format != "PNG":
            raise ValueError(f"expected PNG image, got {image.format or 'unknown format'}")
        image.load()
        width, height = image.size
        if image.mode != "P":
            rgba = image.convert("RGBA")
            return DecodedPng(width, height, rgba.tobytes())

        indexes = image.tobytes()
        rgb = image.getpalette("RGB")
        if rgb is None:
            raise ValueError("indexed PNG does not expose a palette")
        palette_size = len(rgb) // 3
        alphas = [255] * palette_size
        transparency = image.info.get("transparency")
        if isinstance(transparency, bytes):
            alpha_count = min(len(transparency), palette_size)
            alphas[:alpha_count] = transparency[:alpha_count]
        elif isinstance(transparency, int):
            if 0 <= transparency < palette_size:
                alphas[transparency] = 0
        elif transparency is not None:
            raise ValueError(f"unsupported indexed PNG transparency: {transparency!r}")

        palette = tuple(
            (
                rgb[index * 3],
                rgb[index * 3 + 1],
                rgb[index * 3 + 2],
                alphas[index],
            )
            for index in range(palette_size)
        )
        return DecodedPng(width, height, indexes, palette)


def write_indexed_png(
    width: int,
    height: int,
    indexes: bytes | bytearray | memoryview | Iterable[int],
    palette: Sequence[Sequence[int]],
    *,
    compression: int = 1,
) -> bytes:
    pixel_bytes = bytes(indexes)
    _validate_pixel_length(width, height, pixel_bytes, 1)
    colors = [_rgba_color(color) for color in palette]
    if not colors or len(colors) > 256:
        raise ValueError(f"indexed PNG palette must contain 1-256 colors, got {len(colors)}")
    if pixel_bytes and max(pixel_bytes) >= len(colors):
        raise ValueError("indexed PNG contains a pixel outside its palette")

    bitdepth = _palette_bitdepth(len(colors))
    padded_size = 1 << bitdepth
    padded = colors + [(0, 0, 0, 255)] * (padded_size - len(colors))
    image = Image.frombytes("P", (width, height), pixel_bytes)
    image.putpalette([channel for color in padded for channel in color[:3]])
    output = io.BytesIO()
    save_args: dict[str, object] = {
        "format": "PNG",
        "compress_level": compression,
        "bits": bitdepth,
    }
    alphas = bytes(color[3] for color in padded)
    if any(alpha != 255 for alpha in alphas):
        save_args["transparency"] = alphas
    image.save(output, **save_args)
    return output.getvalue()


def write_rgba_png(
    width: int,
    height: int,
    pixels: bytes | bytearray | memoryview | Iterable[Sequence[int]],
    *,
    compression: int = 1,
) -> bytes:
    pixel_bytes = _flatten_pixels(pixels, 4)
    _validate_pixel_length(width, height, pixel_bytes, 4)
    return _write_direct_png("RGBA", width, height, pixel_bytes, compression)


def write_rgb_png(
    width: int,
    height: int,
    pixels: bytes | bytearray | memoryview | Iterable[Sequence[int]],
    *,
    compression: int = 1,
) -> bytes:
    pixel_bytes = _flatten_pixels(pixels, 3)
    _validate_pixel_length(width, height, pixel_bytes, 3)
    return _write_direct_png("RGB", width, height, pixel_bytes, compression)


def quantize_png(
    raw: bytes,
    palette_size: int,
    *,
    timeout: float = 30,
) -> bytes:
    if palette_size not in (16, 256):
        raise ValueError(f"unsupported target palette size: {palette_size}")
    try:
        result = subprocess.run(
            ["pngquant", "--speed", "1", str(palette_size), "-"],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return quantize_png_fallback(raw, palette_size)
    if result.returncode != 0 or not result.stdout:
        return quantize_png_fallback(raw, palette_size)
    return result.stdout


def quantize_png_fallback(raw: bytes, palette_size: int) -> bytes:
    decoded = read_png(raw)
    pixels = decoded.rgba_pixels()
    colors: list[RgbaColor] = []
    color_indexes: dict[RgbaColor, int] = {}
    for pixel in pixels:
        if pixel not in color_indexes and len(colors) < palette_size:
            color_indexes[pixel] = len(colors)
            colors.append(pixel)
    indexes = bytes(color_indexes.get(pixel, 0) for pixel in pixels)
    colors.extend([(0, 0, 0, 255)] * (palette_size - len(colors)))
    return write_indexed_png(decoded.width, decoded.height, indexes, colors)


def convert_indexed_to_rgba_png(raw: bytes) -> bytes:
    decoded = read_png(raw)
    if not decoded.is_indexed:
        return raw
    return write_rgba_png(decoded.width, decoded.height, decoded.rgba_bytes())


def _write_direct_png(
    mode: str,
    width: int,
    height: int,
    pixels: bytes,
    compression: int,
) -> bytes:
    image = Image.frombytes(mode, (width, height), pixels)
    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=compression)
    return output.getvalue()


def _flatten_pixels(
    pixels: bytes | bytearray | memoryview | Iterable[Sequence[int]],
    channels: int,
) -> bytes:
    if isinstance(pixels, (bytes, bytearray, memoryview)):
        return bytes(pixels)
    flattened = bytearray()
    for pixel in pixels:
        if len(pixel) != channels:
            raise ValueError(f"expected {channels} channels, got {len(pixel)}")
        flattened.extend(pixel)
    return bytes(flattened)


def _rgba_color(color: Sequence[int]) -> RgbaColor:
    if len(color) == 3:
        return color[0], color[1], color[2], 255
    if len(color) == 4:
        return color[0], color[1], color[2], color[3]
    raise ValueError(f"palette colors must have 3 or 4 channels, got {len(color)}")


def _palette_bitdepth(palette_size: int) -> int:
    if palette_size <= 2:
        return 1
    if palette_size <= 4:
        return 2
    if palette_size <= 16:
        return 4
    return 8


def _validate_pixel_length(
    width: int,
    height: int,
    pixels: bytes,
    channels: int,
) -> None:
    expected = width * height * channels
    if len(pixels) != expected:
        raise ValueError(f"expected {expected} pixel bytes, got {len(pixels)}")
