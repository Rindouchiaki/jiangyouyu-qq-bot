"""群关系图：酱油鱼在中间，越亲近的越靠里（一圈放不下就往外加一圈），她连到每个人的线的颜色是她的态度，
她和这人的关系写在人名下面；群友之间的关系画成弯线，地方够就写在线上，挤了就标号、列在图下面。

人多的大群也看得清：人越多圈越小、图越大，最多画 MAX_PEOPLE 个，字和字不叠在一起；
超过 SPOKES_MAX 个人时不再画她连出去的线（几十条线挤在中间看不清），改成人外面那圈的颜色表示态度。
只用 Pillow 画，不依赖 NoneBot，方便离线测。中文字体按 Windows / macOS / Linux 常见位置找。
"""

from __future__ import annotations

import functools
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 图至少这么宽（标题和图例要放得下），人多了跟着变大
MIN_SIZE = 860
SPOKES_MAX = 20
MAX_PEOPLE = 80
HEADER = 100
ROW = 30
# 群友之间的关系超过这么多条就直接标号，不往线上写
INLINE_LINKS = 10
CAPTION_CHARS = 7

# 态度档 → 她连到这个人的线的颜色（暖色是喜欢、冷色是讨厌，每档色相不同，别再用几种灰）；也是从里到外排圈的顺序
ATT_COLORS = {
    "亲近": (226, 54, 120),
    "有好感": (245, 150, 50),
    "普通": (52, 168, 100),
    "陌生": (170, 176, 186),
    "讨厌": (122, 62, 168),
}
# 陌生画虚线：还不怎么认识
DASHED = ("陌生",)
TIER_ORDER = tuple(ATT_COLORS)
LINK_COLOR = (74, 123, 209)
# 群日记里指她自己的写法（「我」是记日记的人设自己）
SELF_WORDS = ("我", "自己", "本人")
BG = (255, 255, 255)
INK = (40, 44, 52)
SOFT_INK = (110, 116, 128)
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


@functools.lru_cache(maxsize=32)
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


def node_radius(count: int) -> int:
    """人越多圈越小。"""
    return 46 if count <= 12 else 36 if count <= 30 else 30 if count <= 56 else 26


