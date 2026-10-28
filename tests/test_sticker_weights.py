"""表情抽选的权重校验：用得多 / 刚发过 / 同分类连发，都要被压下去。"""

import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sticker_w_"))
os.environ["STICKER_DIR"] = str(TMP)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import sticker_lib as lib  # noqa: E402


def main() -> int:
    # 跳过 load()：直接塞合成数据，避免依赖真的表情库
    lib._items = [
        {"id": "a", "file": "a.jpg", "category": "其他"},
        {"id": "b", "file": "b.jpg", "category": "其他"},
        {"id": "c", "file": "c.jpg", "category": "疑问"},
    ]
    lib._notes = {"a": {"note": "", "uses": 20}, "b": {"note": "", "uses": 0}}
    lib._pick_hist.clear()
    lib._cat_used.clear()
    lib._by_cat.clear()
    for it in lib._items:
        lib._by_cat.setdefault(it["category"], []).append(it)

    fresh = lib._weight(lib._items[1])                 # 没用过
    used = lib._weight(lib._items[0])                  # 用过 20 次
    assert fresh == 1.0 and used < 0.1, (fresh, used)
    print(f"PASS  用得多的降权：fresh={fresh:.2f} used={used:.3f}")

    lib._pick_hist["g1"] = ["b"]
    assert lib._weight(lib._items[1], "g1") < fresh * 0.1
    lib._pick_hist["g1"] = ["a", "c", "b"]
    assert lib._weight(lib._items[1], "g1") < fresh * 0.5
    print("PASS  最近刚发过的降权（第 1 张最狠，前 3 / 前 8 张递减）")

    lib._pick_hist.clear()
    lib._cat_used["g2"] = Counter({"其他": 4})
    cat_used = lib._weight(lib._items[1], "g2")
    lib._cat_used["g2"] = Counter()
    cat_free = lib._weight(lib._items[1], "g2")
    assert cat_used < cat_free * 0.7, (cat_used, cat_free)
    print(f"PASS  同分类连发降权：{cat_free:.2f} → {cat_used:.2f}")

    # 连抽 50 次，别让同一张占大头
    lib._items = [{"id": f"x{i}", "file": f"x{i}.jpg", "category": "其他"} for i in range(20)]
    lib._notes = {}
    lib._pick_hist.clear()
    lib._cat_used.clear()
    picked = Counter()
    for _ in range(200):
        item = lib.pick("", "g3")
        assert item is not None
        picked[item["id"]] += 1
    top, count = picked.most_common(1)[0]
    assert len(picked) >= 12 and count < 40, (count, len(picked))
    print(f"PASS  200 次抽到 {len(picked)} 张不同的，最高一张 {count} 次（不锁死几张）")

    # 连着抽不许重复上一张（池子够大时）
    last = None
    for _ in range(20):
        cur = lib.pick("", "g4")["id"]
        assert cur != last, "连着两次发了同一张"
        last = cur
    print("PASS  池子够大时不会连着发同一张")

    # 按心情挑：心情分类只占一部分，其余分给中性表情，不能只围着 5 张转
    lib._items = (
        [{"id": f"ang{i}", "file": f"ang{i}.jpg", "category": "生气"} for i in range(5)]
        + [{"id": f"non{i}", "file": f"non{i}.jpg", "category": "无文字"} for i in range(40)]
        + [{"id": f"oth{i}", "file": f"oth{i}.jpg", "category": "其他"} for i in range(20)]
        + [{"id": "rej0", "file": "rej0.jpg", "category": "拒绝"}]
    )
    lib._by_cat.clear()
    for it in lib._items:
        lib._by_cat.setdefault(it["category"], []).append(it)
    lib._notes = {}
    lib._pick_hist.clear()
    lib._cat_used.clear()
    seen = Counter()
    cats = Counter()
    for i in range(120):
        item = lib.pick_for_mood("炸毛", f"mood{i % 3}")
        seen[item["id"]] += 1
        cats[item["category"]] += 1
    assert len(seen) >= 25, f"只抽到 {len(seen)} 张"
    assert cats["生气"] > 20 and cats["无文字"] > 10, cats
    assert cats["拒绝"] == 0, "只有 1 张的分类不该被抽到"
    print(f"PASS  炸毛时 {len(seen)} 张不同、生气 {cats['生气']}/120、无文字 {cats['无文字']}/120")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
