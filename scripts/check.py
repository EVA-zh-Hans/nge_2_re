"""Validate normalized ParaTranz translation files.

The checker supports the repository-wide interface used by ``make check_trans``
and the historical single-file positional interface::

    python -m scripts.check --downloads-dir temp/downloads \
        --terms-file temp/downloads/terms-10882.json \
        --report build/translation_report.json

    python -m scripts.check TRANSLATION_FILE REPORT_FILE TYPE

Translation issues are written to the report but do not fail the build by
default. Missing inputs and malformed JSON are execution errors and return a
non-zero status.
"""

import argparse
import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from tqdm import tqdm

from app.parser.tools.common import to_eva_sjis
from app.parser.tools.evs import CONTENT_BYTE_LIMIT


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

CHECK_TYPES = ("eboot", "evs", "text")
FORMAT_MARKER_PATTERN = re.compile(r"%[0-9]*[a-zA-Z]+|\$[0-9]*[a-zA-Z]+|▽")
FULLWIDTH_DIGIT_PATTERN = re.compile(r"[０-９]")


@dataclass(frozen=True)
class Term:
    source: str
    translations: Tuple[str, ...]


@dataclass(frozen=True)
class CheckContext:
    source: str
    translation: str
    check_type: str
    terms: Tuple[Term, ...] = ()


@dataclass(frozen=True)
class ValidationIssue:
    rule: str
    message: str
    severity: str = "warning"


Rule = Callable[[CheckContext], List[ValidationIssue]]


class RuleRegistry:
    """Keep validation rules and their applicable translation types together."""

    def __init__(self) -> None:
        self._rules: List[Tuple[str, Tuple[str, ...], Rule]] = []

    def register(
        self, name: str, check_types: Sequence[str] = ()
    ) -> Callable[[Rule], Rule]:
        unknown_types = set(check_types) - set(CHECK_TYPES)
        if unknown_types:
            raise ValueError(f"Unknown check types for {name}: {sorted(unknown_types)}")

        def decorator(rule: Rule) -> Rule:
            self._rules.append((name, tuple(check_types), rule))
            return rule

        return decorator

    def check(self, context: CheckContext) -> List[ValidationIssue]:
        issues = []
        for name, check_types, rule in self._rules:
            if check_types and context.check_type not in check_types:
                continue
            for issue in rule(context):
                if issue.rule != name:
                    issue = ValidationIssue(name, issue.message, issue.severity)
                issues.append(issue)
        return issues


RULES = RuleRegistry()


def find_special_characters(value: str) -> Dict[str, int]:
    """Return the count of runtime format markers in ``value``."""
    return dict(Counter(FORMAT_MARKER_PATTERN.findall(value)))


def match_exist_in_string(matches: Dict[str, int], string: str) -> None:
    """Raise when ``string`` does not contain exactly the expected markers."""
    actual = find_special_characters(string)
    if matches != actual:
        raise ValueError(
            f"Format marker mismatch: original has {matches}, translation has {actual}"
        )


def special_character_error(source: str, translation: str) -> None:
    """Validate that runtime format markers are preserved exactly."""
    match_exist_in_string(find_special_characters(source), translation)


def eboot_length_error(source: str, translation: str) -> None:
    """Validate the fixed-size EBOOT string replacement limit."""
    original_length = len(to_eva_sjis(source))
    translation_length = len(to_eva_sjis(translation))
    difference = translation_length - original_length
    if difference in range(1, 5):
        raise ValueError(
            f"Length warning: translation is {difference} byte(s) longer than "
            f"original ({translation_length} vs {original_length} bytes)"
        )
    if difference > 4:
        raise ValueError(
            f"Length error: translation is {difference} byte(s) longer than "
            f"original ({translation_length} vs {original_length} bytes)"
        )


def encoding_error(source: str, translation: str) -> None:
    """Validate that a translation can be converted to EVA Shift-JIS."""
    del source
    try:
        to_eva_sjis(translation)
    except Exception as exc:
        raise ValueError(f"Encoding error: {exc}") from exc


def paging_error(source: str, translation: str) -> None:
    """Validate the byte limit for every EVS page and ``$n`` segment."""
    del source
    for page_index, page in enumerate(translation.split("▽"), 1):
        for segment_index, segment in enumerate(page.split("$n"), 1):
            raw_segment = to_eva_sjis(segment)
            encoded_length = len(
                raw_segment.replace(b" ", b"").replace(b"\n", b"")
                + to_eva_sjis("▽")
            )
            if encoded_length >= CONTENT_BYTE_LIMIT:
                preview = segment[:50] + ("..." if len(segment) > 50 else "")
                raise ValueError(
                    f"Paging error: page {page_index}-$n{segment_index} exceeds "
                    f"the limit ({encoded_length} >= {CONTENT_BYTE_LIMIT} bytes): "
                    f"{preview!r}"
                )


@RULES.register("format_markers")
def check_format_markers(context: CheckContext) -> List[ValidationIssue]:
    expected = find_special_characters(context.source)
    actual = find_special_characters(context.translation)
    if expected == actual:
        return []
    return [
        ValidationIssue(
            "format_markers",
            f"Format marker mismatch: original has {expected}, translation has {actual}",
            "error",
        )
    ]


