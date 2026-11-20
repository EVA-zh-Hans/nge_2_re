"""
从GB2312编码生成自定义编码的映射表，并将其转换为UTF-16编码的二进制文件。
注意避开0x25编码
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import argparse
import json

DEFAULT_EXTRA_CHARS = Path(__file__).resolve().parent.parent / "assets" / "extra_chars.txt"


@dataclass
class Entry:
    """
    映射表条目类，包含字符、UTF-16编码和自定义编码。
    """

    char: str
    utf16_hex: str
    custom_code: str


def load_extra_chars(path: Path) -> list[str]:
    """
    读取追加字符表：每行一个字符，空行和以 # 开头的行会被忽略。

    这些字符不在 GB2312 范围内（例如 GBK 扩展区的“啰”），会按文件顺序
    追加到 GB2312 区之后。只能在文件末尾追加，不能插入、删除或重排，
    否则已有字符的自定义编码会改变。
    """
    chars: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) != 1:
            raise ValueError(f"{path}:{lineno}: expected one character, got {line!r}")
        try:
            line.encode("shift_jis")
        except UnicodeEncodeError:
            pass
        else:
            raise ValueError(
                f"{path}:{lineno}: {line!r} is already Shift_JIS encodable"
            )
        if line in chars:
            raise ValueError(f"{path}:{lineno}: duplicate character {line!r}")
        chars.append(line)
    return chars


def gb2312_to_custom(f, extra_chars: list[str] | None = None):
    """
    生成映射表并打印到文件，返回UTF16编码的字节序列列表。
    映射表的格式为：
    ```
    字符\tUTF-16编码\t自定义编码
    ```
    GB2312 区之后依次追加 extra_chars。
    """
    utf16s = []
    mappings = []
    seen: set[str] = set()

    # 映射表的空间很大，不需要考虑大小问题，只用避开 0x25 和 0x00 即可。
    i = 0
    custom_code = 0xA600
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

                # 将 Unicode 字符编码为 UTF-16
                utf16_bytes = unicode_char.encode("utf-16le")

                if (i % 0x100) == 0x25 or (i % 0x100 == 0x00):
                    # 跳过 0x25 ('%') 和 0x00 ('\0')
                    i += 1
                    utf16s.append(b"\x00\x00")

                custom_code = 0xA600 + i

                # 将映射条目添加到列表中
                utf16s.append(utf16_bytes)

                mappings.append(
                    Entry(unicode_char, utf16_bytes.hex(), hex(custom_code))
                )
                seen.add(unicode_char)

                i += 1
            except UnicodeDecodeError:
                # 跳过无效的 GB2312 编码
                continue

    for unicode_char in extra_chars or []:
        if unicode_char in seen:
            raise ValueError(f"{unicode_char!r} is already in the GB2312 block")
        utf16_bytes = unicode_char.encode("utf-16le")

        if (i % 0x100) == 0x25 or (i % 0x100 == 0x00):
            i += 1
            utf16s.append(b"\x00\x00")

        custom_code = 0xA600 + i
        utf16s.append(utf16_bytes)
        mappings.append(Entry(unicode_char, utf16_bytes.hex(), hex(custom_code)))
        i += 1

    json.dump([asdict(entry) for entry in mappings], f, ensure_ascii=False, indent=4)

    print(f"Used Space: 0xa600-{hex(custom_code)}")
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
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


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
