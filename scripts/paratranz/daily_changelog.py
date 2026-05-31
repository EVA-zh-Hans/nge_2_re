"""Generate a Paratranz changelog with an LLM.

Usage:
    .venv/bin/python scripts/paratranz/daily_changelog.py
    .venv/bin/python scripts/paratranz/daily_changelog.py --since "2026-05-31 00:00" --until "2026-05-31 23:59"
    .venv/bin/python scripts/paratranz/daily_changelog.py --since "2026-05-31T00:00:00+08:00" --image-out out.png

Required LLM config:
    OAI_BASE_URL or OPENAI_BASE_URL
    OAI_API_KEY or OPENAI_API_KEY
    OAI_MODEL or OPENAI_MODEL

Time range:
    --since and --until accept ISO-like values such as:
      2026-05-31
      2026-05-31 00:00
      2026-05-31T00:00:00+08:00
    Values without a timezone are interpreted as Asia/Shanghai time.
    If both are omitted, the script summarizes the most recent 24 hours.

Output:
    The generated Markdown changelog is printed to stdout.
    PNG poster output is disabled by default; pass --image-out to generate one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_PROJECT_ID = 10882
PAGE_SIZE = 200
LLM_MAX_ITEMS = 200
DEFAULT_RANGE_HOURS = 24


def _local_tz() -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Asia/Shanghai")
    except Exception:
        return dt.timezone(dt.timedelta(hours=8), name="Asia/Shanghai")


def _now_local() -> dt.datetime:
    return dt.datetime.now(_local_tz())


def _parse_iso_z(s: str) -> dt.datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s)


def _parse_user_time(value: str, *, default_tz: dt.tzinfo) -> dt.datetime:
    value = value.strip()
    if not value:
        raise ValueError("empty time value")

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        parsed = dt.datetime.fromisoformat(value + "T00:00:00")
    else:
        parsed = dt.datetime.fromisoformat(value.replace(" ", "T", 1))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed


def _resolve_time_range(since_arg: str | None, until_arg: str | None) -> tuple[dt.datetime, dt.datetime]:
    tz_local = _local_tz()
    now = _now_local()

    until = _parse_user_time(until_arg, default_tz=tz_local) if until_arg else now
    since = (
        _parse_user_time(since_arg, default_tz=tz_local)
        if since_arg
        else until - dt.timedelta(hours=DEFAULT_RANGE_HOURS)
    )

    if since >= until:
        raise ValueError("--since must be earlier than --until")
    return since, until


def _truncate_one_line(s: str, max_len: int) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)] + "…"


def _http_get_json(url: str, headers: dict[str, str] | None = None, timeout_s: int = 30):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        raw = r.read()
    return json.loads(raw)


def _http_post_json(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout_s: int = 90,
):
    body = json.dumps(payload).encode("utf-8")
    req_headers = {"content-type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        raw = r.read()
    return json.loads(raw)


def _fetch_history_between(project_id: int, since_utc: dt.datetime, until_utc: dt.datetime) -> list[dict]:
    base = f"https://paratranz.cn/api/projects/{project_id}/history"
    out: list[dict] = []
    page = 1

    while True:
        url = base + "?" + urllib.parse.urlencode({"page": page, "pageSize": PAGE_SIZE})
        data = _http_get_json(url, headers={"accept": "application/json"})
        results = data.get("results") or []
        if not isinstance(results, list) or not results:
            break

        for item in results:
            created_at = item.get("createdAt")
            if not isinstance(created_at, str):
                continue
            try:
                created_dt = _parse_iso_z(created_at)
            except Exception:
                continue
            if since_utc <= created_dt <= until_utc:
                out.append(item)

        last_created_at = results[-1].get("createdAt")
        try:
            last_dt = _parse_iso_z(last_created_at) if isinstance(last_created_at, str) else None
        except Exception:
            last_dt = None
        if last_dt is not None and last_dt < since_utc:
            break

        page += 1
        if page > 5000:
            raise RuntimeError("Paratranz history pagination exceeded 5000 pages")

    out.sort(key=lambda x: x.get("createdAt") or "")
    return out


def _display_name(user: dict | None, uid) -> str:
    if isinstance(user, dict):
        nickname = user.get("nickname")
        if isinstance(nickname, str) and nickname.strip():
            return nickname.strip()
        username = user.get("username")
        if isinstance(username, str) and username.strip():
            return username.strip()
    return f"uid:{uid}"


def _counts_by_user(items: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        user = item.get("user") if isinstance(item.get("user"), dict) else None
        name = _display_name(user, item.get("uid"))
        counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _compact_changes(items: list[dict]) -> list[dict]:
    items_sorted = sorted(items, key=lambda x: x.get("createdAt") or "", reverse=True)
    compact: list[dict] = []
    for item in items_sorted[:LLM_MAX_ITEMS]:
        user = item.get("user") if isinstance(item.get("user"), dict) else None
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        compact.append(
            {
                "user": _display_name(user, item.get("uid")),
                "createdAt": item.get("createdAt") or "",
                "field": item.get("field") or "",
                "key": target.get("key") or "",
                "original": _truncate_one_line(target.get("original") or "", 220)
                if isinstance(target.get("original"), str)
                else "",
                "from": _truncate_one_line(item.get("from") or "", 220)
                if isinstance(item.get("from"), str)
                else "",
                "to": _truncate_one_line(item.get("to") or "", 220) if isinstance(item.get("to"), str) else "",
            }
        )
    return compact


def _resolve_oai_endpoint(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        return base_url + "/chat/completions"
    return base_url + "/v1/chat/completions"


def _generate_changelog_via_oai(
    base_url: str,
    api_key: str,
    model: str,
    prompt_payload: dict,
) -> str:
    endpoint = _resolve_oai_endpoint(base_url)
    headers = {"authorization": f"Bearer {api_key}"}
    req = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个资深发布经理。请根据提供的翻译改动记录，输出中文 Markdown 更新日志。\n\n"
                    "要求：\n"
                    "1) 标题使用 `# 更新日志`。\n"
                    "2) 分为“修改/润色/修正/杂项”四个小节；没有内容的小节可以省略。\n"
                    "3) 每条以动词开头，尽量合并同类项，但不要丢失责任归属。\n"
                    "4) 每条末尾必须标注贡献者，格式固定为：`（by <name>）`；多人用 `/` 分隔。\n"
                    "5) 信息不足时宁可保守，不要编造未给出的上下文。\n"
                    "6) 不要输出贡献者统计，程序会在末尾追加。"
                ),
            },
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
        ],
        "temperature": 0.2,
    }
    resp = _http_post_json(endpoint, req, headers=headers)
    try:
        content = resp["choices"][0]["message"]["content"]
    except Exception as e:
        raise RuntimeError(f"LLM response format error: {json.dumps(resp, ensure_ascii=False)[:2000]}") from e
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM returned empty content")
    return content.strip()


def _append_contributor_stats(changelog_md: str, contributors: list[tuple[str, int]]) -> str:
    lines = [changelog_md.rstrip(), "", "## 贡献者修改统计"]
    if not contributors:
        lines.append("- 无修改")
    else:
        for name, count in contributors:
            lines.append(f"- {name}: {count} 条")
    return "\n".join(lines).rstrip()


def _write_changelog_image(
    path: str,
    title_date: str,
    changelog_md: str,
    contributors: list[tuple[str, int]],
    size: tuple[int, int] = (1080, 1440),
):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        raise RuntimeError(f"Missing Pillow dependency: {e}") from e

    w, h = size
    img = Image.new("RGB", (w, h), "#0B1220")
    draw = ImageDraw.Draw(img)

    def try_font(size_px: int, idx: int = 0):
        candidates: list[tuple[str, int]] = [
            ("./resources/assets/font/ChillRoundFBold.ttf", 0),
            ("/System/Library/Fonts/STHeiti Medium.ttc", 1),
            ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
            ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
            ("/Library/Fonts/Arial Unicode.ttf", 0),
        ]
        for fp, i in candidates:
            try:
                if os.path.exists(fp):
                    return ImageFont.truetype(fp, size_px, index=i)
            except Exception:
                continue
        return ImageFont.load_default()

    def text_w(s: str, font) -> int:
        left, _top, right, _bottom = draw.textbbox((0, 0), s, font=font)
        return right - left

    def line_h(font) -> int:
        _left, top, _right, bottom = draw.textbbox((0, 0), "国Ag", font=font)
        return (bottom - top) + 8

    def wrap(s: str, font, max_width: int) -> list[str]:
        s = s.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not s:
            return [""]
        out: list[str] = []
        cur = ""
        for ch in s:
            nxt = cur + ch
            if text_w(nxt, font) <= max_width or not cur:
                cur = nxt
                continue
            out.append(cur)
            cur = ch
        if cur:
            out.append(cur)
        return out

    def ellipsize(s: str, font, max_width: int) -> str:
        if text_w(s, font) <= max_width:
            return s
        ell = "…"
        while s and text_w(s + ell, font) > max_width:
            s = s[:-1]
        return (s + ell) if s else ell

    margin = 64
    font_title = try_font(56, idx=1)
    font_sub = try_font(26)
    font_h2 = try_font(34, idx=1)
    font_body = try_font(26)
    font_small = try_font(22)

    draw.text((margin, 56), f"Changelog · {title_date}", font=font_title, fill="#E5E7EB")
    draw.text((margin, 128), "NGE2 本地化更新日志", font=font_sub, fill="#9CA3AF")

    card_y = 190
    draw.rounded_rectangle((margin, card_y, w - margin, h - margin), radius=28, fill="#0F172A", outline="#1F2937", width=2)

    x = margin + 36
    y = card_y + 36
    max_w = w - margin * 2 - 72
    content_bottom = h - margin
    footer_top = content_bottom - 220

    lines = changelog_md.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    in_code = False
    for raw in lines:
        if y > footer_top:
            draw.text((x, y), "…", font=font_h2, fill="#9CA3AF")
            break

        s = raw.rstrip()
        if not s.strip():
            y += 10
            continue
        if s.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if s.strip().startswith("#") and "贡献者" in s:
            break

        if s.startswith("# "):
            text = s[2:].strip()
            font = font_h2
            fill = "#E5E7EB"
            max_lines = 1
        elif s.startswith("## "):
            text = s[3:].strip()
            font = font_h2
            fill = "#E5E7EB"
            max_lines = 1
        elif s.startswith("- "):
            text = "• " + s[2:].strip()
            font = font_body
            fill = "#E5E7EB"
            max_lines = 3
        else:
            text = s
            font = font_body
            fill = "#E5E7EB"
            max_lines = 2

        wrapped = wrap(text, font, max_w)
        if len(wrapped) > max_lines:
            wrapped = wrapped[:max_lines]
            wrapped[-1] = ellipsize(wrapped[-1], font, max_w)
        for line in wrapped:
            draw.text((x, y), line, font=font, fill=fill)
            y += line_h(font)
        y += 6

    y_footer = footer_top + 24
    draw.text((x, y_footer), "贡献者", font=font_h2, fill="#E5E7EB")
    y_footer += line_h(font_h2) + 6
    if contributors:
        joined = " · ".join(f"{name}({count})" for name, count in contributors)
        wrapped = wrap(joined, font_body, max_w)
        for line in wrapped[:2]:
            draw.text((x, y_footer), line, font=font_body, fill="#CBD5E1")
            y_footer += line_h(font_body)
    else:
        draw.text((x, y_footer), "（无）", font=font_body, fill="#CBD5E1")

    draw.text((margin + 36, h - margin - 34), "Generated by scripts/paratranz/daily_changelog.py", font=font_small, fill="#6B7280")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    img.save(path, format="PNG", optimize=True)


def _build_payload(
    project_id: int,
    since_local: dt.datetime,
    until_local: dt.datetime,
    changes: list[dict],
) -> dict:
    since_utc = since_local.astimezone(dt.timezone.utc)
    until_utc = until_local.astimezone(dt.timezone.utc)
    counts = _counts_by_user(changes)
    return {
        "projectId": project_id,
        "rangeLocal": {"since": since_local.isoformat(), "until": until_local.isoformat(), "timezone": "Asia/Shanghai"},
        "rangeUtc": {"since": since_utc.isoformat(), "until": until_utc.isoformat()},
        "totalChanges": len(changes),
        "countsByUser": [{"user": user, "count": count} for user, count in counts],
        "changes": _compact_changes(changes),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate a Paratranz changelog with an LLM.")
    parser.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID)
    parser.add_argument("--since", default=None, help="Start time; timezone-less values are Asia/Shanghai.")
    parser.add_argument("--until", default=None, help="End time; timezone-less values are Asia/Shanghai.")
    parser.add_argument("--image-out", default=None, help="Optional PNG poster output path.")
    parser.add_argument("--oai-base-url", default=os.environ.get("OAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--oai-api-key", default=os.environ.get("OAI_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--oai-model", default=os.environ.get("OAI_MODEL") or os.environ.get("OPENAI_MODEL"))
    args = parser.parse_args(argv)

    if not args.oai_base_url or not args.oai_api_key or not args.oai_model:
        print(
            "Missing LLM config: set OAI_BASE_URL/OAI_API_KEY/OAI_MODEL "
            "or OPENAI_BASE_URL/OPENAI_API_KEY/OPENAI_MODEL.",
            file=sys.stderr,
        )
        return 2

    try:
        since_local, until_local = _resolve_time_range(args.since, args.until)
    except Exception as e:
        print(f"Invalid time range: {e}", file=sys.stderr)
        return 2

    since_utc = since_local.astimezone(dt.timezone.utc)
    until_utc = until_local.astimezone(dt.timezone.utc)

    try:
        changes = _fetch_history_between(args.project_id, since_utc=since_utc, until_utc=until_utc)
    except Exception as e:
        print(f"Failed to fetch Paratranz history for project {args.project_id}: {e}", file=sys.stderr)
        return 2

    contributors = _counts_by_user(changes)
    payload = _build_payload(args.project_id, since_local, until_local, changes)

    try:
        changelog = _generate_changelog_via_oai(
            base_url=args.oai_base_url,
            api_key=args.oai_api_key,
            model=args.oai_model,
            prompt_payload=payload,
        )
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(e)
        print(f"LLM request failed: HTTP {e.code}\n{body}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"LLM request failed: {e}", file=sys.stderr)
        return 2

    changelog = _append_contributor_stats(changelog, contributors)
    print(changelog)

    if args.image_out:
        try:
            _write_changelog_image(
                os.path.abspath(args.image_out),
                title_date=until_local.strftime("%Y-%m-%d"),
                changelog_md=changelog,
                contributors=contributors,
            )
        except Exception as e:
            print(f"Failed to generate changelog image: {e}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
