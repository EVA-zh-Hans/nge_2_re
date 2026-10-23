import json
import tempfile
import unittest
from pathlib import Path

from scripts.check import build_parser, check_files
from scripts.paratranz.validation import (
    RULES,
    CheckContext,
    Term,
    parse_terms,
    validate_translation,
)


class TranslationRuleTests(unittest.TestCase):
    def test_runtime_markers_and_chinese_style_rules_are_shared(self):
        issues = validate_translation(
            "Hello $m\nΘ",
            '中文 text... ~ - "quoted" $m',
        )
        rules = {issue["rule"] for issue in issues}
        self.assertTrue(
            {
                "line_breaks",
                "ellipsis_style",
                "fullwidth_tilde",
                "dash_style",
                "cjk_latin_spacing",
                "corner_quotes",
                "eva_special_characters",
            }.issubset(rules)
        )
        line_break_issue = next(
            issue for issue in issues if issue["rule"] == "line_breaks"
        )
        self.assertEqual("warning", line_break_issue["severity"])

    def test_resource_specific_rules_only_run_for_matching_type(self):
        source = "A"
        translation = "中文内容很长"
        text_rules = {
            issue.rule for issue in RULES.check(CheckContext(source, translation, "text"))
        }
        eboot_rules = {
            issue.rule
            for issue in RULES.check(CheckContext(source, translation, "eboot"))
        }
        self.assertNotIn("eboot_length", text_rules)
        self.assertIn("eboot_length", eboot_rules)

    def test_unknown_resource_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown check type"):
            RULES.check(CheckContext("source", "translation", "unknown"))

    def test_selected_rules_are_the_only_rules_executed(self):
        context = CheckContext("Hello $m", "中文 text...", "text")
        issues = RULES.check(context, ("format_markers",))
        self.assertEqual(["format_markers"], [issue.rule for issue in issues])

        with self.assertRaisesRegex(ValueError, "Unknown validation rules"):
            RULES.check(context, ("not_a_rule",))

    def test_rule_cli_option_can_be_repeated(self):
        args = build_parser().parse_args(
            [
                "input.json",
                "report.json",
                "text",
                "--rule",
                "format_markers",
                "--rule",
                "encoding",
            ]
        )
        self.assertEqual(["format_markers", "encoding"], args.rules)

    def test_terms_include_variants_and_remove_duplicates(self):
        terms = parse_terms(
            {
                "results": [
                    {
                        "term": "Eva",
                        "variants": ["EVA", "Eva"],
                        "translation": ["EVA", "泛用人型决战兵器"],
                    }
                ]
            }
        )
        self.assertEqual(
            (
                Term("Eva", ("EVA", "泛用人型决战兵器")),
                Term("EVA", ("EVA", "泛用人型决战兵器")),
            ),
            terms,
        )

    def test_empty_translation_has_one_actionable_issue(self):
        self.assertEqual(
            [
                {
                    "rule": "empty_translation",
                    "severity": "error",
                    "message": "Translation is empty",
                }
            ],
            validate_translation("Hello", "", ()),
        )


class TranslationReportTests(unittest.TestCase):
    def test_batch_report_uses_shared_style_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            translation_file = root / "sample.json"
            translation_file.write_text(
                json.dumps(
                    [
                        {
                            "key": "bad-style",
                            "original": "Hello",
                            "translation": "中文 text...",
                        },
                        {
                            "key": "untranslated",
                            "original": "Later",
                            "translation": None,
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            issues, summary = check_files(
                [(translation_file, "text")], display_root=root
            )

        rules = {issue["rule"] for issue in issues}
        self.assertIn("cjk_latin_spacing", rules)
        self.assertIn("ellipsis_style", rules)
        self.assertEqual(2, summary["entries"])
        self.assertEqual(1, summary["checked"])
        self.assertEqual(1, summary["skipped"])
        self.assertTrue(all(issue["file"] == "sample.json" for issue in issues))

    def test_batch_report_contains_only_selected_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            translation_file = root / "sample.json"
            translation_file.write_text(
                json.dumps(
                    [
                        {
                            "original": "Hello $m",
                            "translation": "中文 text...",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            issues, summary = check_files(
                [(translation_file, "text")],
                display_root=root,
                rule_names=("format_markers",),
            )

        self.assertEqual(["format_markers"], [issue["rule"] for issue in issues])
        self.assertEqual(["format_markers"], summary["rules"])


if __name__ == "__main__":
    unittest.main()
