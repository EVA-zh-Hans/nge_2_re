import unittest
from app.parser.tools.common import EvaEncodeError, to_eva_sjis


class TestCommonFunctions(unittest.TestCase):
    def test_to_eva_sjis_valid(self):
        input_text = "テスト"
        expected_output = input_text.encode("shift_jis")
        self.assertEqual(to_eva_sjis(input_text), expected_output)

    def test_to_eva_sjis_normalizes_em_dash(self):
        encoded = to_eva_sjis("前—后")

        self.assertEqual(encoded, "前―后".encode("shift_jis"))
        self.assertNotIn(b"\xa6\x0a", encoded)

    def test_to_eva_sjis_accepts_empty_bytes(self):
        self.assertEqual(to_eva_sjis(b""), b"")

    def test_to_eva_sjis_invalid_raises(self):
        with self.assertRaises(EvaEncodeError) as ctx:
            to_eva_sjis("前𠜎后")

        self.assertEqual(ctx.exception.char, "𠜎")
        self.assertIn("U+2070E", str(ctx.exception))
        self.assertIn("前𠜎后", str(ctx.exception))

    def test_to_eva_sjis_custom_map_character(self):
        # "这" is not Shift_JIS, so it must come from CUSTOM_ENCODE_MAP.
        encoded = to_eva_sjis("这")
        self.assertEqual(len(encoded), 2)
        self.assertNotEqual(encoded, b"?")


if __name__ == "__main__":
    unittest.main()
