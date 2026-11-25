"""把仓库 stickers/ 的表情库搬到 dsh-roost 的表情包目录。

roost 的表情库没有索引 JSON：一级子目录 = 分类，文件名 = 标签，
同名 ``.tags`` 侧车（``标签, 标签; 场合``）优先于文件名；分类说明写 ``_desc.txt``。
本工具只做搬运（复制），不改仓库里的任何文件，可重复执行。

用法：
    python tools/port_stickers_to_roost.py --dry-run
    python tools/port_stickers_to_roost.py
    python tools/port_stickers_to_roost.py --target "D:/表情包" --keep-names
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

SRC = Path("stickers")
DEFAULT_TARGET = Path.home() / ".dsh" / "dsh-roost" / "stickers"

# 我们自己的分类 → roost 里给模型看的分类名（“无文字/其他”当分类名会误导）
CATEGORY_MAP = {"无文字": "通用", "其他": "杂图"}
CATEGORY_DESC = {
    "通用": "没有字的纯图，情绪和反应都靠表情，最常用",
    "杂图": "不好归类的图，用得少",
    "疑问": "表示疑惑、问号脸",
    "卖萌": "装可爱、撒娇",
    "生气": "炸毛、生气、凶",
    "搞笑": "搞笑、笑死",
    "拒绝": "拒绝、不要",
    "夸奖": "夸奖、夸人",
}
MAX_TAGS = 5


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def clean_category(name: str, keep_names: bool) -> str:
    raw = (name or "").strip() or "未分类"
    if keep_names:
        return raw
    out = CATEGORY_MAP.get(raw, raw)
    bad = '<>:"/\\|?*'
    for ch in bad:
        out = out.replace(ch, "_")
    return out or "未分类"


NOISE_TAGS = {"静图", "动图", "方图", "横图", "竖图", "有文字", "无文字", "透明", "暖", "冷", "中性"}


def sidecar_text(item: dict, read: dict, note: str, cat: str) -> str:
    tags: list[str] = []

    def add(tag: str, limit: int = 8) -> None:
        tag = str(tag or "").strip()
        if tag and len(tag) <= limit and tag not in NOISE_TAGS and tag not in tags:
            tags.append(tag)

    add(cat)
    add(read.get("mean") or "", 6)
    for tag in item.get("tags") or []:
        add(tag)
    usage = str(read.get("scene") or "").strip() or note.strip() or str(read.get("desc") or "").strip()
    usage = usage.replace("\r", " ").replace("\n", " ")[:60]
    tags = tags[:MAX_TAGS]
    if tags and usage:
        return ", ".join(tags) + "; " + usage
    if tags:
        return ", ".join(tags)
    return usage


def main() -> int:
    ap = argparse.ArgumentParser(description="把 stickers/ 搬到 dsh-roost 表情包目录")
    ap.add_argument("--src", default=str(SRC), help="仓库里的表情库目录（默认 stickers）")
    ap.add_argument("--target", default=str(DEFAULT_TARGET), help="roost 的表情包目录")
    ap.add_argument("--dry-run", action="store_true", help="只看会搬多少，不落盘")
    ap.add_argument("--keep-names", action="store_true", help="分类名原样搬运，不做映射")
    ap.add_argument("--limit", type=int, default=0, help="最多搬几张（调试用）")
    args = ap.parse_args()

    src = Path(args.src)
    target = Path(args.target)
    data = load_json(src / "index.json", {})
    items = data.get("items") or []
    notes = load_json(src / "notes.json", {})
    reads = load_json(src / "reads.json", {})
    if not items:
        print(f"[错误] {src / 'index.json'} 里没有 items")
        return 2

    if args.limit:
        items = items[: args.limit]

    copied = skipped_missing = overwritten = 0
    per_cat: dict[str, int] = {}
    mapping: dict[str, str] = {}
    for item in items:
        rel = item.get("file") or ""
        src_file = src / rel
        if not rel or not src_file.is_file():
            skipped_missing += 1
            continue
        cat = clean_category(item.get("category") or "", args.keep_names)
        mapping[item.get("category") or ""] = cat
        dest_dir = target / cat
        dest = dest_dir / f"{item.get('id')}{src_file.suffix.lower()}"
        side = dest.with_name(dest.name + ".tags")
        text = sidecar_text(item, reads.get(item.get("id")) or {}, (notes.get(item.get("id")) or {}).get("note") or "", cat)
        per_cat[cat] = per_cat.get(cat, 0) + 1
        if not args.dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                overwritten += 1
            shutil.copy2(src_file, dest)
            side.write_text(text + "\n", encoding="utf-8")
        copied += 1

    if not args.dry_run:
        for cat, count in per_cat.items():
            desc = CATEGORY_DESC.get(cat, "")
            if desc:
                (target / cat / "_desc.txt").write_text(desc + "\n", encoding="utf-8")
        manifest = {
            "src": str(src.resolve()),
            "target": str(target.resolve()),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "copied": copied,
            "overwritten": overwritten,
            "missing": skipped_missing,
            "categories": per_cat,
            "category_map": mapping,
        }
        (target / "port-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    mode = "演练（未落盘）" if args.dry_run else "已搬运"
    print(f"{mode}：{copied} 张，缺文件 {skipped_missing} 张，覆盖 {overwritten} 张")
    for cat, count in sorted(per_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {cat}: {count}")
    print(f"目标目录：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
