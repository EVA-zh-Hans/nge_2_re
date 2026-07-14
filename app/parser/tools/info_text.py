from app.parser.tools import common


INFO_TITLE_MAX_BYTES = 34
INFO_LINE_MAX_BYTES = 54
INFO_BODY_LINES_PER_PAGE = 5
TUTO_TITLE_MAX_BYTES = INFO_TITLE_MAX_BYTES
TUTO_LINE_MAX_BYTES = INFO_LINE_MAX_BYTES
TUTO_BODY_LINES_PER_PAGE = 6

_FULLWIDTH_PAGE_DIGITS = "１２３４５６７８９"
_ASCII_PAGE_DIGITS = "123456789"


def _encoded_length(text: str) -> int:
    return len(common.to_eva_sjis(text))


def _fail(entry_label: str, message: str) -> None:
    prefix = f"{entry_label}: " if entry_label else ""
    raise ValueError(prefix + message)


class _DetailTextLayout:
    def __init__(
        self,
        title_max_bytes: int,
        line_max_bytes: int,
        body_lines_per_page: int,
        first_page_prefix: str,
        next_page_prefix: str,
        page_separator: str,
    ):
        self.title_max_bytes = title_max_bytes
        self.line_max_bytes = line_max_bytes
        self.body_lines_per_page = body_lines_per_page
        self.first_page_prefix = first_page_prefix
        self.next_page_prefix = next_page_prefix
        self.page_separator = page_separator


_INFO_LAYOUT = _DetailTextLayout(
    title_max_bytes=INFO_TITLE_MAX_BYTES,
    line_max_bytes=INFO_LINE_MAX_BYTES,
    body_lines_per_page=INFO_BODY_LINES_PER_PAGE,
    first_page_prefix="\n",
    next_page_prefix="\n\n",
    page_separator="$n\n\n",
)

_TUTO_LAYOUT = _DetailTextLayout(
    title_max_bytes=TUTO_TITLE_MAX_BYTES,
    line_max_bytes=TUTO_LINE_MAX_BYTES,
    body_lines_per_page=TUTO_BODY_LINES_PER_PAGE,
    first_page_prefix="",
    next_page_prefix="\n",
    page_separator="$n\n",
)


def _wrap_encoded_line(text: str, max_bytes: int) -> list[str]:
    lines = []
    current = ""
    current_bytes = 0

    for char in text:
        char_bytes = _encoded_length(char)
        if current and current_bytes + char_bytes > max_bytes:
            lines.append(current.rstrip())
            current = ""
            current_bytes = 0
        current += char
        current_bytes += char_bytes

    if current:
        lines.append(current.rstrip())
    return lines or [""]


def _extract_paragraphs(body: str) -> list[str]:
    paragraphs = []
    current = []

    for line in body.replace("$n", "\n\n").split("\n"):
        stripped = line.strip()
        if stripped:
            if not current:
                current.append(line.rstrip())
            else:
                current.append(stripped)
        elif current:
            paragraphs.append("".join(current))
            current = []

    if current:
        paragraphs.append("".join(current))
    return paragraphs


def _paginate_paragraphs(
    paragraphs: list[str],
    line_max_bytes: int,
    lines_per_page: int,
) -> list[list[str]]:
    pages = [[]]

    for paragraph in paragraphs:
        wrapped_lines = _wrap_encoded_line(paragraph, line_max_bytes)
        if pages[-1]:
            remaining_lines = lines_per_page - len(pages[-1])
            if remaining_lines <= 1:
                pages.append([])
            else:
                pages[-1].append("")

        for line in wrapped_lines:
            if len(pages[-1]) >= lines_per_page:
                pages.append([])
            pages[-1].append(line)

    pages = [page for page in pages if page]
    return pages or [[""]]


