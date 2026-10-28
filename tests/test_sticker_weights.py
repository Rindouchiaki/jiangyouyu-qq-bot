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

    # 读后感：可爱二次元更常发，没看懂的不算读过
    lib._items = [{"id": "cute", "file": "cute.gif", "category": "其他"}, {"id": "real", "file": "real.jpg", "category": "其他"},
                  {"id": "blank", "file": "blank.jpg", "category": "其他"}]
    lib._notes, lib._reads = {}, {}
    lib._pick_hist.clear()
    lib._cat_used.clear()
    lib.set_read("cute", {"desc": "猫耳少女眨眼", "mean": "卖萌", "scene": "撒娇", "acg": True, "cute": 3})
    lib.set_read("real", {"desc": "真人摊手", "mean": "无奈", "scene": "没办法", "acg": False, "cute": 0})
    lib.set_read("blank", {"desc": "", "mean": "", "scene": "", "acg": False, "cute": 0})
    w = {it["id"]: lib._weight(it) for it in lib._items}
    assert w["cute"] == 2.0 and w["real"] == 0.5 and w["blank"] == 1.0, w
    assert lib.read_of("blank") is None and lib.has_read("blank") and lib.next_unread() is None
    assert lib.label(lib._items[0]) == "卖萌" and lib.label(lib._items[2]) == "其他"
    assert lib.pick_for_scene(("撒娇",))["id"] == "cute"  # 读后感里的场景也能用来找图
    assert (TMP / "reads.json").is_file()
    print("PASS  读后感：可爱二次元权重 ×2、别的画风 ×0.5，没看懂的不算，场景能找到图")

    # 定期清收藏：别太严，真不喜欢的 30 天、其余 90 天一次没发过才删
    import json
    import time
    now = time.time()
    (TMP / "saved").mkdir(exist_ok=True)
    saved = [
        {"id": "s_real_old", "file": "saved/s_real_old.jpg", "category": "收藏", "saved_at": now - 40 * 86400},
        {"id": "s_real_new", "file": "saved/s_real_new.jpg", "category": "收藏", "saved_at": now - 10 * 86400},
        {"id": "s_real_used", "file": "saved/s_real_used.jpg", "category": "收藏", "saved_at": now - 40 * 86400},
        {"id": "s_acg_old", "file": "saved/s_acg_old.jpg", "category": "收藏", "saved_at": now - 40 * 86400},
        {"id": "s_acg_idle", "file": "saved/s_acg_idle.jpg", "category": "收藏", "saved_at": now - 100 * 86400},
        {"id": "s_unread", "file": "saved/s_unread.jpg", "category": "收藏", "saved_at": now - 40 * 86400},
    ]
    for it in saved:
        (TMP / it["file"]).write_bytes(b"x")
    (TMP / "saved.json").write_text(json.dumps({"items": saved}), encoding="utf-8")
    real = {"desc": "真人", "mean": "", "scene": "", "acg": False, "cute": 0}
    for sid in ("s_real_old", "s_real_new", "s_real_used"):
        lib.set_read(sid, real)
    for sid in ("s_acg_old", "s_acg_idle"):
        lib.set_read(sid, {"desc": "二次元少女", "mean": "", "scene": "", "acg": True, "cute": 1})
    lib._notes = {"s_real_used": {"note": "", "uses": 1}}
    gone = lib.prune(now, 30, 90)
    assert sorted(it["id"] for it in gone) == ["s_acg_idle", "s_real_old"], gone
    left = {it["id"] for it in json.loads((TMP / "saved.json").read_text(encoding="utf-8"))["items"]}
    assert left == {"s_real_new", "s_real_used", "s_acg_old", "s_unread"} and not (TMP / "saved/s_real_old.jpg").exists()
    print("PASS  清收藏：真不喜欢的 30 天、其余 90 天一次没发过才删；发过一次就留着")

    # 收藏满了：先挤掉最不喜欢的，不是最早的
    import io
    from PIL import Image
    lib.SAVE_MAX = 4
    lib.load()
    real = {"desc": "真人", "mean": "", "scene": "", "acg": False, "cute": 0}
    lib.set_read("s_real_new", real)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "pink").save(buf, format="PNG")
    item = lib.save_sticker(buf.getvalue(), "收藏")
    left = {it["id"] for it in json.loads((TMP / "saved.json").read_text(encoding="utf-8"))["items"]}
    assert item["id"] in left and "s_real_new" not in left and "s_acg_old" in left, left
    print("PASS  收藏满了先挤掉最不喜欢、最少用的")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
