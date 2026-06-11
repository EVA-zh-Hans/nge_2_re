from app.parser.tools import common


INFO_TITLE_MAX_BYTES = 34
INFO_LINE_MAX_BYTES = 54
INFO_BODY_LINES_PER_PAGE = 5

_FULLWIDTH_PAGE_DIGITS = "１２３４５６７８９"


def _encoded_length(text: str) -> int:
    return len(common.to_eva_sjis(text))


def _fail(entry_label: str, message: str) -> None:
    prefix = f"{entry_label}: " if entry_label else ""
    raise ValueError(prefix + message)


def validate_info_text(text: str, entry_label: str = "") -> None:
    """Validate f2info text without changing translator-controlled layout."""
    if "\0" in text:
        _fail(entry_label, "contains an embedded NUL byte")
    if "\r" in text:
        _fail(entry_label, "contains CR/CRLF; use LF newlines")
    if "%" in text:
        _fail(entry_label, "contains '%', which the game treats as a format directive")

    parts = text.split("\n", 2)
    if len(parts) != 3:
        _fail(entry_label, "must contain a page-count line and a title line")

    page_count_text, title, body = parts
    if len(page_count_text) != 1 or page_count_text not in _FULLWIDTH_PAGE_DIGITS:
        _fail(
            entry_label,
            "page count must be one full-width digit from １ to ９",
        )

    title_bytes = _encoded_length(title)
    if not title:
        _fail(entry_label, "title must not be empty")
    if title_bytes > INFO_TITLE_MAX_BYTES:
        _fail(
            entry_label,
            f"title is {title_bytes} encoded bytes; maximum is {INFO_TITLE_MAX_BYTES}",
        )

    pages = body.split("$n")
    declared_pages = _FULLWIDTH_PAGE_DIGITS.index(page_count_text) + 1
    if declared_pages != len(pages):
        _fail(
            entry_label,
            f"declares {declared_pages} pages but contains {len(pages)}",
        )

    for page_index, raw_page in enumerate(pages):
        expected_prefix = "\n" if page_index == 0 else "\n\n"
        if not raw_page.startswith(expected_prefix):
            _fail(
                entry_label,
                f"page {page_index + 1} must begin with the standard blank line",
            )

        is_last_page = page_index == len(pages) - 1
        if is_last_page:
            if not raw_page.endswith("\n"):
                _fail(entry_label, f"final page must end with LF")
            content = raw_page[len(expected_prefix) : -1]
        else:
            if raw_page.endswith("\n"):
                _fail(
                    entry_label,
                    f"page {page_index + 1} must place $n directly after its final text",
                )
            content = raw_page[len(expected_prefix) :]

        lines = content.split("\n") if content else []
        if len(lines) > INFO_BODY_LINES_PER_PAGE:
            _fail(
                entry_label,
                f"page {page_index + 1} has {len(lines)} body lines; "
                f"maximum is {INFO_BODY_LINES_PER_PAGE}",
            )

        for line_index, line in enumerate(lines, start=1):
            line_bytes = _encoded_length(line)
            if line_bytes > INFO_LINE_MAX_BYTES:
                _fail(
                    entry_label,
                    f"page {page_index + 1}, line {line_index} is "
                    f"{line_bytes} encoded bytes; maximum is {INFO_LINE_MAX_BYTES}",
                )