def _validate_detail_text(
    text: str,
    layout: _DetailTextLayout,
    entry_label: str,
) -> None:
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
    if title_bytes > layout.title_max_bytes:
        _fail(
            entry_label,
            f"title is {title_bytes} encoded bytes; maximum is {layout.title_max_bytes}",
        )

    pages = body.split("$n")
    declared_pages = _FULLWIDTH_PAGE_DIGITS.index(page_count_text) + 1
    if declared_pages != len(pages):
        _fail(
            entry_label,
            f"declares {declared_pages} pages but contains {len(pages)}",
        )

    for page_index, raw_page in enumerate(pages):
        expected_prefix = (
            layout.first_page_prefix if page_index == 0 else layout.next_page_prefix
        )
        if not raw_page.startswith(expected_prefix):
            _fail(
                entry_label,
                f"page {page_index + 1} must begin with the standard blank line",
            )

        is_last_page = page_index == len(pages) - 1
        if is_last_page:
            if not raw_page.endswith("\n"):
                _fail(entry_label, "final page must end with LF")
            content = raw_page[len(expected_prefix) : -1]
        else:
            if raw_page.endswith("\n"):
                _fail(
                    entry_label,
                    f"page {page_index + 1} must place $n directly after its final text",
                )
            content = raw_page[len(expected_prefix) :]

        lines = content.split("\n") if content else []
        if len(lines) > layout.body_lines_per_page:
            _fail(
                entry_label,
                f"page {page_index + 1} has {len(lines)} body lines; "
                f"maximum is {layout.body_lines_per_page}",
            )

        for line_index, line in enumerate(lines, start=1):
            line_bytes = _encoded_length(line)
            if line_bytes > layout.line_max_bytes:
                _fail(
                    entry_label,
                    f"page {page_index + 1}, line {line_index} is "
                    f"{line_bytes} encoded bytes; maximum is {layout.line_max_bytes}",
                )


def _repair_detail_text(
    text: str,
    layout: _DetailTextLayout,
    entry_label: str,
) -> str:
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
    if (
        len(page_count_text) != 1
        or page_count_text not in _FULLWIDTH_PAGE_DIGITS + _ASCII_PAGE_DIGITS
    ):
        _fail(
            entry_label,
            "page count must be one full-width digit from １ to ９",
        )
    if not title:
        _fail(entry_label, "title must not be empty")

    title_bytes = _encoded_length(title)
    if title_bytes > layout.title_max_bytes:
        _fail(
            entry_label,
            f"title is {title_bytes} encoded bytes; maximum is {layout.title_max_bytes}",
        )

    pages = _paginate_paragraphs(
        _extract_paragraphs(body),
        line_max_bytes=layout.line_max_bytes,
        lines_per_page=layout.body_lines_per_page,
    )
    if len(pages) > len(_FULLWIDTH_PAGE_DIGITS):
        _fail(
            entry_label,
            f"reformatted body needs {len(pages)} pages; maximum is 9",
        )

    rendered_pages = ["\n".join(page) for page in pages]
    repaired = (
        f"{_FULLWIDTH_PAGE_DIGITS[len(pages) - 1]}\n"
        f"{title}\n"
        + layout.first_page_prefix
        + layout.page_separator.join(rendered_pages)
        + "\n"
    )
    _validate_detail_text(repaired, layout=layout, entry_label=entry_label)
    return repaired


def _normalize_detail_text(
    text: str,
    layout: _DetailTextLayout,
    entry_label: str,
) -> tuple[str, bool]:
    try:
        _validate_detail_text(text, layout=layout, entry_label=entry_label)
        return text, False
    except ValueError:
        repaired = _repair_detail_text(text, layout=layout, entry_label=entry_label)
        return repaired, repaired != text


def validate_info_text(text: str, entry_label: str = "") -> None:
    """Validate f2info text without changing translator-controlled layout."""
    _validate_detail_text(text, layout=_INFO_LAYOUT, entry_label=entry_label)


def repair_info_text(text: str, entry_label: str = "") -> str:
    """Rebuild f2info body layout while preserving title and body wording."""
    return _repair_detail_text(text, layout=_INFO_LAYOUT, entry_label=entry_label)


def normalize_info_text(text: str, entry_label: str = "") -> tuple[str, bool]:
    """Return valid f2info text unchanged, otherwise safely reformat it."""
    return _normalize_detail_text(text, layout=_INFO_LAYOUT, entry_label=entry_label)


def validate_tuto_text(text: str, entry_label: str = "") -> None:
    """Validate f2tuto detail text without changing translator-controlled layout."""
    _validate_detail_text(text, layout=_TUTO_LAYOUT, entry_label=entry_label)


def repair_tuto_text(text: str, entry_label: str = "") -> str:
    """Rebuild f2tuto body layout while preserving title and body wording."""
    return _repair_detail_text(text, layout=_TUTO_LAYOUT, entry_label=entry_label)


def normalize_tuto_text(text: str, entry_label: str = "") -> tuple[str, bool]:
    """Return valid f2tuto text unchanged, otherwise safely reformat it."""
    return _normalize_detail_text(text, layout=_TUTO_LAYOUT, entry_label=entry_label)
