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

    print("test_sv_data: 全部通过")


if __name__ == "__main__":
    main()
