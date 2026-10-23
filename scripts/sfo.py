import argparse
import struct
from pathlib import Path


PSF_MAGIC = b"\x00PSF"
PSF_HEADER = struct.Struct("<4sIIII")
PSF_ENTRY = struct.Struct("<HHIII")
PSF_TYPE_STRING = 0x0204
PSF_TYPE_UINT32 = 0x0404
DEFAULT_TITLE = "新世纪福音战士２ 被创造的世界"


class SfoEditor:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = bytearray(self.path.read_bytes())
        self.entries = self._parse_entries()

    def _parse_entries(self):
        if len(self.data) < PSF_HEADER.size:
            raise ValueError("PARAM.SFO is too short")

        magic, _, key_table, data_table, count = PSF_HEADER.unpack_from(self.data)
        if magic != PSF_MAGIC:
            raise ValueError("invalid PARAM.SFO magic")

        index_end = PSF_HEADER.size + count * PSF_ENTRY.size
        if index_end > len(self.data) or not index_end <= key_table <= data_table:
            raise ValueError("invalid PARAM.SFO table offsets")

        entries = {}
        for index in range(count):
            index_offset = PSF_HEADER.size + index * PSF_ENTRY.size
            key_offset, data_type, data_len, max_len, data_offset = (
                PSF_ENTRY.unpack_from(self.data, index_offset)
            )
            key_start = key_table + key_offset
            if not key_table <= key_start < data_table:
                raise ValueError("invalid PARAM.SFO key offset")
            key_end = self.data.find(b"\x00", key_start, data_table)
            if key_end < 0:
                raise ValueError("unterminated PARAM.SFO key")

            value_start = data_table + data_offset
            value_end = value_start + max_len
            if value_start < data_table or value_end > len(self.data):
                raise ValueError("invalid PARAM.SFO value offset")
            if data_len > max_len:
                raise ValueError("PARAM.SFO value length exceeds its capacity")

            try:
                name = self.data[key_start:key_end].decode("ascii")
            except UnicodeDecodeError as error:
                raise ValueError("PARAM.SFO key is not ASCII") from error

            entries[name] = {
                "type": data_type,
                "length": data_len,
                "capacity": max_len,
                "value_offset": value_start,
                "index_offset": index_offset,
            }
        return entries

    def get_value(self, name):
        entry = self._entry(name)
        offset = entry["value_offset"]
        if entry["type"] == PSF_TYPE_UINT32:
            if entry["length"] != 4:
                raise ValueError(f"invalid integer length for {name}")
            return struct.unpack_from("<I", self.data, offset)[0]

        raw = self.data[offset : offset + entry["length"]]
        return bytes(raw).rstrip(b"\x00").decode("utf-8")

    def set_string(self, name, value):
        entry = self._entry(name)
        if entry["type"] != PSF_TYPE_STRING:
            raise ValueError(f"{name} is not a string field")

        encoded = value.encode("utf-8") + b"\x00"
        if len(encoded) > entry["capacity"]:
            raise ValueError(
                f"{name} needs {len(encoded)} bytes, but only "
                f"{entry['capacity']} are available"
            )

        offset = entry["value_offset"]
        capacity = entry["capacity"]
        self.data[offset : offset + capacity] = b"\x00" * capacity
        self.data[offset : offset + len(encoded)] = encoded
        struct.pack_into("<I", self.data, entry["index_offset"] + 4, len(encoded))
        entry["length"] = len(encoded)

    def save(self, output: Path):
        Path(output).write_bytes(self.data)

    def _entry(self, name):
        try:
            return self.entries[name]
        except KeyError as error:
            raise KeyError(f"PARAM.SFO does not contain {name}") from error


def build_cli():
    parser = argparse.ArgumentParser(description="Update a PSP PARAM.SFO title")
    parser.add_argument("file", type=Path, help="source PARAM.SFO")
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    return parser


def main():
    args = build_cli().parse_args()
    editor = SfoEditor(args.file)
    editor.set_string("TITLE", args.title)
    editor.save(args.output)
    print(f"Saved PARAM.SFO: {args.output}")


if __name__ == "__main__":
    main()
