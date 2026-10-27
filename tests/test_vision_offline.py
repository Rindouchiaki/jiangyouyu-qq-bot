"""vision.py 的离线校验：不连 QQ、不联网，走本地文件 + Windows OCR。"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import vision  # noqa: E402

STICKER_DIR = Path(r"Z:\snowluma\stickers")
OUT = Path(r"Z:\snowluma\_research\vision_test.png")


class Seg:
    type = "image"

    def __init__(self, uri: str) -> None:
        self.data = {"file": uri}


class FakeEvent:
    def __init__(self, segs) -> None:
        self._segs = segs

    def get_message(self):
        return self._segs


def make_text_image(path: Path, text: str = "HELLO WORLD 123") -> None:
    img = Image.new("RGB", (900, 240), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=90)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    draw.text((40, 70), text, fill="black", font=font)
    img.save(path)


def main() -> int:
    ok = True

    # 1) 表情库命中：sha1 路径
    item = json.loads((STICKER_DIR / "index.json").read_text(encoding="utf-8"))["items"][0]
    uri = (STICKER_DIR / item["file"]).resolve().as_uri()
    card = asyncio.run(vision.image_card(FakeEvent([Seg(uri)])))
    print("sticker card:", card)
    ok &= card.startswith("[表情:")

    # 2) 未知图片 -> OCR
    OUT.parent.mkdir(parents=True, exist_ok=True)
    make_text_image(OUT)
    card2 = asyncio.run(vision.image_card(FakeEvent([Seg(OUT.resolve().as_uri())])))
    print("ocr card:", card2)
    ok &= "HELLO" in card2 or "hello" in card2.lower()

    # 3) 缓存命中（第二次不再跑 OCR）
    card3 = asyncio.run(vision.image_card(FakeEvent([Seg(OUT.resolve().as_uri())])))
    ok &= card3 == card2

    # 4) 文本清洗
    ok &= vision._clean_text("生活 苦涩·\n@咿呀") == "生活苦涩咿呀"

    print("stats:", vision.stats())
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
