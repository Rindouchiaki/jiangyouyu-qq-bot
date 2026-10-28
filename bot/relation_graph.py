"""群关系图：酱油鱼在中间，连到每个记过的群友（线上写态度档），群友之间有关系的连线写关系。

只用 Pillow 画，不依赖 NoneBot，方便离线测。中文字体按 Windows / macOS / Linux 常见位置找。
"""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 1000
RING = 360
NODE_R = 46
MAX_PEOPLE = 16
NOTE_LINE = 34

# 态度档 → 她连到这个人的线的颜色
ATT_COLORS = {
    "亲近": (232, 87, 155),
    "有好感": (242, 154, 196),
    "普通": (154, 165, 177),
    "陌生": (199, 204, 209),
    "讨厌": (91, 103, 112),
}
LINK_COLOR = (74, 123, 209)
BG = (255, 255, 255)
INK = (40, 44, 52)
SELF_FILL = (255, 214, 231)
NODE_FILL = (238, 243, 250)

_FONT_PATHS = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
)


def _font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_PATHS:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _short(name: str, n: int = 6) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


def _label(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, color) -> None:
    """线中间的字：垫一块白底，压在线上也看得清。"""
    box = draw.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    x, y = xy[0] - w / 2, xy[1] - h / 2
    draw.rectangle((x - 4, y - 3, x + w + 4, y + h + 5), fill=BG)
    draw.text((x, y - box[1]), text, font=font, fill=color)


def _node(draw: ImageDraw.ImageDraw, xy: tuple[float, float], name: str, font, fill) -> None:
    x, y = xy
    draw.ellipse((x - NODE_R, y - NODE_R, x + NODE_R, y + NODE_R), fill=fill, outline=INK, width=2)
    text = _short(name)
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2 - box[1]), text, font=font, fill=INK)


def render(
    center: str,
    people: list[tuple[str, str | None]],
    links: list[tuple[str, str, str]],
    notes: list[str] = (),
    title: str = "",
) -> bytes:
    """画一张关系图，返回 PNG。people 是 (名字, 她对这人的态度档)；links 是 (甲, 乙, 关系)；
    notes 是认不出是谁和谁的关系笔记，列在图下面。"""
    att = dict(people)
    # 有关系的两个人在圈上挨着放，连线短、不横穿中间压住别的字
    names: list[str] = []
    for a, b, _ in links:
        for n in (a, b):
            if n not in names and n != center:
                names.append(n)
    names += [n for n, _ in people if n not in names]
    names = names[:MAX_PEOPLE]
    notes = [n for n in notes if n][:8]
    height = SIZE + (NOTE_LINE * (len(notes) + 1) + 20 if notes else 0)
    img = Image.new("RGB", (SIZE, height), BG)
    draw = ImageDraw.Draw(img)
    f_node, f_label, f_title = _font(22), _font(18), _font(26)

    mid = (SIZE / 2, SIZE / 2 + 10)
    pos: dict[str, tuple[float, float]] = {center: mid}
    for i, name in enumerate(names):
        angle = -math.pi / 2 + 2 * math.pi * i / max(len(names), 1)
        pos[name] = (mid[0] + RING * math.cos(angle), mid[1] + RING * math.sin(angle))

    # 先画线再画圈，圈压在线头上
    for name in names:
        level = att.get(name)
        if level:
            color = ATT_COLORS.get(level, ATT_COLORS["普通"])
            draw.line((mid, pos[name]), fill=color, width=4 if level in ("亲近", "有好感") else 2)
    drawn = []
    for a, b, rel in links:
        if a in pos and b in pos:
            draw.line((pos[a], pos[b]), fill=LINK_COLOR, width=3)
            drawn.append((a, b, rel))
    for name in names:
        level = att.get(name)
        if level:
            x, y = pos[name]
            _label(draw, (mid[0] + (x - mid[0]) * 0.55, mid[1] + (y - mid[1]) * 0.55), level, f_label,
                   ATT_COLORS.get(level, INK))
    for a, b, rel in drawn:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        _label(draw, ((x1 + x2) / 2, (y1 + y2) / 2), _short(rel, 10), f_label, LINK_COLOR)

    _node(draw, mid, center, f_node, SELF_FILL)
    for name in names:
        _node(draw, pos[name], name, f_node, NODE_FILL)

    if title:
        draw.text((24, 18), title, font=f_title, fill=INK)
    if notes:
        y = SIZE + 10
        draw.text((24, y), "认不出是谁和谁的关系：", font=f_label, fill=INK)
        for note in notes:
            y += NOTE_LINE
            draw.text((40, y), f"· {note}", font=f_label, fill=INK)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
