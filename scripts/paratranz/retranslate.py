"""Preview and safely apply AI retranslations for a ParaTranz project file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import requests
from dotenv import load_dotenv

from scripts.check import CheckContext, RULES, Term

PROJECT_ID = 10882
PARATRANZ_BASE_URL = "https://paratranz.cn/api"
DEFAULT_PAGE_SIZE = 1000
DEFAULT_BATCH_SIZE = 5
EVA_SPECIAL_CHARACTERS = "ΘΑΤΝΣＳ"
LAYOUT_SPACE_RE = re.compile(r" {2,}")
CJK_LATIN_SPACE_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff] [A-Za-z0-9]|[A-Za-z0-9] [\u3400-\u9fff\uf900-\ufaff]")
ELLIPSIS_PUNCTUATION_RE = re.compile(r"(?:……|…)[，。,.]|[，。,.](?:……|…)")


def _result_list(payload: Any, endpoint: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        values = payload.get("results")
        if values is None:
            values = payload.get("data")
    else:
        values = None
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        raise ValueError(f"Invalid {endpoint} response shape")
    return values


class ParaTranzClient:
    def __init__(self, token: str, base_url: str = PARATRANZ_BASE_URL, session=None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": token, "Accept": "application/json"})

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            f"{self.base_url}{path}", params=params, timeout=30
        )
        response.raise_for_status()
        try:
            return response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise ValueError("ParaTranz returned invalid JSON") from exc

    def _fetch_pages(self, path: str, page_size: int = DEFAULT_PAGE_SIZE) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._get_json(path, {"page": page, "pageSize": page_size})
            batch = _result_list(payload, path)
            if not batch:
                break
            values.extend(batch)
            if isinstance(payload, dict) and payload.get("pageCount") is not None:
                if page >= int(payload["pageCount"]):
                    break
            elif len(batch) < page_size:
                break
            page += 1
            if page > 10000:
                raise RuntimeError(f"Pagination exceeded 10000 pages for {path}")
        return values

    def fetch_files(self) -> list[dict[str, Any]]:
        return self._fetch_pages(f"/projects/{PROJECT_ID}/files")

    def fetch_strings(self, file_id: int | None = None) -> list[dict[str, Any]]:
        path = f"/projects/{PROJECT_ID}/strings"
        return self._fetch_pages(path) if file_id is None else self._fetch_string_pages(file_id)

    def _fetch_string_pages(self, file_id: int) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        page = 1
        path = f"/projects/{PROJECT_ID}/strings"
        while True:
            payload = self._get_json(path, {"file": file_id, "page": page, "pageSize": DEFAULT_PAGE_SIZE})
            batch = _result_list(payload, path)
            if not batch:
                break
            values.extend(batch)
            if isinstance(payload, dict) and payload.get("pageCount") is not None:
                if page >= int(payload["pageCount"]):
                    break
            elif len(batch) < DEFAULT_PAGE_SIZE:
                break
            page += 1
        return values

    def fetch_history(self) -> list[dict[str, Any]]:
        return self._fetch_pages(f"/projects/{PROJECT_ID}/history")

    def fetch_terms(self) -> list[dict[str, Any]]:
        return self._fetch_pages(f"/projects/{PROJECT_ID}/terms")

    def fetch_current(self, file_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        strings = self.fetch_strings(file_id)
        history = self.fetch_history()
        return strings, history

    def update_string(self, string_id: int, translation: str) -> None:
        response = self.session.put(
            f"{self.base_url}/projects/{PROJECT_ID}/strings/{string_id}",
            json={"translation": translation, "stage": 1},
            timeout=30,
        )
        response.raise_for_status()

    def import_translation_subset(self, file_id: int, translations: Any) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/projects/{PROJECT_ID}/files/{file_id}/translation",
            files={
                "file": (
                    "translation-subset.json",
                    json.dumps(translations, ensure_ascii=False).encode("utf-8"),
                    "application/json",
                )
            },
            timeout=60,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise ValueError("ParaTranz returned invalid import response JSON") from exc
        revision = payload.get("revision") if isinstance(payload, dict) else None
        if not isinstance(revision, dict) or revision.get("type") != "import":
            raise ValueError("ParaTranz did not confirm an import revision")
        return revision


def _history_string_id(item: dict[str, Any]) -> int | None:
    value = item.get("tid")
    if value is None and isinstance(item.get("target"), dict):
        value = item["target"].get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def history_for_string(history: Iterable[dict[str, Any]], string_id: int) -> list[dict[str, Any]]:
    matches = [item for item in history if _history_string_id(item) == string_id]
    return sorted(matches, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))


def manual_translation_history(history: Iterable[dict[str, Any]], string_id: int) -> list[dict[str, Any]]:
    return [
        item for item in history_for_string(history, string_id)
        if item.get("field") == "translation" and item.get("operation") != "import"
    ]


def has_translation_import(history: Iterable[dict[str, Any]], string_id: int) -> bool:
    return any(
        item.get("field") == "translation" and item.get("operation") == "import"
        for item in history_for_string(history, string_id)
    )


def manual_translation_fingerprint(history: Iterable[dict[str, Any]], string_id: int) -> str:
    encoded = json.dumps(manual_translation_history(history, string_id), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def history_fingerprint(history: Iterable[dict[str, Any]], string_id: int) -> str:
    encoded = json.dumps(history_for_string(history, string_id), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _path_value(item: dict[str, Any]) -> str:
    for key in ("path", "name", "filename"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value.replace("\\", "/").lstrip("./")
    return ""


def resolve_file(files: list[dict[str, Any]], file_path: str, file_id: int | None) -> dict[str, Any]:
    if file_id is not None:
        matches = [item for item in files if str(item.get("id")) == str(file_id)]
    else:
        wanted = file_path.replace("\\", "/").lstrip("./")
        matches = [item for item in files if _path_value(item) == wanted]
    if len(matches) != 1:
        raise ValueError(f"Expected one ParaTranz file match, found {len(matches)}")
    return matches[0]


def _string_file_id(item: dict[str, Any]) -> int | None:
    value = item.get("fileId")
    if value is None and isinstance(item.get("file"), dict):
        value = item["file"].get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _terms(raw_terms: Iterable[dict[str, Any]]) -> tuple[Term, ...]:
    result = []
    seen = set()
    for entry in raw_terms:
        source = next((entry.get(key) for key in ("term", "source", "original") if isinstance(entry.get(key), str) and entry[key]), None)
        target = next((entry.get(key) for key in ("translation", "target", "translated") if entry.get(key)), None)
        targets = (target,) if isinstance(target, str) else tuple(target) if isinstance(target, list) else ()
        targets = tuple(value for value in targets if isinstance(value, str) and value)
        variants = entry.get("variants", [])
        sources = [source] if source else []
        if isinstance(variants, list):
            sources.extend(value for value in variants if isinstance(value, str) and value)
        for term_source in sources:
            identity = (term_source, targets)
            if targets and identity not in seen:
                result.append(Term(term_source, targets))
                seen.add(identity)
    return tuple(result)


def _relevant_terms(source: str, terms: tuple[Term, ...]) -> list[dict[str, Any]]:
    return [{"source": term.source, "translations": list(term.translations)} for term in terms if term.source in source]


def _invisible_characters(value: str) -> list[str]:
    return [
        char for char in value
        if unicodedata.category(char) in {"Cc", "Cf"} and char not in "\r\n"
    ]


def validate_translation(source: str, translation: str, terms: tuple[Term, ...]) -> list[dict[str, str]]:
    if not isinstance(translation, str) or not translation.strip():
        return [{"rule": "empty_translation", "severity": "error", "message": "Translation is empty"}]
    issues = RULES.check(CheckContext(source, translation, "text", terms))
    records = [{"rule": issue.rule, "severity": issue.severity, "message": issue.message} for issue in issues]
    if source.count("\n") != translation.count("\n") or source.count("\\n") != translation.count("\\n"):
        records.append({
            "rule": "line_breaks",
            "severity": "error",
            "message": "Line break markers do not match the original",
        })
    if "..." in translation or "…?" in translation or "…？" in translation or ELLIPSIS_PUNCTUATION_RE.search(translation):
        records.append({"rule": "ellipsis_style", "severity": "error", "message": "Use Chinese ellipsis and do not combine it with commas or full stops"})
    if source.strip() == "…" and translation.strip() == "…":
        records.append({"rule": "ellipsis_style", "severity": "warning", "message": "A standalone ellipsis should preferably be rendered as ……"})
    if any(char in translation for char in "~"):
        records.append({"rule": "fullwidth_tilde", "severity": "error", "message": "Use the fullwidth tilde ～ instead of ASCII ~"})
    if translation.count("-") > source.count("-"):
        records.append({"rule": "dash_style", "severity": "error", "message": "Use an em dash — unless the original contains the ASCII hyphen"})
    if CJK_LATIN_SPACE_RE.search(translation):
        records.append({"rule": "cjk_latin_spacing", "severity": "error", "message": "Do not add spaces between Chinese and English characters"})
    if any(char in translation for char in '\"“”‘’'):
        records.append({"rule": "corner_quotes", "severity": "error", "message": "Use 「」 for quotation marks"})
    source_special = Counter(char for char in source if char in EVA_SPECIAL_CHARACTERS)
    translation_special = Counter(char for char in translation if char in EVA_SPECIAL_CHARACTERS)
    if source_special != translation_special:
        records.append({"rule": "eva_special_characters", "severity": "error", "message": "Preserve EVA special glyphs Θ Α Τ Ν Σ and Ｓ exactly"})
    if _invisible_characters(source) != _invisible_characters(translation):
        records.append({"rule": "invisible_characters", "severity": "error", "message": "Preserve invisible control and format characters exactly"})
    if len(LAYOUT_SPACE_RE.findall(source)) > len(LAYOUT_SPACE_RE.findall(translation)):
        records.append({"rule": "layout_spaces", "severity": "warning", "message": "Preserve repeated spaces used for layout where possible"})
    return records


def chat_completions_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value:
        raise ValueError("OAI_BASE_URL is empty")
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("OAI_BASE_URL must be an absolute URL")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        pass
    elif path.endswith("/v1"):
        path += "/chat/completions"
    elif path.endswith("/api"):
        path += "/v1/chat/completions"
    else:
        path += "/v1/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def _prompt(batch: list[dict[str, Any]]) -> list[dict[str, str]]:
    lines = [
        "Translate each English original into Simplified Chinese for the Neon Genesis Evangelion 2 PSP game.",
        "Use the project's established Chinese localization style and the supplied terminology.",
        "Preserve every format marker exactly, including $m, $n, %s, ▽, and line breaks.",
        "Chinese punctuation and layout rules: copy ideographic full stops 。; keep 、 in short titles, but use Chinese commas for pauses and where 、 acts as a comma in long sentences.",
        "Use the Chinese ellipsis … rather than three ASCII periods. Prefer …… for a standalone ellipsis; normalize …。 to …… and …？ to ？. Never place a Chinese comma or full stop directly before or after an ellipsis.",
        "Use corner quotes 「」 for all quotation marks. Preserve invisible characters exactly. Do not use ASCII ~; use ～. Do not introduce ASCII hyphens; use — unless the original contains a hyphen.",
        "Do not put spaces between Chinese and English characters. Match the original's fullwidth Latin style where possible. Keep line count, line lengths, and spacing distribution close to the source; preserve repeated layout spaces.",
        "Never translate or replace EVA special glyphs Θ, Α, Τ, Ν, Σ, or fullwidth Ｓ. These are game symbols with fixed rendered meanings; preserve each exact character. Preserve ▽ as a dialog page marker.",
        "Do not add explanations. Return a JSON object with a results array. Each result must have an integer id and string translation.",
        "The input contains originals and context only. Do not ask for or infer prior translations.",
        "Items:",
        json.dumps(batch, ensure_ascii=False),
    ]
    return [{"role": "system", "content": "You are a careful video game localization translator."}, {"role": "user", "content": "\n".join(lines)}]


def _decode_completion(payload: Any, expected_ids: set[int]) -> dict[int, str]:
    try:
        content = payload["choices"][0]["message"]["content"]
        decoded = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("Chat Completions returned invalid JSON content") from exc
    if isinstance(decoded, dict) and isinstance(decoded.get("results"), list):
        decoded = decoded["results"]
    if not isinstance(decoded, list):
        raise ValueError("Chat Completions content must be a JSON array")
    results: dict[int, str] = {}
    for row in decoded:
        if not isinstance(row, dict) or "id" not in row or not isinstance(row.get("translation"), str) or not row["translation"].strip():
            raise ValueError("Chat Completions item is missing an ID or non-empty translation")
        try:
            string_id = int(row["id"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Chat Completions item has an invalid ID") from exc
        if string_id in results:
            raise ValueError("Chat Completions returned a duplicate ID")
        results[string_id] = row["translation"]
    if set(results) != expected_ids:
        raise ValueError("Chat Completions IDs do not match the requested batch")
    return results


def translate_batch(batch: list[dict[str, Any]], api_key: str, model: str, base_url: str, session=None, retries: int = 4) -> dict[int, str]:
    http = session or requests.Session()
    url = chat_completions_url(base_url)
    expected = {int(item["id"]) for item in batch}
    for attempt in range(retries):
        try:
            response = http.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": _prompt(batch),
                    "response_format": {"type": "json_object"},
                },
                timeout=120,
            )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 == retries:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After") if response.status_code == 429 else None
                try:
                    delay = min(float(retry_after), 60) if retry_after else min(2**attempt, 30)
                except ValueError:
                    delay = min(2**attempt, 30)
                time.sleep(delay)
                continue
            response.raise_for_status()
            return _decode_completion(response.json(), expected)
        except (requests.RequestException, ValueError):
            if attempt + 1 == retries:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("Chat Completions retries exhausted")


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> dict[tuple[int, str, str], str]:
    values: dict[tuple[int, str, str], str] = {}
    if not path.exists():
        return values
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("original_sha256") and row.get("model"):
                values[(int(row["id"]), row["original_sha256"], row["model"])] = row["translation"]
    return values


def create_preview(args: argparse.Namespace, client: ParaTranzClient, llm_session=None) -> Path:
    files = client.fetch_files()
    target_file = resolve_file(files, args.file, args.file_id)
    file_id = int(target_file["id"])
    strings = client.fetch_strings(file_id)
    history = client.fetch_history()
    terms = _terms(client.fetch_terms())
    unmatched_history = any(_history_string_id(item) is None for item in history)
    history_by_id: dict[int, list[dict[str, Any]]] = {}
    for item in history:
        string_id = _history_string_id(item)
        if string_id is not None:
            history_by_id.setdefault(string_id, []).append(item)

    string_ids = []
    for item in strings:
        try:
            string_ids.append(int(item["id"]))
        except (KeyError, TypeError, ValueError):
            string_ids.append(None)
    duplicate_ids = {string_id for string_id, count in Counter(string_ids).items() if string_id is not None and count > 1}

    records = []
    for item, parsed_id in zip(strings, string_ids):
        try:
            string_id = int(parsed_id)
        except (KeyError, TypeError, ValueError):
            records.append({"status": "skipped", "reason": "invalid_string_id"})
            continue
        original = item.get("original")
        old_translation = item.get("translation") or ""
        own_history = history_by_id.get(string_id, [])
        if _string_file_id(item) != file_id:
            status, reason = "skipped", "file_mismatch"
        elif string_id in duplicate_ids:
            status, reason = "skipped", "duplicate_string_id"
        elif unmatched_history:
            status, reason = "skipped", "history_id_unmatched"
        elif not isinstance(original, str) or not original.strip():
            status, reason = "skipped", "empty_original"
        elif item.get("stage") != 1:
            status, reason = "skipped", "stage_not_one"
        elif manual_translation_history(own_history, string_id):
            status, reason = "skipped", "translation_was_edited"
        else:
            status, reason = "pending", None
        records.append({
            "id": string_id,
            "original": original,
            "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest() if isinstance(original, str) else None,
            "old_translation": old_translation,
            "stage": item.get("stage"),
            "context": item.get("context") or "",
            "history_fingerprint": history_fingerprint(own_history, string_id),
            "manual_translation_fingerprint": manual_translation_fingerprint(own_history, string_id),
            "status": status,
            "reason": reason,
            "translation": None,
            "validation": [],
        })

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"
    resumed = _read_jsonl(results_path)
    candidates = [row for row in records if row["status"] == "pending"]
    terms_by_id = {row["id"]: terms for row in candidates}
    failed_ids: set[int] = set()
    pending_results = [
        row for row in candidates
        if (row["id"], row["original_sha256"], args.model) not in resumed
    ]
    for start in range(0, len(pending_results), args.batch_size):
        group = pending_results[start : start + args.batch_size]
        prompt_rows = [{"id": row["id"], "original": row["original"], "context": row["context"], "terms": _relevant_terms(row["original"], terms)} for row in group]
        try:
            outputs = translate_batch(prompt_rows, args.oai_api_key, args.model, args.oai_base_url, session=llm_session, retries=args.retries)
        except (requests.RequestException, ValueError, RuntimeError):
            failed_ids.update(row["id"] for row in group)
            continue
        for string_id, translation in outputs.items():
            source_row = next(row for row in group if row["id"] == string_id)
            identity = (string_id, source_row["original_sha256"], args.model)
            _append_jsonl(results_path, {"id": string_id, "original_sha256": source_row["original_sha256"], "model": args.model, "translation": translation})
            resumed[identity] = translation

    for row in candidates:
        identity = (row["id"], row["original_sha256"], args.model)
        if identity not in resumed:
            row["status"] = "failed"
            row["reason"] = "model_request_failed" if row["id"] in failed_ids else "missing_model_result"
            continue
        row["translation"] = resumed[identity]
        row["validation"] = validate_translation(row["original"], row["translation"], terms_by_id[row["id"]])
        row["status"] = "ready" if not row["validation"] else "invalid"

    report = {
        "project_id": PROJECT_ID,
        "file_id": file_id,
        "file": _path_value(target_file),
        "model": args.model,
        "entries": records,
    }
    report_path = run_dir / "report.json"
    _write_report(report_path, report)
    return report_path


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def watch_apply(args: argparse.Namespace, client: ParaTranzClient) -> None:
    run_dir = Path(args.run_dir)
    results_path = run_dir / "results.jsonl"
    state_path = run_dir / "watch-state.json"
    report_path = run_dir / "report.json"
    if not results_path.exists():
        raise FileNotFoundError(f"Results file does not exist: {results_path}")

    previous_state = None
    if state_path.exists():
        previous_state = json.loads(state_path.read_text(encoding="utf-8"))
        if previous_state.get("file_id") != args.file_id:
            raise ValueError("Saved watch state belongs to a different ParaTranz file")
    if previous_state is not None and not args.rebuild_state:
        state = previous_state
        terms = _terms(client.fetch_terms())
        retried = 0
        for entry in state.get("candidates", {}).values():
            if entry.get("status") == "invalid" and entry.get("validation") and all(
                issue.get("rule") == "ideographic_full_stop" for issue in entry["validation"]
            ):
                entry["status"] = "pending"
                entry["validation"] = []
                retried += 1
        if retried:
            _write_state(state_path, state)
            print(f"Revalidating {retried} saved entries under the current rules", flush=True)
    else:
        files = client.fetch_files()
        target_file = resolve_file(files, args.file, args.file_id)
        file_id = int(target_file["id"])
        strings, history = client.fetch_current(file_id)
        terms = _terms(client.fetch_terms())
        unmatched_history = any(_history_string_id(item) is None for item in history)
        history_by_id: dict[int, list[dict[str, Any]]] = {}
        for item in history:
            string_id = _history_string_id(item)
            if string_id is not None:
                history_by_id.setdefault(string_id, []).append(item)
        candidates: dict[str, dict[str, Any]] = {}
        blocked: dict[str, str] = {}
        for item in strings:
            try:
                string_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            original = item.get("original")
            own_history = history_by_id.get(string_id, [])
            if _string_file_id(item) != file_id:
                reason = "file_mismatch"
            elif unmatched_history:
                reason = "history_id_unmatched"
            elif not isinstance(original, str) or not original.strip():
                reason = "empty_original"
            elif item.get("stage") != 1:
                reason = "stage_not_one"
            elif manual_translation_history(own_history, string_id):
                reason = "translation_was_edited"
            else:
                reason = None
            key = str(item.get("key", ""))
            if reason or not key:
                blocked[str(string_id)] = reason or "missing_file_key"
                continue
            candidates[str(string_id)] = {
                "key": key,
                "original": original,
                "original_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                "old_translation": item.get("translation") or "",
                "stage": item.get("stage"),
                "history_fingerprint": history_fingerprint(own_history, string_id),
                "manual_translation_fingerprint": manual_translation_fingerprint(own_history, string_id),
                "status": "pending",
                "validation": [],
            }
        key_counts = Counter(entry["key"] for entry in candidates.values())
        for string_id, entry in list(candidates.items()):
            if key_counts[entry["key"]] > 1:
                blocked[string_id] = "duplicate_file_key"
                del candidates[string_id]
        model = (previous_state or {}).get("model") or os.environ.get("OAI_MODEL") or os.environ.get("OPENAI_MODEL")
        resumed = _read_jsonl(results_path)
        applied_count = 0
        current_by_id = {str(item.get("id")): item for item in strings if item.get("id") is not None}
        for raw_id, entry in candidates.items():
            result = resumed.get((int(raw_id), entry["original_sha256"], model))
            current_translation = (current_by_id.get(raw_id) or {}).get("translation") or ""
            if (
                result is not None
                and current_translation == result
                and not validate_translation(entry["original"], result, terms)
            ):
                entry["status"] = "applied"
                applied_count += 1
        state = {
            "file_id": file_id,
            "file": _path_value(target_file),
            "model": model,
            "candidates": candidates,
            "blocked": blocked,
            "applied": applied_count,
            "conflict": 0,
            "invalid": 0,
        }
        _write_state(state_path, state)

    candidates = state["candidates"]
    blocked = state.get("blocked", {})
    def report_signature() -> tuple[int, int] | None:
        if not report_path.exists():
            return None
        stat = report_path.stat()
        return stat.st_mtime_ns, stat.st_size

    initial_report_signature = report_signature()
    print(f"Watching {results_path}; file_id={state['file_id']}; candidates={len(candidates)}", flush=True)
    while True:
        result_rows: dict[int, str] = {}
        result_hashes: dict[int, str] = {}
        for line_number, line in enumerate(results_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                string_id = int(row["id"])
                if row.get("model") == state.get("model") and isinstance(row.get("translation"), str):
                    result_rows[string_id] = row["translation"]
                    result_hashes[string_id] = row.get("original_sha256")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue

        ready: list[tuple[str, dict[str, Any], str]] = []
        for raw_id, entry in candidates.items():
            if entry["status"] != "pending":
                continue
            string_id = int(raw_id)
            translation = result_rows.get(string_id)
            if translation is None:
                continue
            if result_hashes.get(string_id) != entry["original_sha256"]:
                entry["status"] = "conflict"
                entry["reason"] = "result_source_mismatch"
                state["conflict"] += 1
                _write_state(state_path, state)
                continue
            validation = validate_translation(entry["original"], translation, terms)
            if validation:
                entry["status"] = "invalid"
                entry["validation"] = validation
                state["invalid"] += 1
                _write_state(state_path, state)
                continue
            ready.append((raw_id, entry, translation))
            if len(ready) >= args.batch_size:
                break

        if ready:
            try:
                current_strings, current_history = client.fetch_current(int(state["file_id"]))
                current_by_id = {}
                for item in current_strings:
                    try:
                        current_by_id[int(item["id"])] = item
                    except (KeyError, TypeError, ValueError):
                        continue
                if any(_history_string_id(item) is None for item in current_history):
                    raise ValueError("History contains an unmatched string ID")
                safe: list[tuple[str, dict[str, Any], str]] = []
                for raw_id, entry, translation in ready:
                    current = current_by_id.get(int(raw_id))
                    own_history = history_for_string(current_history, int(raw_id))
                    if (
                        current is None
                        or entry["stage"] != 1
                        or current.get("original") != entry["original"]
                        or current.get("stage") != entry["stage"]
                        or manual_translation_fingerprint(current_history, int(raw_id))
                        != entry.get("manual_translation_fingerprint", hashlib.sha256(b"[]").hexdigest())
                        or (
                            (current.get("translation") or "") != entry["old_translation"]
                            and not has_translation_import(current_history, int(raw_id))
                        )
                    ):
                        entry["status"] = "conflict"
                        entry["reason"] = "remote_state_changed"
                        state["conflict"] += 1
                    else:
                        safe.append((raw_id, entry, translation))
                if safe:
                    payload = [
                        {
                            "id": int(raw_id),
                            "key": entry["key"],
                            "original": entry["original"],
                            "translation": translation,
                            "stage": entry["stage"],
                            "context": current_by_id[int(raw_id)].get("context") or "",
                        }
                        for raw_id, entry, translation in safe
                    ]
                    revision = client.import_translation_subset(int(state["file_id"]), payload)
                    verify_strings = client.fetch_strings(int(state["file_id"]))
                    verify_by_id = {int(item["id"]): item for item in verify_strings if item.get("id") is not None}
                    for raw_id, entry, translation in safe:
                        current = verify_by_id.get(int(raw_id))
                        if current is None or current.get("translation") != translation:
                            entry["status"] = "conflict"
                            entry["reason"] = "import_verification_failed"
                            state["conflict"] += 1
                        else:
                            entry["status"] = "applied"
                            entry["revision_id"] = revision.get("id")
                            entry["reason"] = None
                            state["applied"] += 1
                _write_state(state_path, state)
                print(f"Progress: applied={state['applied']} conflict={state['conflict']} invalid={state['invalid']}", flush=True)
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                print(f"Batch deferred: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(args.poll_interval * 3)
                continue

        if report_path.exists() and report_signature() != initial_report_signature:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            pending_report = False
            for row in report.get("entries", []):
                entry = candidates.get(str(row.get("id")))
                if entry and entry.get("status") == "applied":
                    row["status"] = "applied"
                    row["reason"] = None
                    row["revision_id"] = entry.get("revision_id")
                elif entry and entry.get("status") == "conflict":
                    row["status"] = "conflict"
                    row["reason"] = entry.get("reason")
                elif entry and entry.get("status") == "invalid":
                    row["status"] = "invalid"
                    row["validation"] = entry.get("validation", [])
                elif entry and entry.get("status") == "failed":
                    row["status"] = "failed"
                    row["reason"] = entry.get("reason")
                elif entry is None:
                    if row.get("status") == "ready":
                        row["status"] = "conflict"
                        row["reason"] = "not_eligible_at_watch_start"
                elif row.get("status") == "ready":
                    pending_report = True
                elif row.get("status") == "failed":
                    entry["status"] = "failed"
                    entry["reason"] = row.get("reason") or "model_request_failed"
                elif row.get("status") == "skipped":
                    entry["status"] = "conflict"
                    entry["reason"] = row.get("reason") or "not_eligible_for_import"
                    state["conflict"] += 1
            _write_state(state_path, state)
            _write_report(report_path, report)
            if not pending_report:
                print(f"Finished: applied={state['applied']} conflict={state['conflict']} invalid={state['invalid']}", flush=True)
                return
        time.sleep(args.poll_interval)


def apply_report(report_path: Path, client: ParaTranzClient) -> dict[str, int]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    file_id = int(report["file_id"])
    stats = {"applied": 0, "conflict": 0, "skipped": 0}
    changed = False
    for row in report.get("entries", []):
        if row.get("status") == "applied":
            continue
        if row.get("status") != "ready":
            stats["skipped"] += 1
            continue
        strings, history = client.fetch_current(file_id)
        current_by_id = {}
        for item in strings:
            try:
                current_by_id[int(item["id"])] = item
            except (KeyError, TypeError, ValueError):
                continue
        current = current_by_id.get(int(row["id"]))
        mismatch = current is None or any(_history_string_id(item) is None for item in history)
        if current is not None:
            mismatch = (
                any(_history_string_id(item) is None for item in history)
                or row.get("stage") != 1
                or current.get("original") != row.get("original")
                or current.get("stage") != row.get("stage")
                or manual_translation_fingerprint(history, int(row["id"]))
                != row.get("manual_translation_fingerprint", hashlib.sha256(b"[]").hexdigest())
                or (
                    (current.get("translation") or "") != row.get("old_translation", "")
                    and not has_translation_import(history, int(row["id"]))
                )
            )
        if mismatch:
            row["status"] = "conflict"
            row["reason"] = "remote_state_changed"
            stats["conflict"] += 1
            changed = True
            continue
        client.update_string(int(row["id"]), row["translation"])
        row["status"] = "applied"
        row["reason"] = None
        stats["applied"] += 1
        changed = True
        _write_report(report_path, report)
    if changed:
        _write_report(report_path, report)
    return stats


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview", help="generate and validate local translations")
    preview.add_argument("--file", default="game/imtext.json")
    preview.add_argument("--file-id", type=int)
    preview.add_argument("--run-dir", type=Path, required=True)
    preview.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    preview.add_argument("--retries", type=int, default=4)
    apply = subparsers.add_parser("apply", help="apply validated translations from a report")
    apply.add_argument("--report", type=Path, required=True)
    watch = subparsers.add_parser("watch-apply", help="watch JSONL results and import safe translation subsets")
    watch.add_argument("--file", default="game/imtext.json")
    watch.add_argument("--file-id", type=int, default=1483701)
    watch.add_argument("--run-dir", type=Path, required=True)
    watch.add_argument("--batch-size", type=int, default=20)
    watch.add_argument("--poll-interval", type=float, default=3)
    watch.add_argument("--rebuild-state", action="store_true", help="refresh candidates while preserving verified applied results")
    return parser


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    parser = _parser()
    args = parser.parse_args(argv)
    token = os.environ.get("AUTH_KEY")
    if not token:
        parser.error("AUTH_KEY is required (set it in the repository .env or environment)")
    client = ParaTranzClient(token)
    if args.command == "preview":
        args.oai_base_url = os.environ.get("OAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        args.oai_api_key = os.environ.get("OAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        args.model = os.environ.get("OAI_MODEL") or os.environ.get("OPENAI_MODEL")
        if not args.oai_api_key or not args.model:
            parser.error("OAI_API_KEY and OAI_MODEL are required for preview")
        if args.batch_size < 1 or args.retries < 1:
            parser.error("--batch-size and --retries must be positive")
        report = create_preview(args, client)
        print(f"Preview report written to {report}")
    else:
        if args.command == "apply":
            stats = apply_report(args.report, client)
            print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
        else:
            if args.batch_size < 1 or args.poll_interval <= 0:
                parser.error("--batch-size must be positive and --poll-interval must be greater than zero")
            watch_apply(args, client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
