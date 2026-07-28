#!/usr/bin/env python3
import ctypes
import math
import os
import struct
import zlib


WIDTH, HEIGHT = 1600, 900
OUT = os.path.join(os.path.dirname(__file__), "architecture.png")
FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def rgba(hex_color, alpha=255):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4)) + (alpha,)


class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(bg * (w * h))

    def blend(self, x, y, color):
        if x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        i = (y * self.w + x) * 4
        a = color[3] / 255.0
        ia = 1.0 - a
        self.px[i] = int(color[0] * a + self.px[i] * ia)
        self.px[i + 1] = int(color[1] * a + self.px[i + 1] * ia)
        self.px[i + 2] = int(color[2] * a + self.px[i + 2] * ia)
        self.px[i + 3] = 255

    def rect(self, x, y, w, h, color):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        for yy in range(y0, y1):
            row = (yy * self.w + x0) * 4
            for _ in range(x0, x1):
                self.px[row : row + 4] = bytes(color)
                row += 4

    def rounded_rect(self, x, y, w, h, r, fill, stroke=None, sw=2):
        def inside(px, py, ox, oy, ow, oh, rr):
            dx = max(ox + rr - px, 0, px - (ox + ow - rr - 1))
            dy = max(oy + rr - py, 0, py - (oy + oh - rr - 1))
            return dx * dx + dy * dy <= rr * rr

        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if inside(xx, yy, x, y, w, h, r):
                    self.blend(xx, yy, fill)
        if stroke:
            ix, iy = x + sw, y + sw
            iw, ih = w - sw * 2, h - sw * 2
            ir = max(1, r - sw)
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    if inside(xx, yy, x, y, w, h, r) and not inside(xx, yy, ix, iy, iw, ih, ir):
                        self.blend(xx, yy, stroke)

    def line(self, x0, y0, x1, y1, color, width=3):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(steps + 1):
            t = i / steps
            x = int(x0 + (x1 - x0) * t)
            y = int(y0 + (y1 - y0) * t)
            for yy in range(y - width // 2, y + width // 2 + 1):
                for xx in range(x - width // 2, x + width // 2 + 1):
                    self.blend(xx, yy, color)

    def arrow(self, x0, y0, x1, y1, color, label=None, font=None):
        self.line(x0, y0, x1, y1, color, 5)
        ang = math.atan2(y1 - y0, x1 - x0)
        for side in (-1, 1):
            a = ang + side * 2.55
            self.line(x1, y1, int(x1 + math.cos(a) * 24), int(y1 + math.sin(a) * 24), color, 5)
        if label and font:
            tx = (x0 + x1) // 2
            ty = (y0 + y1) // 2 - 32
            tw = font.text_width(label, 24)
            self.rounded_rect(tx - tw // 2 - 14, ty - 16, tw + 28, 38, 12, rgba("#111827", 238), rgba("#334155", 200), 1)
            font.draw(self, label, tx - tw // 2, ty + 11, 24, rgba("#cbd5e1"))

    def write_png(self, path):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        raw = bytearray()
        stride = self.w * 4
        for y in range(self.h):
            raw.append(0)
            raw.extend(self.px[y * stride : (y + 1) * stride])
        data = b"\x89PNG\r\n\x1a\n"
        data += chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0))
        data += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        data += chunk(b"IEND", b"")
        with open(path, "wb") as f:
            f.write(data)


class FTBitmap(ctypes.Structure):
    _fields_ = [
        ("rows", ctypes.c_uint),
        ("width", ctypes.c_uint),
        ("pitch", ctypes.c_int),
        ("buffer", ctypes.POINTER(ctypes.c_ubyte)),
        ("num_grays", ctypes.c_ushort),
        ("pixel_mode", ctypes.c_ubyte),
        ("palette_mode", ctypes.c_ubyte),
        ("palette", ctypes.c_void_p),
    ]


class FTVector(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class FTGeneric(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("finalizer", ctypes.c_void_p)]


class FTBBox(ctypes.Structure):
    _fields_ = [("xMin", ctypes.c_long), ("yMin", ctypes.c_long), ("xMax", ctypes.c_long), ("yMax", ctypes.c_long)]


class FTGlyphMetrics(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_long),
        ("height", ctypes.c_long),
        ("horiBearingX", ctypes.c_long),
        ("horiBearingY", ctypes.c_long),
        ("horiAdvance", ctypes.c_long),
        ("vertBearingX", ctypes.c_long),
        ("vertBearingY", ctypes.c_long),
        ("vertAdvance", ctypes.c_long),
    ]


class FTGlyphSlotRec(ctypes.Structure):
    _fields_ = [
        ("library", ctypes.c_void_p),
        ("face", ctypes.c_void_p),
        ("next", ctypes.c_void_p),
        ("reserved", ctypes.c_uint),
        ("generic", FTGeneric),
        ("metrics", FTGlyphMetrics),
        ("linearHoriAdvance", ctypes.c_long),
        ("linearVertAdvance", ctypes.c_long),
        ("advance", FTVector),
        ("format", ctypes.c_uint),
        ("bitmap", FTBitmap),
        ("bitmap_left", ctypes.c_int),
        ("bitmap_top", ctypes.c_int),
    ]


class FTFaceRec(ctypes.Structure):
    _fields_ = [
        ("num_faces", ctypes.c_long),
        ("face_index", ctypes.c_long),
        ("face_flags", ctypes.c_long),
        ("style_flags", ctypes.c_long),
        ("num_glyphs", ctypes.c_long),
        ("family_name", ctypes.c_char_p),
        ("style_name", ctypes.c_char_p),
        ("num_fixed_sizes", ctypes.c_int),
        ("available_sizes", ctypes.c_void_p),
        ("num_charmaps", ctypes.c_int),
        ("charmaps", ctypes.c_void_p),
        ("generic", FTGeneric),
        ("bbox", FTBBox),
        ("units_per_EM", ctypes.c_ushort),
        ("ascender", ctypes.c_short),
        ("descender", ctypes.c_short),
        ("height", ctypes.c_short),
        ("max_advance_width", ctypes.c_short),
        ("max_advance_height", ctypes.c_short),
        ("underline_position", ctypes.c_short),
        ("underline_thickness", ctypes.c_short),
        ("glyph", ctypes.POINTER(FTGlyphSlotRec)),
    ]


class Font:
    def __init__(self, path):
        self.ft = ctypes.CDLL("libfreetype.so.6")
        self.lib = ctypes.c_void_p()
        self.face = ctypes.POINTER(FTFaceRec)()
        assert self.ft.FT_Init_FreeType(ctypes.byref(self.lib)) == 0
        assert self.ft.FT_New_Face(self.lib, path.encode(), 0, ctypes.byref(self.face)) == 0

    def set_size(self, size):
        self.ft.FT_Set_Pixel_Sizes(self.face, 0, size)

    def text_width(self, text, size):
        self.set_size(size)
        width = 0
        for ch in text:
            if self.ft.FT_Load_Char(self.face, ord(ch), 4) == 0:
                width += self.face.contents.glyph.contents.advance.x >> 6
        return width

    def draw(self, canvas, text, x, baseline, size, color):
        self.set_size(size)
        pen = x
        for ch in text:
            if self.ft.FT_Load_Char(self.face, ord(ch), 4) != 0:
                continue
            slot = self.face.contents.glyph.contents
            bm = slot.bitmap
            for row in range(bm.rows):
                for col in range(bm.width):
                    v = bm.buffer[row * bm.pitch + col]
                    if v:
                        canvas.blend(pen + slot.bitmap_left + col, baseline - slot.bitmap_top + row, color[:3] + (int(color[3] * v / 255),))
            pen += slot.advance.x >> 6

    def centered_lines(self, canvas, lines, cx, cy, sizes, colors, gap=10):
        heights = [int(s * 1.22) for s in sizes]
        total = sum(heights) + gap * (len(lines) - 1)
        top = cy - total // 2
        y = top
        for line, size, color, h in zip(lines, sizes, colors, heights):
            tw = self.text_width(line, size)
            self.draw(canvas, line, cx - tw // 2, y + int(size * 0.95), size, color)
            y += h + gap


def draw_card(c, font, x, y, w, h, title, subtitle, accent):
    c.rounded_rect(x + 10, y + 14, w, h, 22, rgba("#020617", 110))
    c.rounded_rect(x, y, w, h, 22, rgba("#111827", 245), rgba(accent, 235), 3)
    c.rect(x, y, w, 8, rgba(accent, 230))
    lines = [title] + subtitle
    sizes = [36] + [25 for _ in subtitle]
    colors = [rgba("#f8fafc")] + [rgba("#cbd5e1") for _ in subtitle]
    font.centered_lines(c, lines, x + w // 2, y + h // 2 + 6, sizes, colors, gap=8)


def main():
    c = Canvas(WIDTH, HEIGHT, rgba("#07111f"))
    font = Font(FONT)

    # Subtle background grid.
    for x in range(0, WIDTH, 40):
        c.line(x, 0, x, HEIGHT, rgba("#172033", 70), 1)
    for y in range(0, HEIGHT, 40):
        c.line(0, y, WIDTH, y, rgba("#172033", 70), 1)

    font.draw(c, "统一采集服务 unified-collector 架构图", 74, 92, 42, rgba("#f8fafc"))
    font.draw(c, "Docker 容器部署 · 暗色主题 · 数据流从左到右", 76, 133, 24, rgba("#94a3b8"))

    c.rounded_rect(45, 188, 1510, 575, 28, rgba("#0b1220", 170), rgba("#334155", 210), 2)
    font.draw(c, "Docker Compose / 容器网络", 74, 232, 27, rgba("#93c5fd"))

    cards = [
        (80, 330, 245, 185, "62个外部源", ["Telegram / RSS", "频道与订阅源"], "#38bdf8"),
        (400, 300, 265, 245, "Collector核心", ["FastAPI", "抓取 / 解析 / 入库"], "#818cf8"),
        (740, 315, 230, 215, "SQLite", ["WAL 模式", "articles / sources"], "#22c55e"),
        (1040, 315, 220, 215, "API层", ["REST / JSON", "查询与筛选"], "#f59e0b"),
        (1320, 315, 205, 215, "Caddy", ["反向代理", "TLS / 路由"], "#06b6d4"),
    ]
    for card in cards:
        draw_card(c, font, *card)

    user_x, user_y = 1405, 635
    c.rounded_rect(user_x - 82, user_y - 38, 164, 76, 38, rgba("#1e293b", 245), rgba("#e2e8f0", 220), 2)
    font.centered_lines(c, ["用户"], user_x, user_y + 2, [34], [rgba("#f8fafc")])

    c.arrow(325, 422, 400, 422, rgba("#38bdf8"), "采集", font)
    c.arrow(665, 422, 740, 422, rgba("#a78bfa"), "写入", font)
    c.arrow(970, 422, 1040, 422, rgba("#4ade80"), "读取", font)
    c.arrow(1260, 422, 1320, 422, rgba("#fbbf24"), "HTTP", font)
    c.arrow(1422, 530, 1422, 595, rgba("#22d3ee"), "访问", font)

    # Operational details.
    c.rounded_rect(405, 605, 310, 92, 16, rgba("#111827", 225), rgba("#475569", 210), 2)
    font.centered_lines(c, ["定时任务 / 手动触发", "去重、失败重试、日志"], 560, 652, [25, 22], [rgba("#e2e8f0"), rgba("#94a3b8")], gap=5)

    c.rounded_rect(805, 605, 310, 92, 16, rgba("#111827", 225), rgba("#475569", 210), 2)
    font.centered_lines(c, ["持久化存储", "WAL 提升并发读写"], 960, 652, [25, 22], [rgba("#e2e8f0"), rgba("#94a3b8")], gap=5)

    c.arrow(560, 545, 560, 605, rgba("#64748b"))
    c.arrow(960, 530, 960, 605, rgba("#64748b"))

    font.draw(c, "数据流：62个外部源 → Collector核心(FastAPI) → SQLite(WAL) → API层 → Caddy反向代理 → 用户", 76, 825, 26, rgba("#cbd5e1"))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    c.write_png(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
