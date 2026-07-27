import io
import unittest

from app.database.dao.hgpt import HgptDao
from app.parser.tools import png
from app.parser.tools.hgp import (
    DisplayInfo,
    HgptHeader,
    HgptImage,
    HgptReader,
    HgptWriter,
    TileProcessor8800,
)


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
        width, height, rows, info = png.Reader(bytes=encoded).read()

        self.assertEqual((width, height), (2, 2))
        self.assertTrue(info["alpha"])
        self.assertEqual([list(row) for row in rows][0], [255, 0, 0, 255, 0, 255, 0, 128])


if __name__ == "__main__":
    unittest.main()
