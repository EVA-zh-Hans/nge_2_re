import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.parser.tools.evs import EvsWrapper, get_number_of_parameters
from app.parser.tools.hgar import HGArchive, HGArchiveFile
from app.parser.tools.text import TextArchive
from app.pipeline.catalog import CevOverride, TranslationCatalog
from app.pipeline.transforms import transform_evs, transform_text_archive


class StreamTransformTests(unittest.TestCase):
    def test_translation_catalog_uses_last_value_per_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            translations = root / "translations.json"
            translations.write_text(
                json.dumps(
                    [
                        {"key": "same", "translation": "first"},
                        {"key": "same", "translation": "last"},
                        {"key": "empty", "translation": ""},
                    ]
                ),
                encoding="utf-8",
            )
            cev_dir = root / "cev"
            cev_dir.mkdir()

            catalog = TranslationCatalog.load([translations], cev_dir)

        self.assertEqual(catalog.generic, {"same": "last"})
        self.assertEqual(len(catalog.generic_conflicts), 1)

    def test_text_transform_rebuilds_shared_strings(self):
        original = "original"
        key = hashlib.md5(original.encode()).hexdigest()
        catalog = TranslationCatalog(generic={key: "translated\\nline"}, cev={})
        archive = TextArchive()
        archive.entries = [(10, 0), (20, 0)]
        archive.strings = [(1, 2, original)]

        applied = transform_text_archive(archive, "other.bin", catalog)

        self.assertEqual(applied, 2)
        self.assertEqual(archive.entries, [(10, 0), (20, 0)])
        self.assertEqual(archive.strings, [(1, 2, "translated\nline")])

    def test_cev_override_takes_precedence_over_generic_translation(self):
        original = "original"
        key = hashlib.md5(original.encode()).hexdigest()
        catalog = TranslationCatalog(
            generic={key: "generic"},
            cev={
                ("cev0001.evs", 0): CevOverride(
                    original=original,
                    translation="scoped",
                    source="test.json",
                )
            },
        )
        wrapper = EvsWrapper()
        parameter_count = get_number_of_parameters(0x01)
        wrapper.add_entry(0x01, [0] * parameter_count, original)

        transformed, applied = transform_evs(
            wrapper.save_bytes(), "cev0001.evs", catalog
        )
        restored = EvsWrapper()
        restored.open_bytes(transformed)

        self.assertEqual(applied, 1)
        self.assertEqual(restored.entries[0][2], "scoped")
        self.assertEqual(catalog.used_cev, {("cev0001.evs", 0)})
        self.assertEqual(catalog.used_generic, set())


class HgarRoundTripTests(unittest.TestCase):
    def test_duplicate_entries_are_preserved_by_position(self):
        archive = HGArchive(
            1,
            [
                HGArchiveFile(
                    None,
                    b"same.bin",
                    5,
                    encoded_identifier=0x1234,
                    content=b"first",
                ),
                HGArchiveFile(
                    None,
                    b"same.bin",
                    6,
                    encoded_identifier=0x1234,
                    content=b"second",
                ),
                HGArchiveFile(
                    None,
                    b"f.",
                    4,
                    encoded_identifier=0x4321,
                    content=b"edge",
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.har"
            second_path = Path(directory) / "second.har"
            archive.save(str(first_path))
            restored = HGArchive(None, [])
            restored.open(str(first_path))
            restored.save(str(second_path))

            self.assertEqual(len(restored.files), 3)
            self.assertEqual(
                [entry.content for entry in restored.files],
                [b"first", b"second", b"edge"],
            )
            self.assertEqual(restored.files[2].short_name, b"f.")
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
