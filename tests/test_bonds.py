"""bonds（群友小本本）的离线校验：临时目录里读写，不连 QQ、不调模型。"""

import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="bonds_"))
os.environ["PERSONA_DATA_DIR"] = str(TMP)
os.environ["DIARY_USER_NOTES"] = "3"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import bonds  # noqa: E402
from persona_rules import visible_notes  # noqa: E402


def main() -> int:
    assert bonds.DATA_FILE.parent == TMP
    # 群里和私聊里是同一个 QQ 号，就是同一条记录
    bonds.touch("10001", "小明", 0, now=1000.0)
    bonds.add_user_notes("10001", ["喜欢原神"], "g123", now=1001.0)
    bonds.touch("10001", "明明", 0, now=2000.0)
    bonds.add_user_notes("10001", ["最近在找工作"], "p", now=2001.0)
    rec = bonds.user("10001")
    assert rec["name"] == "明明" and rec["fam"] == 9 and len(rec["notes"]) == 2, rec  # 熟悉度按天，同一天只 +1
    judged = bonds.judge("10001", 2, now=2100.0)
    assert judged["aff"] == rec["aff"] + 2 and judged["fam"] == rec["fam"] and judged["last"] == rec["last"], judged
    assert bonds.judge("88888", 2) is None and "88888" not in bonds._data["users"]  # 打分不建新记录
    assert sum(bonds._data["users"]["10001"]["hrs"]) == 1  # 同一个小时里聊几句只记一次常聊的钟点
    bonds.mark_bye("10001", 2200.0)
    assert bonds._data["users"]["10001"]["bye"] == 2200.0
    assert visible_notes(rec["notes"], True) == ["喜欢原神"]
    assert visible_notes(rec["notes"], False) == ["喜欢原神", "最近在找工作"]
    print("PASS  群聊私聊共用一条记录，私聊听来的只在私聊用")

    bonds.add_user_notes("10001", ["养了只猫", "常熬夜", "会弹吉他"], "g123", now=3000.0)
    assert [n["t"] for n in bonds.user("10001")["notes"]] == ["养了只猫", "常熬夜", "会弹吉他"]
    bonds.add_group_notes("123", ["小明和小红常一起打鸣潮"], now=3001.0)
    bonds.add_group_style("123", ["爱玩谐音梗"], now=3002.0)
    print("PASS  每人最多 DIARY_USER_NOTES 条，满了丢最旧的")

    bonds.save(force=True)
    bonds.load()
    assert bonds.user("10001")["name"] == "明明" and bonds.group("123")["notes"][0]["t"] == "小明和小红常一起打鸣潮"
    assert bonds.group("123")["style"][0]["t"] == "爱玩谐音梗"
    print("PASS  落盘后重新载入不丢")

    assert bonds.user("99999") == {"aff": 0, "fam": 8, "notes": [], "topics": {}} and "99999" not in bonds._data["users"]
    assert bonds.forget_user("10001") and not bonds.forget_user("10001")
    assert bonds.user("10001")["notes"] == [] and bonds.group("123")["notes"]
    assert bonds.clear_group("123") and bonds.group("123")["notes"] == []
    bonds.save(force=True)
    print("PASS  只读不建记录；删除某人 / 清空本群")

    # 初始好感度是「礼貌」的普通档，不是爱答不理的陌生
    from persona_rules import attitude  # noqa: E402

    assert attitude(10, 8) == "普通" and attitude(0, 0) == "陌生"
    before, after = bonds.set_levels("88888", "新人", aff=30)
    assert before["aff"] == 0 and after["aff"] == 30, (before, after)
    before, after = bonds.set_levels("88888", fam=-5)
    assert after["fam"] == 0 and after["aff"] == 30, after
    before, after = bonds.set_levels("88888", aff=999, fam=999)
    assert after["aff"] == 100 and after["fam"] == 100, after
    print("PASS  /好感 手动调数值，越界夹紧，态度档跟着变")

    # 老数据迁移：熟悉 <8 抬到初始值（初始好感现在是 0，好感不用抬），负数好感不动
    old = TMP / "old.json"
    old.write_text(
        '{"users": {"1": {"aff": 0, "fam": 0}, "2": {"aff": -40, "fam": 2}}, "groups": {}}',
        encoding="utf-8",
    )
    bonds.load(old)
    assert bonds.user("1")["aff"] == 0 and bonds.user("1")["fam"] == 8
    assert bonds.user("2")["aff"] == -40 and bonds.user("2")["fam"] == 8
    assert bonds._data.get("floor") == 1
    print("PASS  老数据里刚认识的人抬到礼貌底线，记仇的不动，只迁一次")

    # 私聊里没法 @ 人，/好感 靠昵称找 QQ 号
    bonds.touch("77001", "夜雨轩烛", 0, now=4000.0)
    bonds.touch("77002", "夜雨", 0, now=4001.0)
    assert bonds.find_user("轩烛") == ["77001"]
    assert sorted(bonds.find_user("夜雨")) == ["77001", "77002"]
    assert bonds.find_user("没这个人") == [] and bonds.find_user("  ") == []
    print("PASS  昵称找人：一对一、一对多、查无此人都分得清")

    print("\n结果: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
