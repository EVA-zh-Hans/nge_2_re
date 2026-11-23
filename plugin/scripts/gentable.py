"""
从GB2312编码与追加字符表生成自定义编码的映射表，并将其转换为UTF-16编码的二进制文件。
避开低字节 0x00 ('\\0')、0x0A ('\\n')、0x25 ('%')。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import argparse
import json

DEFAULT_EXTRA_CHARS = Path(__file__).resolve().parent.parent / "assets" / "extra_chars.txt"
CUSTOM_FIRST = 0xA600
CUSTOM_LAST = 0xDDFF
RESERVED_LOW_BYTES = frozenset((0x00, 0x0A, 0x25))


@dataclass
class Entry:
    """
    映射表条目类，包含字符、UTF-16编码和自定义编码。
    """

    char: str
    utf16_hex: str
    custom_code: str


def _is_shift_jis_encodable(char: str) -> bool:
    try:
        char.encode("shift_jis")
    except UnicodeEncodeError:
        return False
    return True


def _encode_bmp_utf16le(char: str) -> bytes:
    utf16_bytes = char.encode("utf-16le")
    if len(utf16_bytes) != 2:
        raise ValueError(
            f"Character {char!r} (U+{ord(char):04X}) requires a UTF-16 surrogate pair "
            "and cannot fit in the 16-bit PSP table"
        )
    return utf16_bytes


def load_extra_chars(path: Path) -> list[str]:
    """
    读取追加字符表：每行一个字符，空行和以 # 开头的行会被忽略。

    可直接放入完整字表（例如《通用规范汉字表》8105 字）并在末尾追加项目
    需要的额外字符；加载时会自动：
    - 跳过已重复的字符（保留首次出现顺序）
    - 跳过原生 Shift_JIS 可编码的字符
    - 跳过非 BMP 字符（> U+FFFF，PSP 的 uint16_t 码表无法表示）
    - 与 GB2312 区重复的字符会在 gb2312_to_custom 中自动去重跳过

    注意：已有条目请勿重排或删除，新增字符请追加到文件末尾以保持码位稳定。
    """
    chars: list[str] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) != 1:
            raise ValueError(f"{path}:{lineno}: expected one character, got {line!r}")
        if line in seen:
            continue
        seen.add(line)
        if len(line.encode("utf-16le")) != 2:
            continue
        if _is_shift_jis_encodable(line):
            continue
        chars.append(line)
    return chars


def gb2312_to_custom(f, extra_chars: list[str] | None = None):
    """
    生成映射表并写入 JSON 文件，返回 UTF-16LE 编码的字节序列列表。

    GB2312 区之后依次追加 extra_chars（自动跳过已在 GB2312 区或已追加过的字符）。
    """
    utf16s: list[bytes] = []
    mappings: list[Entry] = []
    seen: set[str] = set()

    # 映射表空间为 0xA600-0xDDFF，避开低字节 0x00、0x0A、0x25。
    i = 0
    custom_code = CUSTOM_FIRST

    def append_char(unicode_char: str) -> None:
        nonlocal i, custom_code
        utf16_bytes = _encode_bmp_utf16le(unicode_char)

        while (i % 0x100) in RESERVED_LOW_BYTES:
            i += 1
            utf16s.append(b"\x00\x00")

        custom_code = CUSTOM_FIRST + i
        if custom_code > CUSTOM_LAST:
            raise ValueError(
                f"Custom code space exhausted at {unicode_char!r} ({hex(custom_code)} > {hex(CUSTOM_LAST)})"
            )

        utf16s.append(utf16_bytes)
        mappings.append(Entry(unicode_char, utf16_bytes.hex(), hex(custom_code)))
        seen.add(unicode_char)
        i += 1

    # 遍历所有可能的第一个字节
    for first_byte in range(0xA1, 0xF8):
        # 遍历所有可能的第二个字节
        for second_byte in range(0xA1, 0xFF):
            # 组合成一个 GB2312 编码的字节序列
            gb2312_bytes = bytes([first_byte, second_byte])

            try:
                # 将 GB2312 编码的字节序列解码为 Unicode 字符
                unicode_char = gb2312_bytes.decode(
                    "gbk"
                )  # GB2312 会将破折号映射为 U+2015 (HORIZONTAL BAR), 而 GBK 映射到 U+2014 与现在输入法行为相符。
            except UnicodeDecodeError:
                # 跳过无效的 GB2312 编码
                continue

            append_char(unicode_char)

    for unicode_char in extra_chars or []:
        if unicode_char in seen:
            continue
        append_char(unicode_char)

    json.dump([asdict(entry) for entry in mappings], f, ensure_ascii=False, indent=4)

    print(f"Used Space: {hex(CUSTOM_FIRST)}-{hex(custom_code)}")
    return utf16s


def write_python_map(map_json: Path, output_path: Path):
    """把 JSON 映射表写成 app/utils/map.py（PC 端编码使用的同一份表）。"""
    entries = json.loads(map_json.read_text(encoding="utf-8"))
    lines = ["CUSTOM_ENCODE_MAP = ["]
    for entry in entries:
        fields = ", ".join(
            f"{json.dumps(key)}: {json.dumps(entry[key], ensure_ascii=False)}"
            for key in ("char", "utf16_hex", "custom_code")
        )
        lines.append(f"    {{{fields}}},")
    lines.append("]")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write("\n".join(lines) + "\n")


def write_to_utf16_binary(utf16s: list[bytes], output_path: Path):
    # 打开文件以写入二进制映射表
    with output_path.open("wb") as f:
        # 遍历所有可能的第一个字节
        for utf16_bytes in utf16s:
            # 写入 UTF-16 编码到文件
            f.write(utf16_bytes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate the GB2312 custom-code UTF-16 table."
    )
    parser.add_argument(
        "--out-bin",
        type=Path,
        default=Path("GB2312_CUSTOM.BIN"),
        help="Output binary table path.",
    )
    parser.add_argument(
        "--out-map",
        type=Path,
        default=Path("GB2312_Custom_Map.json"),
        help="Output mapping JSON path.",
    )
    parser.add_argument(
        "--extra-chars",
        type=Path,
        default=DEFAULT_EXTRA_CHARS,
        help="Append-only list of non-GB2312 characters (one per line).",
    )
    parser.add_argument(
        "--out-py",
        type=Path,
        default=None,
        help="Also write the PC-side Python table (app/utils/map.py).",
    )
    args = parser.parse_args()

    args.out_bin.parent.mkdir(parents=True, exist_ok=True)
    args.out_map.parent.mkdir(parents=True, exist_ok=True)

    # 打开文件以写入映射表
    with args.out_map.open("w", encoding="utf-8") as f:
        # 调用函数生成映射表
        map_bytes = gb2312_to_custom(f, load_extra_chars(args.extra_chars))

    print(f"{len(map_bytes)} characters generated.")

    # 调用函数生成二进制映射表
    write_to_utf16_binary(map_bytes, args.out_bin)

    if args.out_py is not None:
        write_python_map(args.out_map, args.out_py)
