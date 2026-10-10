import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock

import requests

from scripts.paratranz import retranslate


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class RetranslateTests(unittest.TestCase):
    def test_pagination_for_files_strings_history_and_terms(self):
        session = Mock()
        session.headers = {}
        session.get.side_effect = [
            FakeResponse({"results": [{"id": 1}], "pageCount": 2}),
            FakeResponse({"results": [{"id": 2}], "pageCount": 2}),
            FakeResponse({"results": [{"id": 3}], "pageCount": 1}),
            FakeResponse({"results": [{"id": 4, "tid": 4}], "pageCount": 1}),
            FakeResponse({"results": [{"id": 5, "term": "Eva", "translation": "EVA"}], "pageCount": 1}),
        ]
        api = retranslate.ParaTranzClient("secret", session=session)
        self.assertEqual([1, 2], [x["id"] for x in api.fetch_files()])
        self.assertEqual([3], [x["id"] for x in api.fetch_strings()])
        self.assertEqual([4], [x["id"] for x in api.fetch_history()])
        self.assertEqual([5], [x["id"] for x in api.fetch_terms()])
        self.assertEqual(5, session.get.call_count)

    def test_string_file_page_filter_and_short_page(self):
        session = Mock()
        session.headers = {}
        session.get.side_effect = [FakeResponse([{"id": 1, "fileId": 12}])]
        api = retranslate.ParaTranzClient("secret", session=session)
        self.assertEqual(1, len(api.fetch_strings(12)))
        self.assertEqual(12, session.get.call_args.kwargs["params"]["file"])

    def test_imported_translation_history_is_retranslatable_but_manual_edits_are_not(self):
        history = [
            {"id": 1, "tid": 7, "field": "stage"},
            {"id": 2, "tid": 7, "field": "context"},
            {"id": 3, "tid": 7, "field": "translation", "operation": "import"},
            {"id": 4, "tid": 7, "field": "main_void", "operation": "edit"},
            {"id": 5, "tid": 8, "field": "translation", "operation": "translate"},
        ]
        self.assertEqual(4, len(retranslate.history_for_string(history, 7)))
        self.assertEqual(64, len(retranslate.history_fingerprint(history, 7)))
        self.assertTrue(retranslate.has_translation_import(history, 7))
        self.assertEqual([], retranslate.manual_translation_history(history, 7))
        self.assertEqual(1, len(retranslate.manual_translation_history(history, 8)))

    def test_history_without_string_id_is_retained_for_safe_skip(self):
        session = Mock()
        session.headers = {}
        session.get.return_value = FakeResponse([{"id": 1, "field": "translation"}])
        self.assertEqual([{"id": 1, "field": "translation"}], retranslate.ParaTranzClient("secret", session=session).fetch_history())

    def test_chat_endpoint_resolution(self):
        cases = {
            "https://host.example": "https://host.example/v1/chat/completions",
            "https://host.example/v1/": "https://host.example/v1/chat/completions",
            "https://host.example/v1/chat/completions": "https://host.example/v1/chat/completions",
        }
        for source, expected in cases.items():
            self.assertEqual(expected, retranslate.chat_completions_url(source))

    def test_completion_requires_exact_ids_nonempty_values_and_json(self):
        self.assertEqual(
            {1: "中文"},
            retranslate._decode_completion(
                {"choices": [{"message": {"content": '{"results":[{"id":1,"translation":"中文"}]}'}}]}, {1}
            ),
        )
        invalid_contents = [
            "not json",
            '[{"id":1,"translation":""}]',
            '[{"id":1,"translation":"A"},{"id":1,"translation":"B"}]',
            '[{"id":2,"translation":"A"}]',
            '[{"id":1,"translation":"A"},{"id":3,"translation":"B"}]',
        ]
        for content in invalid_contents:
            with self.subTest(content=content), self.assertRaises(ValueError):
                retranslate._decode_completion({"choices": [{"message": {"content": content}}]}, {1})

    def test_chat_request_contains_original_context_and_terms_without_old_translation(self):
        session = Mock()
        session.post.return_value = FakeResponse({"choices": [{"message": {"content": '[{"id":1,"translation":"你好"}]'}}]})
        result = retranslate.translate_batch(
            [{"id": 1, "original": "Hello", "context": "Greeting", "terms": [{"source": "Hello", "translations": ["你好"]}]}],
            "llm-secret",
            "model",
            "https://provider/v1",
            session=session,
            retries=1,
        )
        self.assertEqual({1: "你好"}, result)
        body = session.post.call_args.kwargs["json"]
        self.assertIn("Hello", body["messages"][1]["content"])
        self.assertIn("Greeting", body["messages"][1]["content"])
        self.assertNotIn("old_translation", json.dumps(body))
        self.assertEqual({"type": "json_object"}, body["response_format"])
        self.assertEqual("Bearer llm-secret", session.post.call_args.kwargs["headers"]["Authorization"])

    def test_format_markers_and_newlines_are_checked(self):
        source = "A $m $n %s ▽\nNext"
        matching = "中 $m $n %s ▽\n下"
        broken = "中 $m %s ▽ 下"
        self.assertEqual([], retranslate.validate_translation(source, matching, ()))
        self.assertTrue(any(issue["rule"] == "format_markers" for issue in retranslate.validate_translation(source, broken, ())))
        self.assertTrue(any(issue["rule"] == "line_breaks" for issue in retranslate.validate_translation(source, matching.replace("\n", " "), ())))

    def test_chinese_punctuation_spacing_and_eva_glyph_rules(self):
        source = "EVA Θ Α Τ Ν Σ Ｓ。\u200b"
        matching = "EVAΘΑΤΝΣＳ。\u200b"
        self.assertEqual([], retranslate.validate_translation(source, matching, ()))
        invalid = retranslate.validate_translation("English", '中文 text... ~ - "quoted"', ())
        rules = {issue["rule"] for issue in invalid}
        self.assertTrue({"cjk_latin_spacing", "ellipsis_style", "fullwidth_tilde", "dash_style", "corner_quotes"}.issubset(rules))
        self.assertIn("eva_special_characters", {issue["rule"] for issue in retranslate.validate_translation("ΘΑ", "JA", ())})
        self.assertIn("invisible_characters", {issue["rule"] for issue in retranslate.validate_translation("A\u200b", "A", ())})
        self.assertIn("layout_spaces", {issue["rule"] for issue in retranslate.validate_translation("A  B", "A B", ())})
        self.assertIn("ellipsis_style", {issue["rule"] for issue in retranslate.validate_translation("…", "…", ())})

    def test_apply_detects_remote_changes_and_put_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "report.json"
            item = {
                "id": 4,
                "original": "hello",
                "old_translation": "旧译文",
                "stage": 1,
                "history_fingerprint": retranslate.history_fingerprint([], 4),
                "translation": "你好",
                "status": "ready",
            }
            report_path.write_text(json.dumps({"file_id": 2, "entries": [item]}), encoding="utf-8")
            client = Mock()
            client.fetch_current.return_value = ([{"id": 4, "original": "hello", "translation": "人工译文", "stage": 1}], [])
            stats = retranslate.apply_report(report_path, client)
            self.assertEqual({"applied": 0, "conflict": 1, "skipped": 0}, stats)
            client.update_string.assert_not_called()
            self.assertEqual("conflict", json.loads(report_path.read_text(encoding="utf-8"))["entries"][0]["status"])

            item["status"] = "ready"
            item["old_translation"] = "旧译文"
            client.fetch_current.return_value = ([{"id": 4, "original": "hello", "translation": "旧译文", "stage": 1}], [])
            report_path.write_text(json.dumps({"file_id": 2, "entries": [item]}), encoding="utf-8")
            self.assertEqual(1, retranslate.apply_report(report_path, client)["applied"])
            client.update_string.assert_called_once_with(4, "你好")

    def test_apply_detects_original_stage_and_history_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "report.json"
            item = {
                "id": 4,
                "original": "hello",
                "old_translation": "旧译文",
                "stage": 1,
                "history_fingerprint": retranslate.history_fingerprint([], 4),
                "translation": "你好",
                "status": "ready",
            }
            cases = [
                ({"original": "changed", "translation": "旧译文", "stage": 1}, []),
                ({"original": "hello", "translation": "旧译文", "stage": 2}, []),
                ({"original": "hello", "translation": "旧译文", "stage": 1}, [{"tid": 4, "field": "translation", "operation": "translate"}]),
            ]
            for string_state, history in cases:
                row = dict(item)
                report_path.write_text(json.dumps({"file_id": 2, "entries": [row]}), encoding="utf-8")
                client = Mock()
                client.fetch_current.return_value = ([{"id": 4, **string_state}], history)
                self.assertEqual(1, retranslate.apply_report(report_path, client)["conflict"])
                client.update_string.assert_not_called()

    def test_update_puts_translation_and_stage_one(self):
        session = Mock()
        session.headers = {}
        session.put.return_value = FakeResponse({"id": 4})
        api = retranslate.ParaTranzClient("secret", session=session)
        api.update_string(4, "你好")
        self.assertEqual({"translation": "你好", "stage": 1}, session.put.call_args.kwargs["json"])

    def test_apply_allows_imported_translation_change_and_other_field_history(self):
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "report.json"
            item = {
                "id": 4,
                "original": "hello",
                "old_translation": "旧译文",
                "stage": 1,
                "manual_translation_fingerprint": retranslate.manual_translation_fingerprint([], 4),
                "translation": "重新翻译",
                "status": "ready",
            }
            report_path.write_text(json.dumps({"file_id": 2, "entries": [item]}), encoding="utf-8")
            client = Mock()
            client.fetch_current.return_value = (
                [{"id": 4, "original": "hello", "translation": "已导入的译文", "stage": 1}],
                [
                    {"tid": 4, "field": "translation", "operation": "import"},
                    {"tid": 4, "field": "main_void", "operation": "edit"},
                ],
            )
            self.assertEqual({"applied": 1, "conflict": 0, "skipped": 0}, retranslate.apply_report(report_path, client))
            client.update_string.assert_called_once_with(4, "重新翻译")

    def test_preview_uses_jsonl_resume_and_does_not_put(self):
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp)
            original_hash = retranslate.hashlib.sha256("Hello".encode("utf-8")).hexdigest()
            (run_dir / "results.jsonl").write_text(json.dumps({"id": 9, "original_sha256": original_hash, "model": "test", "translation": "你好"}, ensure_ascii=False) + "\n", encoding="utf-8")
            client = Mock()
            client.fetch_files.return_value = [{"id": 3, "name": "game/imtext.json"}]
            client.fetch_strings.return_value = [{"id": 9, "fileId": 3, "original": "Hello", "translation": "", "stage": 1, "context": "Greeting"}]
            client.fetch_history.return_value = [{"tid": 9, "field": "translation", "operation": "import"}]
            client.fetch_terms.return_value = []
            args = Namespace(file="game/imtext.json", file_id=None, run_dir=run_dir, batch_size=5, retries=2, oai_api_key="llm-secret", model="test", oai_base_url="https://host/v1")
            with unittest.mock.patch.object(retranslate, "translate_batch") as translate:
                report_path = retranslate.create_preview(args, client)
            translate.assert_not_called()
            client.update_string.assert_not_called()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("ready", report["entries"][0]["status"])
            self.assertNotIn("secret", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
