"""把 OCR 文本并进 index.json，按语义打分类标签。

用法：
    python tag_stickers.py --dir Z:\\snowluma\\stickers
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# 顺序有意义：先匹配更具体的
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("生气", ("气死", "生气", "怒", "凶", "咬", "打死", "傻逼", "闭嘴", "烦", "滚")),
    ("无语", ("无语", "汗", "服了", "离谱", "醉了", "绷不住", "裂开", "麻了", "难受")),
    ("搞笑", ("哈哈", "笑死", "草", "乐死", "搞笑", "绷", "笑不活", "乐子")),
    ("卖萌", ("可爱", "亲亲", "抱抱", "么么", "喵", "呜", "委屈", "求", "喜欢")),
    ("拒绝", ("不行", "不要", "拒绝", "不可能", "才不", "免谈", "没门")),
    ("催促", ("搞快", "快点", "急", "速来", "速速", "马上")),
    ("问候", ("你好", "在吗", "早安", "晚安", "哈喽", "hello", "嗨", "早上好", "晚上好")),
    ("回应", ("好的", "可以", "行吧", "收到", "嗯", "ok", "没问题", "是啊", "对的", "懂了")),
    ("疑问", ("为什么", "怎么", "啥", "吗", "呢", "?", "？")),
    ("夸奖", ("牛", "强", "厉害", "666", "绝了", "牛逼", "好活")),
    ("惊讶", ("卧槽", "我靠", "震惊", "真的假的", "离谱")),
]


def classify(text: str) -> tuple[str, list[str]]:
    if not text:
        return "无文字", []

    hits: list[str] = []
    category = "其他"
    for name, words in CATEGORY_RULES:
        matched = [w for w in words if w in text]
        if matched:
            hits.extend(matched)
            if category == "其他":
                category = name
    return category, sorted(set(hits))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=r"Z:\snowluma\stickers")
    args = ap.parse_args()

    root = Path(args.dir)
    index_path = root / "index.json"
    ocr_paths = [root / "ocr.jsonl", root / "ocr2.jsonl"]

    index = json.loads(index_path.read_text(encoding="utf-8"))
    ocr: dict[str, str] = {}
    for ocr_path in ocr_paths:
        if not ocr_path.is_file():
            continue
        for line in ocr_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = str(item.get("file", ""))
            text = str(item.get("text", ""))
            # 两次 OCR 取更长的结果（通常更完整）
            if len(text) > len(ocr.get(name, "")):
                ocr[name] = text

    for item in index["items"]:
        filename = Path(item["file"]).name
        text = ocr.get(filename, "")
        category, hits = classify(text)
        item["text"] = text
        item["category"] = category
        tags = list(item.get("tags", []))
        tags.append(category)
        tags.extend(hits)
        tags.append("有文字" if text else "无文字")
        item["tags"] = sorted(set(tags))

    index["count"] = len(index["items"])
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    cats = Counter(item["category"] for item in index["items"])
    print("分类分布：")
    for name, n in cats.most_common():
        print(f"  {name:<6} {n}")

    print("\n带文字样例：")
    shown = 0
    for item in index["items"]:
        if item["text"] and shown < 8:
            print(f"  [{item['category']}] {item['text'][:20]}  -> {item['file']}")
            shown += 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

