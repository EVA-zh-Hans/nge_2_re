import io
import subprocess
import unittest
from unittest.mock import patch

from PIL import Image

from app.parser.tools.pillow_png import (
    quantize_png,
    read_png,
    write_indexed_png,
    write_rgba_png,
)


class PillowPngTests(unittest.TestCase):
    def test_indexed_png_preserves_indexes_and_per_entry_alpha(self):
        palette = [
            (255, 0, 0, 0),
            (0, 255, 0, 64),
            (0, 0, 255, 128),
            (255, 255, 255, 255),
        ] + [(0, 0, 0, 255)] * 12
        encoded = write_indexed_png(2, 2, bytes((0, 1, 2, 3)), palette)

        decoded = read_png(encoded)

        self.assertTrue(decoded.is_indexed)
        self.assertEqual(decoded.pixels, bytes((0, 1, 2, 3)))
        self.assertEqual(decoded.palette, tuple(palette))

    def test_indexed_png_supports_single_transparent_index(self):
        image = Image.frombytes("P", (2, 1), bytes((0, 1)))
        image.putpalette([255, 0, 0, 0, 255, 0] + [0] * 42)
        output = io.BytesIO()
        image.save(output, format="PNG", bits=4, transparency=1)

        decoded = read_png(output.getvalue())

        self.assertEqual(decoded.palette[0], (255, 0, 0, 255))
        self.assertEqual(decoded.palette[1], (0, 255, 0, 0))

    def test_rgba_png_round_trip(self):
        pixels = [
            (255, 0, 0, 255),
            (0, 255, 0, 128),
            (0, 0, 255, 64),
            (255, 255, 255, 0),
        ]

        decoded = read_png(write_rgba_png(2, 2, pixels))

        self.assertFalse(decoded.is_indexed)
        self.assertEqual(decoded.rgba_pixels(), pixels)

    def test_pngquant_uses_stdio_and_preserves_output(self):
        source = write_rgba_png(1, 1, [(1, 2, 3, 4)])
        expected = write_indexed_png(
            1,
            1,
            bytes((0,)),
            [(1, 2, 3, 4)] + [(0, 0, 0, 255)] * 15,
        )
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=expected,
            stderr=b"",
        )

        with patch(
            "app.parser.tools.pillow_png.subprocess.run",
            return_value=completed,
        ) as run:
            actual = quantize_png(source, 16)

        self.assertEqual(actual, expected)
        self.assertEqual(run.call_args.args[0][-1], "-")
        self.assertEqual(run.call_args.kwargs["input"], source)


if __name__ == "__main__":
    unittest.main()
