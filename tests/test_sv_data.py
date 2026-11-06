"""影之诗卡牌资料模块的离线测试（不联网、不启 NoneBot）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

import persona_rules  # noqa: E402
import sv_data  # noqa: E402


def main() -> None:
    cards = sv_data.load(force=True)
    assert len(cards) > 900, f"卡牌数量不对：{len(cards)}"
    # 图片索引在的话，图要真的配上（以前第一轮读出来全是空图）
    if sv_data.IMAGE_INDEX.exists():
        assert any(c["image"] for c in cards), "图片索引在，但没有一张配上卡图"

    # 精确查
    hit = sv_data.find("天枪深渊")
    assert hit and hit[0]["name"] == "天枪深渊", hit[:3]
    card = hit[0]
    assert card["cost"] == 1 and card["type"] == "法术", card
    assert "进化" in card["skill"], card["skill"]
    assert sv_data.brief(card).startswith("天枪深渊（1费 0/0"), sv_data.brief(card)

    # 模糊查：只记得半个名字
    part = sv_data.find("水之妖精")
    assert any(c["name"] == "纯真的水之妖精" for c in part), [c["name"] for c in part]

    # 一句话里点了名：整名优先，别把「妖精」这种子串也算一遍
    names = [c["name"] for c in sv_data.mention("纯真的水之妖精这张卡怎么样")]
    assert names == ["纯真的水之妖精"], names
    assert sv_data.mention("今天中午吃什么") == []

    # 给模型的参考资料：带上费用、身材、能力和卡包，最多两张
    note = sv_data.for_prompt(sv_data.mention("天枪深渊和妖精"))
    assert "「天枪深渊」1费 0/0" in note, note
    assert "能力：" in note, note
    assert note.count("\n") <= 1, note

    # 资料块进 messages 时是 user 角色、标明只作参考
    msgs = persona_rules.compose_messages(
        [], "小红", "天枪深渊这张卡怎么样", sv_note=note,
    )
    joined = "\n".join(m["content"] for m in msgs)
    assert "影之诗的卡片资料，只作参考" in joined, joined
    assert "天枪深渊" in joined
    assert all(m["role"] in ("system", "user", "assistant") for m in msgs)

    # 没有资料就不塞这个块
    plain = persona_rules.compose_messages([], "小红", "在吗")
    assert "影之诗的卡片资料" not in "\n".join(m["content"] for m in plain)

    # 模糊检索：名字完全一样是最高分，命中方式对得上
    exact = sv_data.search("天枪深渊")
    assert exact and exact[0][0] == sv_data.SCORE_EXACT and exact[0][2] == "exact", exact[:2]

    # 打错一个字也认得出来，分数低于「开头匹配」，并标明是 fuzzy
    fuzzy = sv_data.search("天枪深渊笼")
    assert fuzzy and fuzzy[0][1]["name"] == "天枪深渊", fuzzy[:2]
    assert fuzzy[0][2] == "fuzzy" and fuzzy[0][0] < sv_data.SCORE_PREFIX, fuzzy[0]

    # 只记得几个字：名字里含的都列出来
    inner = [c for _, c, why in sv_data.search("水之妖精", limit=8) if why in ("prefix", "inner")]
    assert any(c["name"] == "纯真的水之妖精" for c in inner), [c["name"] for c in inner]

    # 效果里的词也能找：库里有「疾驰」的卡不止一张
    skill = [c for _, c, why in sv_data.search("疾驰", limit=8) if why == "skill"]
    assert skill, "效果检索没命中"

    # 完全无关的词不乱给
    assert sv_data.search("今天中午吃什么") == []

    # 详情：身材、职业、能力、进化后都写全
    detail = sv_data.detail(card)
    assert detail.startswith("天枪深渊（1费 0/0，"), detail
    assert "能力：" in detail, detail

    print("test_sv_data: 全部通过")


if __name__ == "__main__":
    main()

# ---- 条件筛选（职业 / 身材 / 能力词条）----

spec = sv_data.parse_filters("皇 5/4/4 疾驰")
assert spec["cls"] == ["皇家"], spec
assert (spec["cost"], spec["atk"], spec["life"]) == (5, 4, 4), spec
assert spec["abilities"] == ["疾驰"], spec

spec = sv_data.parse_filters("妖精 2/2")
assert spec["cls"] == ["精灵"] and spec["cost"] == 2 and spec["atk"] == 2 and spec["life"] is None, spec

spec = sv_data.parse_filters("主教 疾驰 守护")
assert spec["cls"] == ["主教"] and spec["abilities"] == ["疾驰", "守护"], spec

spec = sv_data.parse_filters("疾驰守护")
assert spec["abilities"] == ["疾驰守护"], spec

spec = sv_data.parse_filters("天枪深渊")
assert spec["names"] == ["天枪深渊"] and not sv_data.has_filters(spec), spec

assert sv_data.describe_filters(sv_data.parse_filters("皇 5/4/4 疾驰")) == "皇家 5费 4/4 疾驰"

cards, total = sv_data.filter_cards(sv_data.parse_filters("皇"), limit=3)
assert total >= 1 and all(c["class"] == "皇家" for c in cards), (total, cards)

cards, total = sv_data.filter_cards(sv_data.parse_filters("疾驰守护"), limit=3)
assert total >= 1 and "疾驰" in cards[0]["skill"] or "疾驰" in cards[0].get("evo_skill", ""), cards

cards, total = sv_data.filter_cards(sv_data.parse_filters("中立 99/99/99"), limit=3)
assert total == 0 and cards == [], (total, cards)

print("test_sv_data: 条件筛选全部通过")

# ---- 数据库 ID / 列表行 / 进化前后卡图 ----

fresh = sv_data.load()
sample = sv_data.find("天枪深渊")[0]
assert sv_data.by_id(sample["id"])["name"] == "天枪深渊"
assert sv_data.by_id("99999999") is None
assert sv_data.by_id("天枪深渊") is None
assert sv_data.line(sample) == f"{sample['id']} 天枪深渊 1/0/0", sv_data.line(sample)
if sv_data.IMAGE_INDEX.exists():
    with_evo = [c for c in fresh if c.get("evo_image")]
    assert with_evo, "图片索引里带了 evo_file，却没有一张卡配上进化图"
    assert all(Path(c["evo_image"]).exists() for c in with_evo[:20])

print("test_sv_data: ID / 列表行 / 进化图全部通过")