def caption_size(r: int) -> int:
    return max(13, min(17, r // 2 - 2))


def caption_lines(rel: str) -> list[str]:
    """她和这人的关系写在名字下面，最多两行。"""
    rel = " ".join(str(rel or "").split())
    if not rel:
        return []
    if len(rel) <= CAPTION_CHARS:
        return [rel]
    return [rel[:CAPTION_CHARS], _short(rel[CAPTION_CHARS:], CAPTION_CHARS)]


def _overlap(a, b, pad: float = 0) -> bool:
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0] or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def layout(
    names: list[str],
    att: dict[str, str | None],
    pair_links: list[tuple[str, str, str]],
) -> tuple[dict[str, tuple[float, float]], int, float]:
    """排座次（以她为原点）：越亲近越靠里，一圈放满了往外加一圈，同一圈里有关系的挨着。返回 (位置, 圈半径, 最外圈半径)。"""
    if not names:
        return {}, node_radius(0), 0.0
    r = node_radius(len(names))
    cf = caption_size(r)
    spacing = max(2 * r, CAPTION_CHARS * cf) + 16
    first, step = max(180.0, 4.2 * r), 2 * r + 2 * cf + 44
    rank = {t: i for i, t in enumerate(TIER_ORDER)}
    index = {n: i for i, n in enumerate(names)}
    order = sorted(names, key=lambda n: (rank.get(att.get(n) or "", len(TIER_ORDER)), index[n]))
    rings: list[list[str]] = []
    radius = first
    while order:
        cap = max(1, int(2 * math.pi * radius / spacing))
        rings.append(order[:cap])
        order = order[cap:]
        radius += step
    near: dict[str, list[str]] = {}
    for a, b, _ in pair_links:
        near.setdefault(a, []).append(b)
        near.setdefault(b, []).append(a)
    pos: dict[str, tuple[float, float]] = {}
    inner: list[tuple[float, float]] = []
    for k, ring in enumerate(rings):
        # 同一圈里顺着关系走，有关系的挨着
        members, seq = set(ring), []

        def walk(n: str) -> None:
            seq.append(n)
            for m in near.get(n, ()):
                if m in members and m not in seq:
                    walk(m)

        for n in ring:
            if n not in seq:
                walk(n)
        rad = first + k * step
        shift = _best_shift(len(seq), inner, r)
        for i, n in enumerate(seq):
            angle = -math.pi / 2 + 2 * math.pi * i / len(seq) + shift
            pos[n] = (rad * math.cos(angle), rad * math.sin(angle))
            inner.append((angle, rad))
    return pos, r, first + (len(rings) - 1) * step


def _best_shift(count: int, inner: list[tuple[float, float]], r: int) -> float:
    """这一圈转多少：让她连到外圈的线尽量从里圈两个人中间穿过去，别正好压在里圈的人身上。"""
    if not inner:
        return 0.0
    best, best_gap = 0.0, -1.0
    for j in range(12):
        shift = 2 * math.pi / count * j / 12
        gap = min(
            abs((-math.pi / 2 + 2 * math.pi * i / count + shift - a + math.pi) % (2 * math.pi) - math.pi) - r / rad
            for i in range(count) for a, rad in inner
        )
        if gap > best_gap:
            best, best_gap = shift, gap
    return best


def _bow(p1, p2, mid, scale: float) -> list[tuple[float, float]]:
    """群友之间的线往外弯：直线会穿过中间压住她和别的线（两个人正好对着时最明显）。"""
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    dx, dy = mx - mid[0], my - mid[1]
    d = math.hypot(dx, dy)
    if d < scale * 0.3:
        # 弦穿过中间：沿弦的垂直方向弯
        dx, dy = p1[1] - p2[1], p2[0] - p1[0]
        d, amount = math.hypot(dx, dy) or 1, scale * 0.55
    else:
        amount = min(scale * 0.25, math.hypot(p1[0] - p2[0], p1[1] - p2[1]) * 0.35)
    cx, cy = mx + dx / d * amount, my + dy / d * amount
    pts = []
    for i in range(25):
        t = i / 24
        pts.append(((1 - t) ** 2 * p1[0] + 2 * t * (1 - t) * cx + t * t * p2[0],
                    (1 - t) ** 2 * p1[1] + 2 * t * (1 - t) * cy + t * t * p2[1]))
    return pts


def _text_box(draw, xy, text: str, font) -> tuple[float, float, float, float]:
    box = draw.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    return (xy[0] - w / 2 - 4, xy[1] - h / 2 - 3, xy[0] + w / 2 + 4, xy[1] + h / 2 + 5)


def _label(draw: ImageDraw.ImageDraw, box, text: str, font, color) -> None:
    """线上的字：垫一块白底，压在线上也看得清。"""
    draw.rectangle(box, fill=BG)
    tb = draw.textbbox((0, 0), text, font=font)
    draw.text((box[0] + 4, box[1] + 3 - tb[1]), text, font=font, fill=color)


def _badge(draw: ImageDraw.ImageDraw, xy, num: int, font) -> None:
    x, y = xy
    draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=BG, outline=LINK_COLOR, width=2)
    text = str(num)
    tb = draw.textbbox((0, 0), text, font=font)
    draw.text((x - (tb[2] - tb[0]) / 2, y - (tb[3] - tb[1]) / 2 - tb[1]), text, font=font, fill=LINK_COLOR)


def _node(draw: ImageDraw.ImageDraw, xy, name: str, r: int, size: int, fill, ring=None) -> None:
    x, y = xy
    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=ring or INK, width=4 if ring else 2)
    # 名字放不下先缩字（最小 11），还放不下才截
    font, text = _font(size), name
    while size > 11 and draw.textlength(text, font=font) > 1.8 * r:
        size -= 1
        font = _font(size)
    while len(text) > 2 and draw.textlength(text, font=font) > 1.8 * r:
        text = name[: len(text.rstrip("…")) - 1] + "…"
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2 - box[1]), text, font=font, fill=INK)


def _dash(draw: ImageDraw.ImageDraw, p1, p2, color, width: int, on: float = 10, off: float = 7) -> None:
    length = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1
    ux, uy = (p2[0] - p1[0]) / length, (p2[1] - p1[1]) / length
    t = 0.0
    while t < length:
        e = min(t + on, length)
        draw.line((p1[0] + ux * t, p1[1] + uy * t, p1[0] + ux * e, p1[1] + uy * e), fill=color, width=width)
        t = e + off


