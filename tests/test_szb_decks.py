"""影之诗卡组库的离线测试（不联网、不启 NoneBot）。

用临时目录当数据目录，别碰线上那份 `bot/data/szb_decks`。
"""

import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

TMP = tempfile.mkdtemp(prefix="szb-test-")
os.environ["SZB_DECK_DIR"] = TMP

from PIL import Image  # noqa: E402

import szb_decks  # noqa: E402


def _png(color: tuple[int, int, int], size=(40, 60)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    # 职业别名
    assert szb_decks.parse_class("皇家") == "皇家"
    assert szb_decks.parse_class("皇") == "皇家"
    assert szb_decks.parse_class("精灵") == "妖精"
    assert szb_decks.parse_class("复仇者") == "超越者"
    assert szb_decks.parse_class("死灵") == "梦魇"
    assert szb_decks.parse_class("巫师") == "法师"
    assert szb_decks.parse_class("主教") == "主教"
    assert szb_decks.parse_class("跳费龙") == "龙族"
    assert szb_decks.parse_class("今天吃什么") is None

    # 环境
    assert szb_decks.parse_env("无限") == "无限"
    assert szb_decks.parse_env("轮换") == "指定"
    assert szb_decks.parse_env("") is None

    # 一句话拆参数
    q = szb_decks.parse_query("皇家 无限 控制皇")
    assert q == {"cls": "皇家", "env": "无限", "name": "控制皇"}, q
    q = szb_decks.parse_query("皇家")
    assert q["cls"] == "皇家" and q["env"] is None and q["name"] is None, q

    # 入库
    deck = szb_decks.add_deck(name="控制皇", cls="皇家", env="指定", image=_png((200, 0, 0)))
    # 整句正好是卡组名 → 不算「职业 + 名字」，原样当名字（「中速梦」这种老查询靠这条）
    assert szb_decks.parse_query("控制皇") == {"cls": None, "env": None, "name": "控制皇"}
    # 名字自动编号（皇 + 序号），原来的说法留作别名
    assert deck["name"] == "皇1" and deck["alias"] == "控制皇" and deck["source"] == "submit", deck
    assert szb_decks.deck_num(deck) == 1
    assert szb_decks.find_one("控制皇")["id"] == deck["id"], "别名也要能查到"
    assert szb_decks.find_by_num(1)["id"] == deck["id"], "按序号也要能查到"
    assert (szb_decks.DATA_DIR / deck["image"]).is_file()

    # 同图再交 → 拒
    try:
        szb_decks.add_deck(name="控制皇2", cls="皇家", env="指定", image=_png((200, 0, 0)))
    except szb_decks.DeckError as exc:
        assert "已经收过" in str(exc), exc
    else:
        raise AssertionError("同图应该被拒")

    # 同名不同图 → 加投稿人 QQ 后缀
    second = szb_decks.add_deck(
        name="控制皇",
        cls="皇家",
        env="指定",
        image=_png((0, 200, 0)),
        author={"uin": "289635657", "nick": "酱酱鱼"},
    )
    assert second["name"] == "皇2" and second["alias"] == "控制皇", second

    # 另一个环境同名不算冲突
    other_env = szb_decks.add_deck(name="控制皇", cls="皇家", env="无限", image=_png((0, 0, 200)))
    assert other_env["name"] == "皇3" and other_env["alias"] == "控制皇", other_env

    # 查询与排序
    hits = szb_decks.list_decks("皇家", "指定")
    assert {d["name"] for d in hits[:2]} == {"皇1", "皇2"}, hits
    assert szb_decks.find_one("控制皇", "指定", "皇家")["id"] == deck["id"]
    assert szb_decks.find_one("控制皇", "无限", "皇家")["id"] == other_env["id"]

    # 人设用：整名命中优先，模糊的也能挑一个
    best = szb_decks.best_match("控制皇现在能打吗", "皇家", "指定")
    assert best and best["id"] == deck["id"], best
    assert szb_decks.best_match("今天天气不错", None, None) is None

    # 给模型的备注最多两套
    note = szb_decks.deck_note("皇家", "指定")
    assert "控制皇" in note and note.count("；") <= 1, note

    # 多图：一套卡组可以有好几张图（卡组图 + 对局/构筑），全都存下来
    multi = szb_decks.add_deck(
        name="多图龙",
        cls="龙族",
        env="指定",
        images=[_png((10, 20, 30)), _png((40, 50, 60)), _png((70, 80, 90))],
    )
    assert len(multi["images"]) == 3, multi
    assert multi["image"] == multi["images"][0], multi
    for rel in multi["images"]:
        assert (szb_decks.DATA_DIR / rel).is_file(), rel

    # 同一组图再交一次 → 拒（hash 按整组算）
    try:
        szb_decks.add_deck(
            name="多图龙2",
            cls="龙族",
            env="指定",
            images=[_png((10, 20, 30)), _png((40, 50, 60)), _png((70, 80, 90))],
        )
    except szb_decks.DeckError as exc:
        assert "已经收过" in str(exc), exc
    else:
        raise AssertionError("同一组图应该被拒")

    # 补图：整组换成两张，多出来的那张旧图要删掉
    leftover = szb_decks.DATA_DIR / multi["images"][2]
    assert szb_decks.replace_images(multi["id"], [_png((1, 2, 3)), _png((4, 5, 6))]) == 2
    again = szb_decks.find_one("多图龙", "指定", "龙族")
    assert len(again["images"]) == 2, again
    assert not leftover.exists(), leftover

    # 统计
    st = szb_decks.stats()
    assert st["total"] == 4 and st["by_cls"]["皇家"] == 3 and st["by_cls"]["龙族"] == 1, st

    # 删除权限
    try:
        szb_decks.remove_deck(deck["id"], by_uin="10000", is_dev=False)
    except szb_decks.DeckError as exc:
        assert "自己" in str(exc), exc
    else:
        raise AssertionError("不是本人应该删不掉")
    assert szb_decks.remove_deck(second["id"], by_uin="289635657") is True
    assert szb_decks.stats()["total"] == 3


    # 聊天里问卡组：认得出「问卡组」并挑一套
    assert szb_decks.wants_deck("皇家有什么卡组推荐")
    assert szb_decks.wants_deck("影之诗现在上分用什么卡组")
    assert not szb_decks.wants_deck("今天吃了什么")
    assert not szb_decks.wants_deck("皇家")
    picked = szb_decks.suggest("皇家有什么卡组推荐")
    assert picked is not None and picked["cls"] == "皇家", picked
    assert "必须答这套" in szb_decks.note_for(picked)

    print("test_szb_decks: 全部通过")
    print("tmp:", TMP)


if __name__ == "__main__":
    main()
