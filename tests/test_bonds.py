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
    bonds.touch("10001", "小明", 2, now=1000.0)
    bonds.add_user_notes("10001", ["喜欢原神"], "g123", now=1001.0)
    bonds.touch("10001", "明明", 0, now=2000.0)
    bonds.add_user_notes("10001", ["最近在找工作"], "p", now=2001.0)
    rec = bonds.user("10001")
    assert rec["name"] == "明明" and rec["fam"] == 2 and len(rec["notes"]) == 2, rec
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

    assert bonds.user("99999") == {"aff": 0, "fam": 0, "notes": []} and "99999" not in bonds._data["users"]
    assert bonds.forget_user("10001") and not bonds.forget_user("10001")
    assert bonds.user("10001")["notes"] == [] and bonds.group("123")["notes"]
    assert bonds.clear_group("123") and bonds.group("123")["notes"] == []
    bonds.save(force=True)
    print("PASS  只读不建记录；删除某人 / 清空本群")

    print("\n结果: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