def _spoke(draw: ImageDraw.ImageDraw, p1, p2, level: str | None) -> None:
    """她连到一个人的线：颜色是态度，亲近的粗一点，陌生的是虚线。"""
    level = level or "陌生"
    color = ATT_COLORS.get(level, ATT_COLORS["普通"])
    width = 5 if level == "亲近" else 3
    if level in DASHED:
        _dash(draw, p1, p2, color, width)
    else:
        draw.line((p1, p2), fill=color, width=width)


def _legend(draw: ImageDraw.ImageDraw, font, y: float, spokes: bool) -> None:
    """标题下面一行图例：线（人多时是人外面那圈）的颜色 = 她对这人的态度。"""
    x = 24
    for level in ATT_COLORS:
        _spoke(draw, (x, y + 11), (x + 36, y + 11), level)
        draw.text((x + 44, y), level, font=font, fill=INK)
        x += 44 + draw.textlength(level, font=font) + 28
    tip = "名字下面是她和这人的关系" if spokes else "人外圈的颜色是态度，越靠里越亲近；名字下面是她和这人的关系"
    draw.text((x + 8, y), tip, font=font, fill=SOFT_INK)


def arrange(
    center: str,
    people: list[tuple[str, str | None]],
    links: list[tuple[str, str, str]],
    self_names: tuple[str, ...] = (),
) -> tuple[list[str], dict, dict[str, str], list[tuple[str, str, str]]]:
    """排座次：返回（圈上的名字, 态度档, 她和谁的关系, 群友之间的关系）；她的别名和「我」都并到中间。"""
    aliases = tuple(n for n in (center, *self_names) if len(n) >= 2)

    def is_self(name: str) -> bool:
        # 「酱油鱼🐟」这类带后缀的名片也算她
        return name in SELF_WORDS or any(a in name for a in aliases)

    people = [(n, level) for n, level in people if not is_self(n)]
    att = dict(people)
    # 她和某人的关系写在连她的线上，不再单画一个「我」
    self_rel: dict[str, str] = {}
    pair_links: list[tuple[str, str, str]] = []
    for a, b, rel in links:
        if is_self(a) and is_self(b):
            continue
        if is_self(a) or is_self(b):
            self_rel.setdefault(b if is_self(a) else a, rel)
        else:
            pair_links.append((a, b, rel))
    # 有关系的两个人在圈上挨着放，连线短、不横穿中间压住别的字
    near: dict[str, list[str]] = {}
    for a, b, _ in pair_links:
        near.setdefault(a, []).append(b)
        near.setdefault(b, []).append(a)
    names: list[str] = []

    def walk(n: str) -> None:
        # 顺着关系往下走，连着的人排在一起
        names.append(n)
        for m in near[n]:
            if m not in names:
                walk(m)

    for n in near:
        if n not in names:
            walk(n)
    names += [n for n in self_rel if n not in names]
    names += [n for n, _ in people if n not in names]
    return names, att, self_rel, pair_links