@RULES.register("fullwidth_digits")
def check_fullwidth_digits(context: CheckContext) -> List[ValidationIssue]:
    digits = sorted(set(FULLWIDTH_DIGIT_PATTERN.findall(context.translation)))
    if not digits:
        return []
    return [
        ValidationIssue(
            "fullwidth_digits",
            f"Translation contains full-width digit(s): {''.join(digits)}",
        )
    ]


@RULES.register("encoding")
def check_encoding(context: CheckContext) -> List[ValidationIssue]:
    try:
        encoding_error(context.source, context.translation)
    except ValueError as exc:
        return [ValidationIssue("encoding", str(exc), "error")]
    return []


@RULES.register("length_ratio")
def check_length_ratio(context: CheckContext) -> List[ValidationIssue]:
    if context.source and len(context.translation) > 2 * len(context.source):
        return [
            ValidationIssue(
                "length_ratio",
                f"Translation length {len(context.translation)} is more than twice "
                f"the original length {len(context.source)}",
            )
        ]
    return []


@RULES.register("eboot_length", check_types=("eboot",))
def check_eboot_length(context: CheckContext) -> List[ValidationIssue]:
    try:
        eboot_length_error(context.source, context.translation)
    except ValueError as exc:
        severity = "error" if "Length error" in str(exc) else "warning"
        return [ValidationIssue("eboot_length", str(exc), severity)]
    return []


@RULES.register("paging", check_types=("evs",))
def check_paging(context: CheckContext) -> List[ValidationIssue]:
    try:
        paging_error(context.source, context.translation)
    except ValueError as exc:
        return [ValidationIssue("paging", str(exc), "error")]
    return []


@RULES.register("terminology")
def check_terminology(context: CheckContext) -> List[ValidationIssue]:
    issues = []
    for term in context.terms:
        if term.source not in context.source:
            continue
        if any(value in context.translation for value in term.translations):
            continue
        expected = " / ".join(term.translations)
        issues.append(
            ValidationIssue(
                "terminology",
                f"Source contains term {term.source!r}, expected translation: {expected}",
            )
        )
    return issues


