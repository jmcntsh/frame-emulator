from __future__ import annotations

from dataclasses import dataclass, field
import hashlib


Color = tuple[int, int, int]


DEFAULT_PALETTE: list[Color] = [
    (0, 0, 0),
    (255, 255, 255),
    (128, 128, 128),
    (255, 0, 0),
    (255, 128, 192),
    (64, 32, 16),
    (128, 64, 32),
    (255, 128, 0),
    (255, 255, 0),
    (0, 64, 0),
    (0, 180, 0),
    (128, 255, 128),
    (0, 0, 64),
    (0, 96, 160),
    (64, 180, 255),
    (160, 220, 255),
]

PALETTE_NAMES = {
    "VOID": 0,
    "WHITE": 1,
    "GREY": 2,
    "GRAY": 2,
    "RED": 3,
    "PINK": 4,
    "DARKBROWN": 5,
    "BROWN": 6,
    "ORANGE": 7,
    "YELLOW": 8,
    "DARKGREEN": 9,
    "GREEN": 10,
    "LIGHTGREEN": 11,
    "NIGHTBLUE": 12,
    "SEABLUE": 13,
    "SKYBLUE": 14,
    "CLOUDBLUE": 15,
}

FONT_5X7 = {
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "?": ["01110", "10001", "00001", "00010", "00100", "00000", "00100"],
    "!": ["00100", "00100", "00100", "00100", "00100", "00000", "00100"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    ",": ["00000", "00000", "00000", "00000", "01100", "00100", "01000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "/": ["00001", "00010", "00100", "01000", "10000", "00000", "00000"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10011", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
}


@dataclass
class FrameDisplay:
    width: int = 640
    height: int = 400
    palette: list[Color] = field(default_factory=lambda: list(DEFAULT_PALETTE))
    brightness: int = 0

    def __post_init__(self) -> None:
        self.draw_buffer = self._blank_buffer()
        self.visible_buffer = self._blank_buffer()

    def clear_draw_buffer(self) -> None:
        self.draw_buffer = self._blank_buffer()

    def clear_visible_buffer(self) -> None:
        self.visible_buffer = self._blank_buffer()

    def reset_palette(self) -> None:
        self.palette = list(DEFAULT_PALETTE)

    def show(self) -> None:
        self.visible_buffer = [row[:] for row in self.draw_buffer]
        self.clear_draw_buffer()

    def text(self, text: str, x: int = 1, y: int = 1, color: int | str = 1, spacing: int = 4) -> None:
        color_index = self.color_index(color)
        cursor_x = max(0, x - 1)
        cursor_y = max(0, y - 1)
        scale = 3
        char_width = (5 * scale) + max(1, spacing)
        char_height = 7 * scale

        for char in text:
            if char == "\n":
                cursor_x = max(0, x - 1)
                cursor_y += char_height + 8
                continue
            self._draw_glyph(cursor_x, cursor_y, char, color_index, scale)
            cursor_x += char_width

    def rect(self, x: int, y: int, width: int, height: int, color: int | str = 1, filled: bool = True) -> None:
        color_index = self.color_index(color)
        left = max(0, int(x))
        top = max(0, int(y))
        right = min(self.width, left + max(0, int(width)))
        bottom = min(self.height, top + max(0, int(height)))

        for py in range(top, bottom):
            for px in range(left, right):
                if filled or px in (left, right - 1) or py in (top, bottom - 1):
                    self.draw_buffer[py][px] = color_index

    def bitmap(
        self,
        x: int,
        y: int,
        width: int,
        color_format: int,
        palette_offset: int,
        data: bytes,
    ) -> None:
        if width <= 0 or color_format not in (2, 4, 16):
            return

        bits_per_pixel = {2: 1, 4: 2, 16: 4}[color_format]
        mask = (1 << bits_per_pixel) - 1
        px_count = 0

        for byte in data:
            for shift in range(8 - bits_per_pixel, -1, -bits_per_pixel):
                value = (byte >> shift) & mask
                color_index = 0 if value == 0 else (value + palette_offset) % 16
                px = x - 1 + (px_count % width)
                py = y - 1 + (px_count // width)
                if 0 <= px < self.width and 0 <= py < self.height:
                    self.draw_buffer[py][px] = color_index
                px_count += 1

    def assign_color(self, color: int | str, r: int, g: int, b: int) -> None:
        self.palette[self.color_index(color)] = (self._clamp(r), self._clamp(g), self._clamp(b))

    def assign_color_ycbcr(self, color: int | str, y: int, cb: int, cr: int) -> None:
        # Approximate Frame's YCbCr palette register with host RGB for visual QA.
        yy = self._clamp(round((y / 15) * 255))
        cbb = (cb / 7) * 255 - 128
        crr = (cr / 7) * 255 - 128
        r = yy + 1.402 * crr
        g = yy - 0.344136 * cbb - 0.714136 * crr
        b = yy + 1.772 * cbb
        self.assign_color(color, round(r), round(g), round(b))

    def color_index(self, color: int | str) -> int:
        if isinstance(color, int):
            return max(0, min(15, color))
        return PALETTE_NAMES.get(color.upper(), 1)

    def snapshot_ppm(self, brightness: int | None = None) -> bytes:
        header = f"P6\n{self.width} {self.height}\n255\n".encode()
        pixels = bytearray()
        brightness_value = self.brightness if brightness is None else brightness
        for row in self.visible_buffer:
            for color_index in row:
                pixels.extend(self._apply_brightness(self.palette[color_index], brightness_value))
        return header + bytes(pixels)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.snapshot_ppm()).hexdigest()

    def non_void_bounds(self) -> tuple[int, int, int, int] | None:
        xs: list[int] = []
        ys: list[int] = []
        for y, row in enumerate(self.visible_buffer):
            for x, color_index in enumerate(row):
                if color_index != 0:
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _blank_buffer(self) -> list[list[int]]:
        return [[0 for _ in range(self.width)] for _ in range(self.height)]

    def _draw_glyph(self, x: int, y: int, char: str, color_index: int, scale: int) -> None:
        glyph = FONT_5X7.get(char.upper(), FONT_5X7["?"])
        for row_index, row in enumerate(glyph):
            for col_index, value in enumerate(row):
                if value == "1":
                    self.rect(x + col_index * scale, y + row_index * scale, scale, scale, color_index)

    @staticmethod
    def _clamp(value: int) -> int:
        return max(0, min(255, int(value)))

    @classmethod
    def _apply_brightness(cls, color: Color, brightness: int) -> Color:
        factors = {-2: 0.45, -1: 0.7, 0: 1.0, 1: 1.2, 2: 1.4}
        factor = factors.get(max(-2, min(2, int(brightness))), 1.0)
        return tuple(cls._clamp(round(channel * factor)) for channel in color)  # type: ignore[return-value]
