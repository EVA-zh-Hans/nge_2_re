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
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from tqdm import tqdm

from scripts.paratranz.validation import (
    CHECK_TYPES,
    RULES,
    CheckContext,
    Term,
    ValidationIssue,
    check_eboot_length,
    check_encoding,
    check_format_markers,
    check_fullwidth_digits,
    check_length_ratio,
    check_paging,
    check_terminology,
    eboot_length_error,
    encoding_error,
    find_special_characters,
    load_terms,
    match_exist_in_string,
    paging_error,
    special_character_error,
)

__all__ = [
    "CHECK_TYPES",
    "RULES",
    "CheckContext",
    "Term",
    "ValidationIssue",
    "check_eboot_length",
    "check_encoding",
    "check_format_markers",
    "check_fullwidth_digits",
    "check_length_ratio",
    "check_paging",
    "check_terminology",
    "eboot_length_error",
    "encoding_error",
    "find_special_characters",
    "load_terms",
    "match_exist_in_string",
    "paging_error",
    "special_character_error",
]


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


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
    rule_names: Optional[Iterable[str]] = None,
) -> Tuple[List[dict], dict]:
    """Check translation files and return issue records and summary counts."""
    file_list = list(files)
    root = display_root or Path.cwd()
    selected_rules = None if rule_names is None else tuple(rule_names)
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
                for issue in RULES.check(context, selected_rules)
            )

    rule_counts = Counter(issue["rule"] for issue in issues)
    severity_counts = Counter(issue["severity"] for issue in issues)
    summary = {
        "files": len(file_list),
        "entries": total_entries,
        "checked": checked_entries,
        "skipped": skipped_entries,
        "issues": len(issues),
        "rules": list(RULES.names if selected_rules is None else selected_rules),
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
        "--rule",
        dest="rules",
        action="append",
        choices=RULES.names,
        help="Run only this validation rule; may be repeated",
    )
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
    issues, summary = check_files(
        files, terms, args.downloads_dir, rule_names=args.rules
    )
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
    issues, summary = check_files(
        [(args.translation_file, args.type)], rule_names=args.rules
    )
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
