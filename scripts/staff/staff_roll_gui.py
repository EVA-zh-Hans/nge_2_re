import base64
import io
import os
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None
    ttk = None


ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.parser.tools import png as png_mod


SCREEN_W = 480
SCREEN_H = 272
ROW_H = 24
SPAWN_Y = 280.0
FPS = 60
TOTAL_FRAMES = 60 * 88


@dataclass(frozen=True)
class StaffScrollCmd:
    ctrl: int
    row_left: int
    row_right: int

    @property
    def end_flag(self) -> bool:
        return (self.ctrl & 1) != 0

    @property
    def align(self) -> int:
        return (self.ctrl >> 1) & 7

    @property
    def pixel_gap(self) -> int:
        return (self.ctrl >> 4) & 0xFFFF

    @property
    def has_separator(self) -> bool:
        return ((self.ctrl >> 20) & 1) != 0


def _decode_alpha(encoded_alpha: int) -> int:
    return min(encoded_alpha << 1, 0xFF)


def _read_u8(f: io.BufferedIOBase) -> int:
    b = f.read(1)
    if not b:
        raise EOFError
    return b[0]


def _read_u16(f: io.BufferedIOBase) -> int:
    return struct.unpack("<H", f.read(2))[0]


def _read_u32(f: io.BufferedIOBase) -> int:
    return struct.unpack("<I", f.read(4))[0]


