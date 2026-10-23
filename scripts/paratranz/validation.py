"""Translation validation rules shared by ParaTranz workflows.

Keep rules in this module independent from files, reports, HTTP clients, and
command-line interfaces.  This makes each rule usable by both the downloaded
translation checker and tools that validate text before writing to ParaTranz.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from app.parser.tools.common import to_eva_sjis
from app.parser.tools.evs import CONTENT_BYTE_LIMIT

CHECK_TYPES = ("eboot", "evs", "text")
FORMAT_MARKER_PATTERN = re.compile(r"%[0-9]*[a-zA-Z]+|\$[0-9]*[a-zA-Z]+|▽")
FULLWIDTH_DIGIT_PATTERN = re.compile(r"[０-９]")
CJK_LATIN_SPACE_PATTERN = re.compile(
    r"[\u3400-\u9fff\uf900-\ufaff] [A-Za-z0-9]"
    r"|[A-Za-z0-9] [\u3400-\u9fff\uf900-\ufaff]"
)
ELLIPSIS_PUNCTUATION_PATTERN = re.compile(r"(?:……|…)[，。,.]|[，。,.](?:……|…)")
LAYOUT_SPACE_PATTERN = re.compile(r" {2,}")
EVA_SPECIAL_CHARACTERS = frozenset("ΘΑΤΝΣＳ")


@dataclass(frozen=True)
class Term:
    source: str
    translations: tuple[str, ...]


@dataclass(frozen=True)
class CheckContext:
    source: str
    translation: str
    check_type: str
    terms: tuple[Term, ...] = ()


@dataclass(frozen=True)
class ValidationIssue:
    rule: str
    message: str
    severity: str = "warning"


Rule = Callable[[CheckContext], list[ValidationIssue]]


class RuleRegistry:
    """Register named rules and select them by translation resource type."""

    def __init__(self) -> None:
        self._rules: list[tuple[str, tuple[str, ...], Rule]] = []

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

    def check(self, context: CheckContext) -> list[ValidationIssue]:
        if context.check_type not in CHECK_TYPES:
            raise ValueError(f"Unknown check type: {context.check_type}")

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


def find_special_characters(value: str) -> dict[str, int]:
    """Return counts of runtime format markers in a string."""
    return dict(Counter(FORMAT_MARKER_PATTERN.findall(value)))


def match_exist_in_string(matches: dict[str, int], string: str) -> None:
    """Raise when a string does not contain exactly the expected markers."""
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


def _issue(rule: str, message: str, severity: str = "warning") -> list[ValidationIssue]:
    return [ValidationIssue(rule, message, severity)]


@RULES.register("format_markers")
def check_format_markers(context: CheckContext) -> list[ValidationIssue]:
    expected = find_special_characters(context.source)
    actual = find_special_characters(context.translation)
    if expected == actual:
        return []
    return _issue(
        "format_markers",
        f"Format marker mismatch: original has {expected}, translation has {actual}",
        "error",
    )


@RULES.register("line_breaks")
def check_line_breaks(context: CheckContext) -> list[ValidationIssue]:
    actual = (context.translation.count("\n"), context.translation.count("\\n"))
    expected = (context.source.count("\n"), context.source.count("\\n"))
    if actual == expected:
        return []
    return _issue("line_breaks", "Line break markers do not match the original")


@RULES.register("fullwidth_digits")
def check_fullwidth_digits(context: CheckContext) -> list[ValidationIssue]:
    digits = sorted(set(FULLWIDTH_DIGIT_PATTERN.findall(context.translation)))
    if not digits:
        return []
    return _issue(
        "fullwidth_digits",
        f"Translation contains full-width digit(s): {''.join(digits)}",
    )


@RULES.register("encoding")
def check_encoding(context: CheckContext) -> list[ValidationIssue]:
    try:
        encoding_error(context.source, context.translation)
    except ValueError as exc:
        return _issue("encoding", str(exc), "error")
    return []


@RULES.register("length_ratio")
def check_length_ratio(context: CheckContext) -> list[ValidationIssue]:
    if context.source and len(context.translation) > 2 * len(context.source):
        return _issue(
            "length_ratio",
            f"Translation length {len(context.translation)} is more than twice "
            f"the original length {len(context.source)}",
        )
    return []


@RULES.register("eboot_length", check_types=("eboot",))
def check_eboot_length(context: CheckContext) -> list[ValidationIssue]:
    try:
        eboot_length_error(context.source, context.translation)
    except ValueError as exc:
        severity = "error" if "Length error" in str(exc) else "warning"
        return _issue("eboot_length", str(exc), severity)
    return []


@RULES.register("paging", check_types=("evs",))
def check_paging(context: CheckContext) -> list[ValidationIssue]:
    try:
        paging_error(context.source, context.translation)
    except ValueError as exc:
        return _issue("paging", str(exc), "error")
    return []


@RULES.register("terminology")
def check_terminology(context: CheckContext) -> list[ValidationIssue]:
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


@RULES.register("ellipsis_style")
def check_ellipsis_style(context: CheckContext) -> list[ValidationIssue]:
    translation = context.translation
    issues = []
    if (
        "..." in translation
        or "…?" in translation
        or "…？" in translation
        or ELLIPSIS_PUNCTUATION_PATTERN.search(translation)
    ):
        issues.extend(
            _issue(
                "ellipsis_style",
                "Use Chinese ellipsis and do not combine it with commas or full stops",
                "error",
            )
        )
    if context.source.strip() == "…" and translation.strip() == "…":
        issues.extend(
            _issue(
                "ellipsis_style",
                "A standalone ellipsis should preferably be rendered as ……",
            )
        )
    return issues


@RULES.register("fullwidth_tilde")
def check_fullwidth_tilde(context: CheckContext) -> list[ValidationIssue]:
    if "~" not in context.translation:
        return []
    return _issue(
        "fullwidth_tilde", "Use the fullwidth tilde ～ instead of ASCII ~", "error"
    )


@RULES.register("dash_style")
def check_dash_style(context: CheckContext) -> list[ValidationIssue]:
    if context.translation.count("-") <= context.source.count("-"):
        return []
    return _issue(
        "dash_style",
        "Use an em dash — unless the original contains the ASCII hyphen",
        "error",
    )


@RULES.register("cjk_latin_spacing")
def check_cjk_latin_spacing(context: CheckContext) -> list[ValidationIssue]:
    if not CJK_LATIN_SPACE_PATTERN.search(context.translation):
        return []
    return _issue(
        "cjk_latin_spacing",
        "Do not add spaces between Chinese and English characters",
        "error",
    )


@RULES.register("corner_quotes")
def check_corner_quotes(context: CheckContext) -> list[ValidationIssue]:
    if not any(char in context.translation for char in '\"“”‘’'):
        return []
    return _issue("corner_quotes", "Use 「」 for quotation marks", "error")


@RULES.register("eva_special_characters")
def check_eva_special_characters(context: CheckContext) -> list[ValidationIssue]:
    source = Counter(char for char in context.source if char in EVA_SPECIAL_CHARACTERS)
    translation = Counter(
        char for char in context.translation if char in EVA_SPECIAL_CHARACTERS
    )
    if source == translation:
        return []
    return _issue(
        "eva_special_characters",
        "Preserve EVA special glyphs Θ Α Τ Ν Σ and Ｓ exactly",
        "error",
    )


def _invisible_characters(value: str) -> Counter[str]:
    return Counter(
        char
        for char in value
        if unicodedata.category(char) in {"Cc", "Cf"} and char not in "\r\n"
    )


@RULES.register("invisible_characters")
def check_invisible_characters(context: CheckContext) -> list[ValidationIssue]:
    if _invisible_characters(context.source) == _invisible_characters(
        context.translation
    ):
        return []
    return _issue(
        "invisible_characters",
        "Preserve invisible control and format characters exactly",
        "error",
    )


@RULES.register("layout_spaces")
def check_layout_spaces(context: CheckContext) -> list[ValidationIssue]:
    source_count = len(LAYOUT_SPACE_PATTERN.findall(context.source))
    translation_count = len(LAYOUT_SPACE_PATTERN.findall(context.translation))
    if source_count <= translation_count:
        return []
    return _issue(
        "layout_spaces", "Preserve repeated spaces used for layout where possible"
    )


def _extract_term_entries(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("terms", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("terminology JSON must be an array or contain terms/results/data")


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def parse_terms(payload: object) -> tuple[Term, ...]:
    """Parse terms and source variants from common ParaTranz response shapes."""
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
        variants = _string_values(entry.get("variants"))
        for term_source in ((source,) if source else ()) + variants:
            identity = (term_source, translations)
            if translations and identity not in seen:
                terms.append(Term(term_source, translations))
                seen.add(identity)
    return tuple(terms)


def load_terms(path: Path) -> tuple[Term, ...]:
    """Load a ParaTranz terminology JSON file."""
    with path.open("r", encoding="utf-8") as input_file:
        return parse_terms(json.load(input_file))


def relevant_terms(source: str, terms: Iterable[Term]) -> list[dict[str, object]]:
    """Return prompt-ready terminology entries that occur in the source text."""
    return [
        {"source": term.source, "translations": list(term.translations)}
        for term in terms
        if term.source in source
    ]


def validate_translation(
    source: str,
    translation: str,
    terms: tuple[Term, ...] = (),
    check_type: str = "text",
) -> list[dict[str, str]]:
    """Return serializable issue records for one translated string."""
    if not isinstance(translation, str) or not translation.strip():
        return [
            {
                "rule": "empty_translation",
                "severity": "error",
                "message": "Translation is empty",
            }
        ]
    return [
        {"rule": issue.rule, "severity": issue.severity, "message": issue.message}
        for issue in RULES.check(CheckContext(source, translation, check_type, terms))
    ]
