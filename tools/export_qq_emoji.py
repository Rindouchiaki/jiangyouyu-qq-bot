"""从本机 QQ NT 数据目录导出收藏表情，生成索引。

只读源目录，不改动 QQ 的任何文件。

用法：
    python export_qq_emoji.py --src "<...>\\nt_data\\Emoji\\personal_emoji\\Ori" --out stickers
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def dominant_tone(img: Image.Image) -> str:
    """粗略分冷/暖/中性色调。"""
    small = img.convert("RGB").resize((32, 32))
    pixels = list(small.getdata())
    r = sum(p[0] for p in pixels) / len(pixels)
    b = sum(p[2] for p in pixels) / len(pixels)
    if r - b > 18:
        return "暖色"
    if b - r > 18:
        return "冷色"
    return "中性"


def shape_tag(w: int, h: int) -> str:
    if w == h:
        return "方图"
    ratio = w / h
    if ratio > 1.4:
        return "横图"
    if ratio < 0.7:
        return "竖图"
    return "近方图"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "stickers"))
    ap.add_argument("--limit", type=int, default=0, help="只导出前 N 张，0 = 全部")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_dir():
        raise SystemExit(f"源目录不存在: {src}")

    out = Path(args.out)
    ori_dir = out / "ori"
    ori_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    if args.limit:
        files = files[: args.limit]

    index = []
    seen: set[str] = set()
    dup = 0
    skipped = 0

    for i, path in enumerate(files, 1):
        try:
            data = path.read_bytes()
        except OSError:
            skipped += 1
            continue

        digest = hashlib.sha256(data).hexdigest()[:16]
        if digest in seen:
            dup += 1
            continue
        seen.add(digest)

        try:
            with Image.open(path) as img:
                width, height = img.size
                animated = bool(getattr(img, "is_animated", False))
                fmt = (img.format or path.suffix.lstrip(".")).lower()
                tone = dominant_tone(img)
                has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
        except Exception:  # noqa: BLE001
            skipped += 1
            continue

        ext = ".gif" if animated and fmt != "webp" else f".{fmt}"
        name = f"{digest}{ext}"
        target = ori_dir / name
        if not target.exists():
            shutil.copy2(path, target)

        tags = [shape_tag(width, height), tone]
        tags.append("动图" if animated else "静图")
        if has_alpha:
            tags.append("透明")

        index.append(
            {
                "id": digest,
                "file": f"ori/{name}",
                "format": fmt,
                "animated": animated,
                "width": width,
                "height": height,
                "bytes": len(data),
                "tags": tags,
                "text": "",
            }
        )

        if i % 100 == 0:
            print(f"  处理 {i}/{len(files)} ...", flush=True)

    (out / "index.json").write_text(
        json.dumps({"source": str(src), "count": len(index), "items": index},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    tag_counter = Counter(t for item in index for t in item["tags"])
    print(f"\n导出完成：{len(index)} 张去重后图片 -> {ori_dir}")
    print(f"  重复跳过 {dup}，读取失败 {skipped}")
    print(f"  标签分布：{dict(tag_counter)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
