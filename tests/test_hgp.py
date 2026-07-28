import io
import unittest
from types import SimpleNamespace

from app.database.dao.hgpt import HgptDao
from app.parser.tools.hgp import (
    DisplayInfo,
    HgptHeader,
    HgptImage,
    HgptReader,
    HgptWriter,
    Palette,
    TileProcessor8800,
)
from app.parser.tools.pillow_png import read_png


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

    def test_rgba_image_exports_to_png(self):
        display = DisplayInfo(width=2, height=2)
        pixels = [
            (255, 0, 0, 255),
            (0, 255, 0, 128),
            (0, 0, 255, 64),
            (255, 255, 255, 0),
        ]

        encoded = HgptDao._export_to_png(
            HgptImage(HgptHeader(), display, pixels)
        )
        decoded = read_png(encoded)

        self.assertEqual((decoded.width, decoded.height), (2, 2))
        self.assertIsNone(decoded.palette)
        self.assertEqual(list(decoded.pixels[:8]), [255, 0, 0, 255, 0, 255, 0, 128])

    def test_indexed_image_round_trips_through_database_png(self):
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
        exported = HgptDao._export_to_png(
            HgptImage(HgptHeader(), display, [0, 1, 2, 3], palette)
        )
        record = SimpleNamespace(
            png_translated=exported,
            png_image=exported,
            has_extended_header=False,
            unknown_two=0,
            unknown_three=0x13,
            width=2,
            height=2,
            division_name=None,
            divisions=None,
        )

        rebuilt = HgptDao._rebuild_from_png(record)
        restored = HgptReader(io.BytesIO(rebuilt)).read()

        self.assertEqual(restored.content, [0, 1, 2, 3])
        self.assertEqual(restored.palette.colors, palette.colors)


if __name__ == "__main__":
    unittest.main()
