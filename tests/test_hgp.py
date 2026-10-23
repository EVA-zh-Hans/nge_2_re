import io
import tempfile
import unittest
from pathlib import Path

from app.parser.tools.hgp import (
    DisplayInfo,
    HgptHeader,
    HgptImage,
    HgptReader,
    HgptWriter,
    Palette,
    TileProcessor8800,
)
from app.parser.tools.pillow_png import write_indexed_png
from app.pipeline.catalog import ImageOverride
from app.pipeline.transforms import rebuild_hgpt


class RgbaTileProcessorTests(unittest.TestCase):
    def test_rgba_tile_round_trip_preserves_channels_and_crops_padding(self):
        display = DisplayInfo(width=5, height=9)
        processor = TileProcessor8800(display)
        storage_width, storage_height = processor.get_storage_dims()
        pixels = [
            (index, index + 1, index + 2, 255)
            for index in range(display.width * display.height)
        ]

        tiled = processor.tile(pixels, storage_width, storage_height)
        restored = processor.untile(tiled, storage_width, storage_height)

        self.assertEqual(restored, pixels)

    def test_rgba_hgpt_reader_writer_round_trip(self):
        display = DisplayInfo(width=5, height=9)
        pixels = [
            (
                index % 256,
                (index * 2) % 256,
                (index * 4) % 256,
                255 if index % 3 == 0 else 128,
            )
            for index in range(display.width * display.height)
        ]
        image = HgptImage(HgptHeader(), display, pixels)
        encoded = io.BytesIO()

        HgptWriter(image).write(encoded)
        encoded.seek(0)
        decoded = HgptReader(encoded).read()

        self.assertEqual(decoded.display_info.width, display.width)
        self.assertEqual(decoded.display_info.height, display.height)
        self.assertEqual(decoded.palette, None)
        self.assertEqual(decoded.content, pixels)

    def test_indexed_image_round_trips_through_image_override(self):
        display = DisplayInfo(width=2, height=2)
        palette = Palette(
            [
                (255, 0, 0, 0),
                (0, 255, 0, 64),
                (0, 0, 255, 128),
                (255, 255, 255, 255),
            ]
            + [(0, 0, 0, 255)] * 12
        )
        original = io.BytesIO()
        HgptWriter(
            HgptImage(HgptHeader(), display, [0, 1, 2, 3], palette)
        ).write(original)
        translated_png = write_indexed_png(
            2, 2, bytes((0, 1, 2, 3)), palette.colors
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "translated.png"
            path.write_bytes(translated_png)
            rebuilt = rebuild_hgpt(
                original.getvalue(),
                ImageOverride(prefix="unused", path=path, digest="unused"),
            )
        restored = HgptReader(io.BytesIO(rebuilt)).read()

        self.assertEqual(restored.content, [0, 1, 2, 3])
        self.assertEqual(restored.palette.colors, palette.colors)


if __name__ == "__main__":
    unittest.main()