def _extract_term_entries(payload: object) -> List[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("terms", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("terminology JSON must be an array or contain terms/results/data")


def _string_values(value: object) -> Tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def load_terms(path: Path) -> Tuple[Term, ...]:
    """Load the common ParaTranz terminology response shapes."""
    with path.open("r", encoding="utf-8") as input_file:
        payload = json.load(input_file)

    terms = []
    seen = set()
    for entry in _extract_term_entries(payload):
        if not isinstance(entry, dict):
            continue
        source = next(
            (
                entry.get(key)
                for key in ("term", "source", "original")
                if isinstance(entry.get(key), str) and entry.get(key)
            ),
            None,
        )
        translations = ()
        for key in ("translation", "target", "translated"):
            translations = _string_values(entry.get(key))
            if translations:
                break
        if not source or not translations:
            continue
        identity = (source, translations)
        if identity not in seen:
            terms.append(Term(source, translations))
            seen.add(identity)
    return tuple(terms)


def discover_translation_files(downloads_dir: Path) -> List[Tuple[Path, str]]:
    """Find normalized files consumed by the repository import pipeline."""
    candidates = [
        (downloads_dir / "eboot_trans.json", "eboot"),
        (downloads_dir / "evs_trans.json", "evs"),
        (downloads_dir / "utf8" / "memtalk.json", "text"),
    ]
    patterns = (
        ("utf8/free/**/*.json", "text"),
        ("utf8/game/**/*.json", "text"),
        ("utf8/EVS/cev/**/*.json", "evs"),
    )
    for pattern, check_type in patterns:
        candidates.extend((path, check_type) for path in downloads_dir.glob(pattern))

    discovered = []
    seen = set()
    for path, check_type in candidates:
        if path.is_file() and path not in seen:
            discovered.append((path, check_type))
            seen.add(path)
    return sorted(discovered, key=lambda item: str(item[0]))


def load_translation_entries(path: Path) -> List[object]:
    with path.open("r", encoding="utf-8") as input_file:
        entries = json.load(input_file)
    if not isinstance(entries, list):
        raise ValueError(f"Translation file must contain a JSON array: {path}")
    return entries


def _issue_record(
    issue: ValidationIssue,
    path: Path,
    display_root: Path,
    check_type: str,
    entry_index: int,
    entry_key: object,
    source: object,
    translation: object,
) -> dict:
    record = asdict(issue)
    try:
        record["file"] = str(path.relative_to(display_root))
    except ValueError:
        record["file"] = str(path)
    record.update(
        {
            "type": check_type,
            "entry": entry_index,
            "key": entry_key,
            "original": source,
            "translation": translation,
        }
    )
    return record


def check_files(
    files: Iterable[Tuple[Path, str]],
    terms: Tuple[Term, ...] = (),
    display_root: Optional[Path] = None,
) -> Tuple[List[dict], dict]:
    """Check translation files and return issue records and summary counts."""
    file_list = list(files)
    root = display_root or Path.cwd()
    issues = []
    total_entries = 0
    checked_entries = 0
    skipped_entries = 0

    for path, check_type in file_list:
        entries = load_translation_entries(path)
        total_entries += len(entries)
        try:
            description = str(path.relative_to(root))
        except ValueError:
            description = str(path)
        for index, entry in enumerate(
            tqdm(entries, desc=f"Checking {description}", unit="entry"), 1
        ):
            if not isinstance(entry, dict):
                issues.append(
                    _issue_record(
                        ValidationIssue(
                            "entry_structure", "Entry must be a JSON object", "error"
                        ),
                        path,
                        root,
                        check_type,
                        index,
                        f"entry_{index}",
                        None,
                        None,
                    )
                )
                continue

            source = entry.get("original")
            translation = entry.get("translation")
            key = entry.get("key", f"entry_{index}")
            if not isinstance(source, str) or not isinstance(translation, (str, type(None))):
                issues.append(
                    _issue_record(
                        ValidationIssue(
                            "entry_structure",
                            "Entry must have a string original and a string or null translation",
                            "error",
                        ),
                        path,
                        root,
                        check_type,
                        index,
                        key,
                        source,
                        translation,
                    )
                )
                continue
            if not translation:
                skipped_entries += 1
                continue

            checked_entries += 1
            context = CheckContext(source, translation, check_type, terms)
            issues.extend(
                _issue_record(
                    issue, path, root, check_type, index, key, source, translation
                )
                for issue in RULES.check(context)
            )

    rule_counts = Counter(issue["rule"] for issue in issues)
    severity_counts = Counter(issue["severity"] for issue in issues)
    summary = {
        "files": len(file_list),
        "entries": total_entries,
        "checked": checked_entries,
        "skipped": skipped_entries,
        "issues": len(issues),
        "by_rule": dict(sorted(rule_counts.items())),
        "by_severity": dict(sorted(severity_counts.items())),
    }
    return issues, summary


def write_report(report_file: Path, issues: List[dict], summary: dict) -> None:
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with report_file.open("w", encoding="utf-8") as output_file:
        json.dump(
            {"summary": summary, "issues": issues},
            output_file,
            ensure_ascii=False,
            indent=2,
        )


def validate_translations(
    translation_file: Path, report_file: Path, check_type: str
) -> int:
    """Backward-compatible single-file validation entry point."""
    issues, summary = check_files([(translation_file, check_type)])
    write_report(report_file, issues, summary)
    return len(issues)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check normalized translations")
    parser.add_argument("translation_file", nargs="?", type=Path)
    parser.add_argument("legacy_report_file", nargs="?", type=Path)
    parser.add_argument("type", nargs="?", choices=CHECK_TYPES)
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        help="Directory containing merged and normalized ParaTranz downloads",
    )
    parser.add_argument("--terms-file", type=Path, help="ParaTranz terminology JSON")
    parser.add_argument("--report", type=Path, help="Combined JSON report path")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero status when translation issues are found",
    )
    return parser


def _run_batch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.translation_file or args.legacy_report_file or args.type:
        parser.error("positional arguments cannot be combined with --downloads-dir")
    if args.report is None:
        parser.error("--report is required with --downloads-dir")
    if not args.downloads_dir.is_dir():
        raise FileNotFoundError(f"Downloads directory not found: {args.downloads_dir}")

    terms_path = args.terms_file or args.downloads_dir / "terms-10882.json"
    terms = load_terms(terms_path) if terms_path.is_file() else ()
    if args.terms_file is not None and not terms_path.is_file():
        raise FileNotFoundError(f"Terminology file not found: {terms_path}")
    if not terms:
        logger.warning("No usable terminology entries loaded from %s", terms_path)

    files = discover_translation_files(args.downloads_dir)
    if not files:
        raise FileNotFoundError(
            f"No normalized translation files found in: {args.downloads_dir}"
        )
    issues, summary = check_files(files, terms, args.downloads_dir)
    write_report(args.report, issues, summary)
    logger.info(
        "Checked %d entries in %d files: %d issue(s); report: %s",
        summary["checked"],
        summary["files"],
        summary["issues"],
        args.report,
    )
    return 1 if args.strict and issues else 0


def _run_legacy(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.report or args.terms_file:
        parser.error("--report and --terms-file require --downloads-dir")
    if not all((args.translation_file, args.legacy_report_file, args.type)):
        parser.error(
            "provide --downloads-dir/--report or TRANSLATION_FILE REPORT_FILE TYPE"
        )
    issues, summary = check_files([(args.translation_file, args.type)])
    write_report(args.legacy_report_file, issues, summary)
    logger.info(
        "Checked %d entries: %d issue(s); report: %s",
        summary["checked"],
        summary["issues"],
        args.legacy_report_file,
    )
    return 1 if args.strict and issues else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.downloads_dir is not None:
            return _run_batch(args, parser)
        return _run_legacy(args, parser)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
