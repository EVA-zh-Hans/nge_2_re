"""Keep the custom character table and its two committed copies in sync.

plugin/scripts/gentable.py is the single source. app/utils/map.py (PC-side
encoding) and plugin/src/bin/gb2312.c (PSP-side lookup) are generated from it
and committed, so a drift between them would garble in-game text.
"""

import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from app.parser.tools.common import to_eva_sjis
from app.utils.map import CUSTOM_ENCODE_MAP

ROOT = Path(__file__).resolve().parents[2]
CUSTOM_FIRST, CUSTOM_LAST = 0xA600, 0xDDFF


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses looks the module up by name
    spec.loader.exec_module(module)
    return module


gentable = _load("gentable", "plugin/scripts/gentable.py")
bin2c = _load("bin2c", "plugin/scripts/bin2c.py")


class CharsetTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extra = gentable.load_extra_chars(gentable.DEFAULT_EXTRA_CHARS)
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        with (tmp / "map.json").open("w", encoding="utf-8") as f:
            utf16s = gentable.gb2312_to_custom(f, cls.extra)
        cls.generated_map = json.loads((tmp / "map.json").read_text("utf-8"))
        cls.table = b"".join(utf16s)
        (tmp / "t.bin").write_bytes(cls.table)
        bin2c.write_c_array(tmp / "t.bin", tmp / "gb2312.c", "GB2312_CUSTOM_BIN")
        cls.generated_c = (tmp / "gb2312.c").read_text("ascii")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_python_map_matches_generator(self):
        self.assertEqual(self.generated_map, CUSTOM_ENCODE_MAP)

    def test_c_table_matches_generator(self):
        committed = (ROOT / "plugin/src/bin/gb2312.c").read_text("ascii")
        self.assertEqual(self.generated_c, committed)

    def test_extra_chars_follow_gb2312_block_in_file_order(self):
        tail = [e["char"] for e in CUSTOM_ENCODE_MAP[-len(self.extra):]]
        self.assertEqual(self.extra, tail)
        for char in "啰瘆窸":
            self.assertIn(char, self.extra)

    def test_gb2312_block_codes_are_stable(self):
        # Anchors from the original table: appending must never shift these.
        by_char = {e["char"]: e["custom_code"] for e in CUSTOM_ENCODE_MAP}
        self.assertEqual("0xa601", by_char["　"])
        self.assertEqual("0xc371", by_char["齄"])

    def test_codes_are_unique_in_range_and_avoid_reserved_bytes(self):
        codes = [int(e["custom_code"], 16) for e in CUSTOM_ENCODE_MAP]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(CUSTOM_ENCODE_MAP), len({e["char"] for e in CUSTOM_ENCODE_MAP}))
        for code in codes:
            self.assertTrue(CUSTOM_FIRST <= code <= CUSTOM_LAST, hex(code))
            self.assertNotIn(code & 0xFF, (0x00, 0x25), hex(code))

    def test_round_trip_char_to_code_to_table_to_char(self):
        for entry in CUSTOM_ENCODE_MAP:
            code = int(entry["custom_code"], 16)
            index = code - CUSTOM_FIRST
            utf16 = self.table[index * 2:index * 2 + 2]
            self.assertEqual(entry["char"], utf16.decode("utf-16le"), entry)
            self.assertEqual(entry["utf16_hex"], utf16.hex(), entry)

    def test_encoder_uses_custom_code_only_when_shift_jis_cannot(self):
        # common.py normalizes these before encoding, so they never reach the map.
        normalized = {"—", "~", "～"}
        for entry in CUSTOM_ENCODE_MAP:
            char = entry["char"]
            if char in normalized:
                continue
            try:
                expected = char.encode("shift_jis")
            except UnicodeEncodeError:
                expected = int(entry["custom_code"], 16).to_bytes(2, "big")
            self.assertEqual(expected, to_eva_sjis(char), entry)

        # The characters this table was extended for.
        for char, code in (("啰", 0xC372), ("瘆", 0xC373), ("窸", 0xC374)):
            self.assertEqual(code.to_bytes(2, "big"), to_eva_sjis(char))

    def test_table_length_in_c_header_matches_data(self):
        match = re.search(r"GB2312_CUSTOM_BIN_len = (\d+);", self.generated_c)
        self.assertEqual(len(self.table), int(match.group(1)))

    def test_extra_chars_loader_rejects_bad_input(self):
        def load(text):
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "extra.txt"
                path.write_text(text, encoding="utf-8")
                return gentable.load_extra_chars(path)

        self.assertEqual(["啰"], load("# comment\n\n啰\n"))
        with self.assertRaises(ValueError):
            load("啰瘆\n")  # two characters on one line
        with self.assertRaises(ValueError):
            load("啰\n啰\n")  # duplicate
        with self.assertRaises(ValueError):
            load("あ\n")  # already Shift_JIS encodable
        with self.assertRaises(ValueError):
            gentable.gb2312_to_custom(io.StringIO(), ["中"])  # already in GB2312 block


if __name__ == "__main__":
    unittest.main()