def render(
    center: str,
    people: list[tuple[str, str | None]],
    links: list[tuple[str, str, str]],
    notes: list[str] = (),
    title: str = "",
    self_names: tuple[str, ...] = (),
) -> bytes:
    """画一张关系图，返回 PNG。people 是 (名字, 她对这人的态度档)；links 是 (甲, 乙, 关系)；
    notes 是认不出是谁和谁的关系笔记，列在图下面；self_names 是她的别名，和「我」一样都算中间那个。"""
    names, att, self_rel, pair_links = arrange(center, people, links, self_names)
    left_out = max(0, len(names) - MAX_PEOPLE)
    names = names[:MAX_PEOPLE]
    shown = set(names)
    pair_links = [(a, b, rel) for a, b, rel in pair_links if a in shown and b in shown]
    rel_pos, r, outer = layout(names, att, pair_links)
    cf = caption_size(r)
    node_size, f_cap, f_label, f_title = max(14, int(r * 0.46)), _font(cf), _font(17), _font(26)

    spokes = len(names) <= SPOKES_MAX
    half = max(MIN_SIZE / 2, outer + r + 2 * cf + 50)
    width = int(2 * half)
    mid = (half, HEADER + half)
    pos = {n: (mid[0] + x, mid[1] + y) for n, (x, y) in rel_pos.items()}

    scratch = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    # 人、名字下面的关系、中间的她都占着地方，线上的字不能压上去
    taken = [(mid[0] - r - 8, mid[1] - r - 8, mid[0] + r + 8, mid[1] + r + 8)]
    captions: dict[str, list[tuple[tuple, str]]] = {}
    for n in names:
        x, y = pos[n]
        taken.append((x - r, y - r, x + r, y + r))
        lines = caption_lines(self_rel.get(n, ""))
        captions[n] = []
        for i, line in enumerate(lines):
            box = _text_box(scratch, (x, y + r + 4 + cf * 0.7 + i * (cf + 6)), line, f_cap)
            captions[n].append((box, line))
            taken.append(box)

    # 群友之间的关系：地方够就写在线上，挤了就标号、列在下面
    curves, inline, badges, listed = [], [], [], []
    for a, b, rel in pair_links:
        curve = _bow(pos[a], pos[b], mid, max(outer, 200.0))
        curves.append(curve)
        spots = [curve[i] for i in (12, 9, 15, 6, 18)]
        text = _short(rel, 10)
        placed = False
        if len(pair_links) <= INLINE_LINKS:
            for xy in spots:
                box = _text_box(scratch, xy, text, f_label)
                if not any(_overlap(box, t, 2) for t in taken):
                    inline.append((box, text))
                    taken.append(box)
                    placed = True
                    break
        if placed:
            continue
        num = len(listed) + 1
        listed.append(f"{num}. {_short(a, 8)} — {_short(b, 8)}：{_short(rel, 16)}")
        spot = spots[0]
        for xy in spots:
            box = (xy[0] - 13, xy[1] - 13, xy[0] + 13, xy[1] + 13)
            if not any(_overlap(box, t, 1) for t in taken):
                spot = xy
                break
        taken.append((spot[0] - 13, spot[1] - 13, spot[0] + 13, spot[1] + 13))
        badges.append((spot, num))

    notes = [n for n in notes if n][:8]
    cols = max(1, width // 460)
    foot_rows = []
    if listed:
        foot_rows.append(("群友之间（图上的编号）：", [listed[i : i + cols] for i in range(0, len(listed), cols)]))
    if notes:
        foot_rows.append(("认不出是谁和谁的关系：", [[f"· {_short(n, 24)}"] for n in notes]))
    if left_out:
        foot_rows.append((f"人太多，还有 {left_out} 个记过的群友没画进来（按熟悉程度挑的）", []))
    foot = sum(ROW * (1 + len(rows)) + 10 for _, rows in foot_rows)
    img = Image.new("RGB", (width, int(HEADER + 2 * half + foot + (20 if foot else 0))), BG)
    draw = ImageDraw.Draw(img)

    # 先画线再画圈，圈压在线头上；没记过好感的（只在群日记里出现）按陌生算
    colors = {n: ATT_COLORS.get(att.get(n) or "陌生", ATT_COLORS["普通"]) for n in names}
    if spokes:
        for n in names:
            _spoke(draw, mid, pos[n], att.get(n))
    else:
        # 人多不画她连出去的线，画几道淡淡的圈当参考：越靠里越亲近
        for rad in sorted({round(math.hypot(x, y)) for x, y in rel_pos.values()}):
            draw.ellipse((mid[0] - rad, mid[1] - rad, mid[0] + rad, mid[1] + rad), outline=(236, 238, 242), width=1)
    for curve in curves:
        draw.line(curve, fill=LINK_COLOR, width=2 if len(curves) > INLINE_LINKS else 3, joint="curve")
    _node(draw, mid, center, r + 8, max(16, int(r * 0.5)), SELF_FILL)
    for n in names:
        _node(draw, pos[n], n, r, node_size, NODE_FILL, None if spokes else colors[n])
        for box, line in captions[n]:
            _label(draw, box, line, f_cap, SOFT_INK)
    for box, text in inline:
        _label(draw, box, text, f_label, LINK_COLOR)
    for xy, num in badges:
        _badge(draw, xy, num, _font(13))

    if title:
        draw.text((24, 18), title, font=f_title, fill=INK)
    _legend(draw, f_label, 62, spokes)
    y = HEADER + 2 * half + 10
    col_w = width / cols
    for head, rows in foot_rows:
        draw.text((24, y), head, font=f_label, fill=INK)
        y += ROW
        for row in rows:
            for i, item in enumerate(row):
                draw.text((40 + i * col_w, y), item, font=f_label, fill=INK)
            y += ROW
        y += 10
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