def _align(n: int, a: int) -> int:
    return a * ((n + a - 1) // a)


def _decompress_zipped(path: Path) -> bytes:
    b = path.read_bytes()
    if len(b) < 4:
        raise ValueError(f"bad zipped file: {path}")
    raw = b[4:]
    out = zlib.decompress(raw, -15)
    return out


def _decode_hgpt_rgba(hgpt_bytes: bytes) -> tuple[int, int, bytes]:
    f = io.BytesIO(hgpt_bytes)
    magic = f.read(4)
    if magic != b"HGPT":
        raise ValueError("not HGPT")

    pp_offset = _read_u16(f)
    has_extended_header = _read_u16(f)
    number_of_divisions = _read_u16(f)
    _unknown_one = _read_u16(f)
    _unknown_two = _read_u32(f)

    if has_extended_header:
        number_of_divisions_repeat = _read_u16(f)
        if number_of_divisions_repeat != number_of_divisions:
            raise ValueError("HGPT divisions mismatch")
        _unknown_three = _read_u16(f)
        _division_name = f.read(8)
        for _ in range(number_of_divisions):
            f.read(8)
        divisions_size = 12 + 8 * number_of_divisions
        divisions_padded_size = _align(divisions_size, 16)
        f.seek(divisions_padded_size - divisions_size, os.SEEK_CUR)

    f.seek(pp_offset, os.SEEK_SET)

    pp_header = _read_u32(f)
    if (pp_header & 0xFFFF) != 0x7070:
        raise ValueError("missing pp header")

    pp_format = (pp_header >> 16) & 0xFFFF
    if pp_format not in (0x13, 0x14, 0x8800):
        raise ValueError(f"unknown pp_format: {pp_format:#x}")

    if pp_format == 0x8800:
        bytes_per_pixel = 4
        bytes_per_pixel_ppd_size = 1
        tile_width = 4
    elif pp_format == 0x13:
        bytes_per_pixel = 1
        bytes_per_pixel_ppd_size = 1
        tile_width = 16
    else:
        bytes_per_pixel = 0.5
        bytes_per_pixel_ppd_size = 0.5
        tile_width = 32

    width = _read_u16(f)
    height = _read_u16(f)
    f.seek(8, os.SEEK_CUR)

    ppd_header = _read_u32(f)
    if (ppd_header & 0x00FFFFFF) != 0x00647070:
        raise ValueError("missing ppd header")

    ppd_format = (ppd_header >> 24) & 0xFF
    if ppd_format != (pp_format & 0xFF):
        raise ValueError("ppd format mismatch")

    ppd_display_width = _read_u16(f)
    ppd_display_height = _read_u16(f)
    if ppd_display_width != width or ppd_display_height != height:
        raise ValueError("display mismatch")

    f.seek(4, os.SEEK_CUR)

    ppd_sixteenths_width = _read_u16(f)
    ppd_sixteenths_height = _read_u16(f)
    if ppd_sixteenths_width != _align(width, 16) or ppd_sixteenths_height != _align(height, 8):
        raise ValueError("sixteenths mismatch")

    ppd_size = _read_u32(f)

    storage_width = _align(width, tile_width)
    storage_height = _align(height, 8)
    number_of_pixels = storage_width * storage_height
    calculated_ppd_size = int(number_of_pixels * bytes_per_pixel_ppd_size) + 0x20
    if calculated_ppd_size != ppd_size:
        raise ValueError("ppd_size mismatch")

    number_of_bytes = int(number_of_pixels * bytes_per_pixel)
    f.seek(12, os.SEEK_CUR)

    tiled = [0] * number_of_pixels
    cache_last = 0
    remaining = number_of_bytes

    if pp_format == 0x13:
        for i in range(number_of_pixels):
            if remaining <= 0:
                break
            tiled[i] = _read_u8(f)
            remaining -= 1
    elif pp_format == 0x14:
        for i in range(number_of_pixels):
            if remaining <= 0:
                break
            if (i & 1) == 0:
                cache_last = _read_u8(f)
            else:
                remaining -= 1
            tiled[i] = cache_last & 0xF
            cache_last >>= 4
    else:
        for i in range(number_of_pixels):
            if remaining <= 0:
                break
            r = _read_u8(f)
            g = _read_u8(f)
            b = _read_u8(f)
            a = _decode_alpha(_read_u8(f))
            tiled[i] = (r, g, b, a)
            remaining -= 4

    if remaining > 0:
        f.seek(remaining, os.SEEK_CUR)

    content: list[int] | list[tuple[int, int, int, int]] = [0] * (width * height)
    tile_height = 8
    tile_size = tile_width * tile_height
    tile_row = tile_size * (storage_width // tile_width)
    for y in range(height):
        tile_y = y // tile_height
        tile_sub_y = y % tile_height
        base_row = tile_y * tile_row + tile_sub_y * tile_width
        for x in range(width):
            tile_x = x // tile_width
            tile_sub_x = x % tile_width
            content[y * width + x] = tiled[base_row + tile_x * tile_size + tile_sub_x]

    palette: list[tuple[int, int, int, int]] = []
    if pp_format != 0x8800:
        ppc_header = _read_u32(f)
        if ppc_header != 0x00637070:
            raise ValueError("missing ppc header")
        f.seek(2, os.SEEK_CUR)
        palette_total = _read_u16(f) * 8
        f.seek(8, os.SEEK_CUR)
        for _ in range(palette_total):
            r = _read_u8(f)
            g = _read_u8(f)
            b = _read_u8(f)
            a = _decode_alpha(_read_u8(f))
            palette.append((r, g, b, a))

    rgba = bytearray(width * height * 4)
    if pp_format == 0x8800:
        for i, px in enumerate(content):  # type: ignore[assignment]
            o = i * 4
            rgba[o] = px[0]
            rgba[o + 1] = px[1]
            rgba[o + 2] = px[2]
            rgba[o + 3] = px[3]
    else:
        for i, idx in enumerate(content):  # type: ignore[assignment]
            o = i * 4
            if 0 <= idx < len(palette):
                r, g, b, a = palette[idx]
            else:
                r = g = b = a = 0
            rgba[o] = r
            rgba[o + 1] = g
            rgba[o + 2] = b
            rgba[o + 3] = a

    return width, height, bytes(rgba)


def _hgpt_divisions(hgpt_bytes: bytes) -> list[tuple[int, int, int, int]]:
    f = io.BytesIO(hgpt_bytes)
    magic = f.read(4)
    if magic != b"HGPT":
        raise ValueError("not HGPT")

    pp_offset = _read_u16(f)
    has_extended_header = _read_u16(f)
    number_of_divisions = _read_u16(f)
    _unknown_one = _read_u16(f)
    _unknown_two = _read_u32(f)

    if not has_extended_header:
        return []

    number_of_divisions_repeat = _read_u16(f)
    if number_of_divisions_repeat != number_of_divisions:
        raise ValueError("HGPT divisions mismatch")
    f.seek(2, os.SEEK_CUR)
    f.seek(8, os.SEEK_CUR)

    divs: list[tuple[int, int, int, int]] = []
    for _ in range(number_of_divisions):
        x = _read_u16(f)
        y = _read_u16(f)
        w = _read_u16(f)
        h = _read_u16(f)
        divs.append((x, y, w, h))

    divisions_size = 12 + 8 * number_of_divisions
    divisions_padded_size = _align(divisions_size, 16)
    f.seek(divisions_padded_size - divisions_size, os.SEEK_CUR)

    if f.tell() != pp_offset:
        raise ValueError("Incorrect pp offset")

    return divs


def _parse_staff_scroll_table(staff_md_path: Path) -> list[StaffScrollCmd]:
    text = staff_md_path.read_text(encoding="utf-8", errors="ignore")
    cmds: list[StaffScrollCmd] = []
    pat = re.compile(
        r"StaffScrollCmd\s*<\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*>"
    )
    for m in pat.finditer(text):
        ctrl = int(m.group(1), 0)
        rl = int(m.group(2), 0) & 0xFFFF
        rr = int(m.group(3), 0) & 0xFFFF
        row_left = -1 if rl == 0xFFFF else struct.unpack("<h", struct.pack("<H", rl))[0]
        row_right = -1 if rr == 0xFFFF else struct.unpack("<h", struct.pack("<H", rr))[0]
        cmds.append(StaffScrollCmd(ctrl=ctrl, row_left=row_left, row_right=row_right))
        if cmds[-1].end_flag:
            break
    if not cmds:
        raise ValueError("no StaffScrollCmd found in STAFF.md")
    if not cmds[-1].end_flag:
        raise ValueError("StaffScrollCmd list missing end_flag")
    return cmds


def _rgba_crop_to_bbox(rgba: bytes, w: int, h: int) -> tuple[bytes, int, int]:
    left = w
    right = -1
    for y in range(h):
        row_off = y * w * 4
        for x in range(w):
            if rgba[row_off + x * 4 + 3] != 0:
                if x < left:
                    left = x
                if x > right:
                    right = x
    if right < left:
        return b"", 0, h
    new_w = right - left + 1
    out = bytearray(new_w * h * 4)
    for y in range(h):
        src_off = (y * w + left) * 4
        dst_off = y * new_w * 4
        out[dst_off : dst_off + new_w * 4] = rgba[src_off : src_off + new_w * 4]
    return bytes(out), new_w, h


def _rgba_scale_x_nearest(rgba: bytes, w: int, h: int, scale_x: float) -> tuple[bytes, int, int]:
    if w <= 0 or h <= 0:
        return rgba, w, h
    if scale_x <= 0:
        return b"", 0, h
    dst_w = max(1, int(round(w * scale_x)))
    if dst_w == w:
        return rgba, w, h
    out = bytearray(dst_w * h * 4)
    for y in range(h):
        src_row = y * w * 4
        dst_row = y * dst_w * 4
        for x in range(dst_w):
            sx = (x * w) // dst_w
            so = src_row + sx * 4
            do = dst_row + x * 4
            out[do : do + 4] = rgba[so : so + 4]
    return bytes(out), dst_w, h


def _rgba_to_png_bytes(rgba: bytes, w: int, h: int) -> bytes:
    out = io.BytesIO()
    writer = png_mod.Writer(w, h, alpha=True, bitdepth=8)
    stride = w * 4
    rows = [memoryview(rgba)[y * stride : (y + 1) * stride] for y in range(h)]
    writer.write(out, rows)
    return out.getvalue()


@dataclass
class SpriteAsset:
    rgba: bytes
    w: int
    h: int


class StaffAssets:
    def __init__(self, staff_dir: Path):
        self.staff_dir = staff_dir
        self._hpt_paths: dict[int, Path] = {}
        self._hgpt_bytes_cache: dict[int, bytes] = {}
        self._div_cache: dict[int, list[tuple[int, int, int, int]]] = {}
        self._hgpt_cache: dict[int, tuple[int, int, bytes]] = {}
        self._row_cache: dict[int, SpriteAsset] = {}
        self._photo_cache: dict[tuple[int, float], object] = {}
        self._row_map: list[tuple[int, int]] = []
        self.separator_row_id: int | None = None

        for i in range(1, 21):
            matches = sorted(staff_dir.glob(f"staff{i:02d}*.hpt"))
            if not matches:
                raise FileNotFoundError(f"missing staff{i:02d}*.hpt in {staff_dir}")
            self._hpt_paths[i] = matches[0]

        # Load all divisions first
        for hpt_idx in range(1, 21):
            hgpt = self._load_hgpt_bytes(hpt_idx)
            divs = _hgpt_divisions(hgpt)
            if not divs:
                raise ValueError(f"HGPT missing divisions: staff{hpt_idx:02d}")
            self._div_cache[hpt_idx] = divs
        
        # Build _row_map according to StaffRoll_AllocRow() from EBOOT binary
        # Extracted from assembly slti comparisons in EBOOT at 0x8976500
        range_table = [
            (1, 0, 10),       # staff01: row_id [0, 10)
            (2, 10, 21),      # staff02: row_id [10, 21)
            (3, 21, 34),      # staff03: row_id [21, 34)
            (4, 34, 46),      # staff04: row_id [34, 46)
            (5, 46, 55),      # staff05: row_id [46, 55)
            (6, 55, 67),      # staff06: row_id [55, 67)
            (7, 67, 80),      # staff07: row_id [67, 80)
            (8, 80, 93),      # staff08: row_id [80, 93)
            (9, 93, 103),     # staff09: row_id [93, 103)
            (10, 103, 114),   # staff10: row_id [103, 114)
            (11, 114, 125),   # staff11: row_id [114, 125)
            (12, 125, 136),   # staff12: row_id [125, 136)
            (13, 136, 147),   # staff13: row_id [136, 147)
            (14, 147, 154),   # staff14: row_id [147, 154)
            (15, 154, 156),   # staff15: row_id [154, 156)
            (16, 156, 160),   # staff16: row_id [156, 160)
            (17, 160, 163),   # staff17: row_id [160, 163)
            (18, 163, 174),   # staff18: row_id [163, 174)
            (19, 174, 206),   # staff19: row_id [174, 206)
            (20, 206, 214),   # staff20: row_id [206, 214)
        ]
        
        # Fill _row_map: row_id -> (hpt_idx, local_row)
        # where local_row = row_id - range_start
        self._row_map = {}
        for hpt_idx, row_id_start, row_id_end in range_table:
            for row_id in range(row_id_start, row_id_end):
                local_row = row_id - row_id_start
                # Verify that divisions exist for this local_row
                divs = self._div_cache[hpt_idx]
                if local_row >= len(divs):
                    # This is OK - the row_id range can be larger than actual divisions
                    # The game might not use all divisions, so we allow this mismatch
                    pass
                self._row_map[row_id] = (hpt_idx, local_row)
                
                # Detect separator row (staff15 div1 at row_id 155)
                if hpt_idx == 15 and local_row == 1 and self.separator_row_id is None:
                    self.separator_row_id = row_id

    def _load_hgpt_bytes(self, hpt_idx: int) -> bytes:
        if hpt_idx in self._hgpt_bytes_cache:
            return self._hgpt_bytes_cache[hpt_idx]
        hgpt = _decompress_zipped(self._hpt_paths[hpt_idx])
        self._hgpt_bytes_cache[hpt_idx] = hgpt
        return hgpt

    def _load_hgpt_rgba(self, hpt_idx: int) -> tuple[int, int, bytes]:
        if hpt_idx in self._hgpt_cache:
            return self._hgpt_cache[hpt_idx]
        hgpt = self._load_hgpt_bytes(hpt_idx)
        w, h, rgba = _decode_hgpt_rgba(hgpt)
        self._hgpt_cache[hpt_idx] = (w, h, rgba)
        return w, h, rgba

    def row_asset(self, row_id: int) -> SpriteAsset:
        if row_id in self._row_cache:
            return self._row_cache[row_id]
        if row_id not in self._row_map:
            asset = SpriteAsset(rgba=b"", w=0, h=0)
            self._row_cache[row_id] = asset
            return asset

        hpt_idx, div_idx = self._row_map[row_id]
        img_w, img_h, rgba = self._load_hgpt_rgba(hpt_idx)
        divs = self._div_cache[hpt_idx]
        x0, y0, w, h = divs[div_idx]
        if w <= 0 or h <= 0:
            asset = SpriteAsset(rgba=b"", w=0, h=0)
            self._row_cache[row_id] = asset
            return asset
        if x0 + w > img_w or y0 + h > img_h:
            raise ValueError(f"division out of range: staff{hpt_idx:02d} div={div_idx}")

        rect_rgba = bytearray(w * h * 4)
        for y in range(h):
            src_off = ((y0 + y) * img_w + x0) * 4
            dst_off = y * w * 4
            rect_rgba[dst_off : dst_off + w * 4] = rgba[src_off : src_off + w * 4]
        cropped_rgba, cw, ch = _rgba_crop_to_bbox(bytes(rect_rgba), w, h)
        asset = SpriteAsset(rgba=cropped_rgba, w=cw, h=ch)
        self._row_cache[row_id] = asset
        return asset

    def photo(self, row_id: int, scale_x: float, tk_root) -> tuple[object | None, int, int]:
        asset = self.row_asset(row_id)
        if asset.w <= 0 or not asset.rgba:
            return None, 0, asset.h
        key = (row_id, scale_x)
        if key in self._photo_cache:
            img = self._photo_cache[key]
            return img, int(round(asset.w * scale_x)), asset.h
        rgba, w, h = asset.rgba, asset.w, asset.h
        if abs(scale_x - 1.0) > 1e-6:
            rgba, w, h = _rgba_scale_x_nearest(rgba, w, h, scale_x)
        png_bytes = _rgba_to_png_bytes(rgba, w, h)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        if tk is None:
            raise RuntimeError("tkinter is not available in this Python environment")
        img = tk.PhotoImage(master=tk_root, data=b64, format="png")
        self._photo_cache[key] = img
        return img, w, h


@dataclass
class ActiveSprite:
    canvas_id: int
    x: float
    y: float
    w: int
    h: int
    image: object


class StaffRollSim:
    def __init__(self, root, assets: StaffAssets, cmds: list[StaffScrollCmd]):
        self.root = root
        self.assets = assets
        self.cmds = cmds

        self.done_flag = False
        self.cmd_index = 0
        self.cmd_tail_slot = 0
        self.scroll_accum = 0.0
        self.scroll_speed = self._calc_total_height() / float(TOTAL_FRAMES)

        self.slots: list[ActiveSprite | None] = [None] * 64

        self.paused = False

        self.root.title("Staff Roll Sim (480x272)")
        self.root.resizable(False, False)

        if tk is None or ttk is None:
            raise RuntimeError("tkinter is not available in this Python environment")
        self.canvas = tk.Canvas(self.root, width=SCREEN_W, height=SCREEN_H, bg="black", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        bar = ttk.Frame(self.root)
        bar.grid(row=1, column=0, sticky="ew")
        bar.columnconfigure(4, weight=1)

        self.btn_pause = ttk.Button(bar, text="Pause", command=self.toggle_pause)
        self.btn_pause.grid(row=0, column=0, padx=6, pady=6)

        self.btn_restart = ttk.Button(bar, text="Restart", command=self.restart)
        self.btn_restart.grid(row=0, column=1, padx=6, pady=6)

        self.info = ttk.Label(bar, text="")
        self.info.grid(row=0, column=4, sticky="w", padx=6)

        self._update_info()
        self._tick()

    def _calc_total_height(self) -> int:
        total = 0
        for c in self.cmds:
            total += c.pixel_gap
            if c.end_flag:
                break
        return total

    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.config(text="Resume" if self.paused else "Pause")

    def restart(self):
        for s in self.slots:
            if s is not None:
                self.canvas.delete(s.canvas_id)
        self.slots = [None] * 64
        self.done_flag = False
        self.cmd_index = 0
        self.cmd_tail_slot = 0
        self.scroll_accum = 0.0
        self._update_info()

    def _free_slot(self, slot: int):
        s = self.slots[slot]
        if s is None:
            return
        self.canvas.delete(s.canvas_id)
        self.slots[slot] = None

    def _alloc_slot(self) -> int:
        slot = self.cmd_tail_slot
        if self.slots[slot] is not None:
            self._free_slot(slot)
        self.cmd_tail_slot = (slot + 1) % 64
        return slot

    def _spawn_sprite(self, row_id: int, x: float, y: float, scale_x: float = 1.0):
        img, w, h = self.assets.photo(row_id, scale_x, self.root)
        if img is None or w <= 0:
            return
        slot = self._alloc_slot()
        canvas_id = self.canvas.create_image(x, y, anchor="nw", image=img)
        self.slots[slot] = ActiveSprite(canvas_id=canvas_id, x=x, y=y, w=w, h=h, image=img)

    def _process_cmd(self, cmd: StaffScrollCmd):
        if cmd.end_flag:
            self.done_flag = True

        # 打印当前指令的详细 Log
        log_msg = f"[CMD {self.cmd_index}] "
        
        w_left = 0
        w_right = 0

        # 处理左侧行
        if cmd.row_left != -1:
            hpt_idx, div_idx = self.assets._row_map.get(cmd.row_left, (None, None))
            log_msg += f"Left: RowID {cmd.row_left} (HPT {hpt_idx:02d}, Div {div_idx}) | "
            
            img_l, w_l, h_l = self.assets.photo(cmd.row_left, 1.0, self.root)
            if img_l is not None and w_l > 0:
                w_left = w_l
                a = cmd.align
                # 坐标计算逻辑保持不变...
                if a == 0: x = 240 - w_l
                elif a == 1: x = 224 - w_l
                elif a == 2: x = 10
                elif a == 3: x = 248
                elif a == 4: x = (240 - w_l) if cmd.row_right != -1 else 240 - w_l/2
                elif a == 5: x = (224 - w_l) if cmd.row_right != -1 else 224 - w_l/2
                elif a == 6: x = (288 - w_l) if cmd.row_right != -1 else 288 - w_l/2
                else: x = 0x4000
                self._spawn_sprite(cmd.row_left, float(x), float(SPAWN_Y))
        else:
            log_msg += "Left: Empty | "

        # 处理右侧行
        if cmd.row_right != -1:
            hpt_idx, div_idx = self.assets._row_map.get(cmd.row_right, (None, None))
            log_msg += f"Right: RowID {cmd.row_right} (HPT {hpt_idx:02d}, Div {div_idx}) | "
            
            img_r, w_r, h_r = self.assets.photo(cmd.row_right, 1.0, self.root)
            if img_r is not None and w_r > 0:
                w_right = w_r
                a = cmd.align
                if a == 5: x = 256
                elif a == 6: x = 304
                else: x = 248
                self._spawn_sprite(cmd.row_right, float(x), float(SPAWN_Y))
        else:
            log_msg += "Right: Empty | "

        # 处理分隔符
        if cmd.has_separator:
            divider_row_id = self.assets.separator_row_id if self.assets.separator_row_id is not None else 155
            hpt_idx, div_idx = self.assets._row_map.get(divider_row_id, (None, None))
            log_msg += f"SEP: ACTIVE (HPT {hpt_idx:02d}, Div {div_idx})"
            
            a = cmd.align
            v23 = 0
            if a in (0, 3):
                v23 = (w_left // 2) + 32
            elif a == 1:
                v23 = w_left + 48
            elif a == 4:
                v23 = (w_left + w_right + 32) if cmd.row_right != -1 else (w_left // 2) + 32
            elif a == 5:
                v23 = (w_left + w_right + 48) if cmd.row_right != -1 else (w_left // 2) + 32
            
            if v23 > 0:
                divider_asset = self.assets.row_asset(divider_row_id)
                if divider_asset.w > 0:
                    scale_x = (2.0 * float(v23)) / float(divider_asset.w)
                    self._spawn_sprite(divider_row_id, float(240 - v23), float(SPAWN_Y + 24.0), scale_x=scale_x)
        else:
            log_msg += "SEP: None"

        # 输出这一行指令的完整映射关系
        print(log_msg)
        
        self.scroll_accum += float(cmd.pixel_gap)

    def _update_info(self):
        self.info.config(
            text=f"cmd={self.cmd_index}/{len(self.cmds)}  speed={self.scroll_speed:.4f}  accum={self.scroll_accum:.2f}  done={int(self.done_flag)}"
        )

    def _tick(self):
        if not self.paused:
            if (not self.done_flag) and self.cmd_index < len(self.cmds):
                if self.scroll_accum <= 0.0:
                    self._process_cmd(self.cmds[self.cmd_index])
                    self.cmd_index += 1

            for i, s in enumerate(self.slots):
                if s is None:
                    continue
                s.y -= self.scroll_speed
                if s.y > -float(s.h):
                    self.canvas.coords(s.canvas_id, s.x, s.y)
                else:
                    self._free_slot(i)

            self.scroll_accum -= self.scroll_speed
            self._update_info()

        self.root.after(int(1000 / FPS), self._tick)


def main():
    if tk is None or ttk is None:
        print("tkinter 不可用：当前 Python 缺少 _tkinter。请改用系统自带 Python，或安装带 Tk 支持的 Python。")
        print("macOS (Homebrew) 常见修复：brew install python-tk@3.12 或使用 python.org 官方安装包。")
        return
    staff_md_path = ROOT_DIR / "docs" / "STAFF.md"
    staff_dir = ROOT_DIR / "scripts" / "staff"
    cmds = _parse_staff_scroll_table(staff_md_path)
    assets = StaffAssets(staff_dir)
    root = tk.Tk()
    StaffRollSim(root, assets, cmds)
    root.mainloop()


if __name__ == "__main__":
    main()
