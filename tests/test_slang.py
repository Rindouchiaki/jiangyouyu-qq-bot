"""热梗词典的离线校验：只读 bot/knowledge/slang.json，不联网。"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import slang  # noqa: E402


def main() -> int:
    total = slang.size()
    assert total >= 100, f"词表太小：{total}"
    print(f"PASS  词表载入 {total} 条")

    hits = slang.lookup("这波操作 yyds 了")
    assert hits and hits[0][0] == "yyds", hits
    assert slang.hint("这波操作 yyds 了") == "yyds=永远的神，夸人特别强"
    print("PASS  命中给一句话解释")

    assert slang.lookup("今天天气不错，吃了吗") == []
    assert slang.hint("今天天气不错，吃了吗") == ""
    print("PASS  没命中就什么都不拼，不占 token")

    hits = slang.lookup("我破大防了")
    assert hits[0][0] == "破大防", hits
    print("PASS  长词优先（破大防 > 破防）")

    hits = slang.lookup("破防 yyds 绝绝子 栓Q", limit=2)
    assert len(hits) == 2 and {h[0] for h in hits} == {"yyds", "绝绝子"}, hits
    print("PASS  limit 生效，按长度排序")

    assert set(slang.load()[0].keys()) == {"t", "m"}
    print("PASS  每条只有 term / meaning 两个字段")

    # 学到的梗分会话：查不到的只在原来的群 / 私聊里认
    tmp = Path(tempfile.mkdtemp()) / "slang_learned.json"
    slang.LEARNED_FILE = tmp
    slang._learned.update(loaded=False, public={}, scoped={})
    assert slang.add_learned("鱼鱼塞", "本群叫酱油鱼的外号", "g1")
    assert slang.hint("鱼鱼塞今天又来了", scope="g1") == "鱼鱼塞=本群叫酱油鱼的外号"
    assert slang.hint("鱼鱼塞今天又来了", scope="g2") == ""
    assert slang.hint("鱼鱼塞今天又来了", scope="p123") == "" and slang.hint("鱼鱼塞今天又来了") == ""
    assert "鱼鱼塞" in slang.known_terms("g1") and "鱼鱼塞" not in slang.known_terms("g2")
    print("PASS  查不到的梗只在原来的群里认，别的群和私聊都不带")

    assert slang.add_learned("哈基米", "猫的昵称")
    assert slang.hint("哈基米好可爱", scope="g2") == "哈基米=猫的昵称" and slang.hint("哈基米好可爱") == "哈基米=猫的昵称"
    assert not slang.add_learned("哈基米", "别的意思", "g3")
    assert slang.add_learned("鱼鱼塞", "网上查到的意思")
    assert slang.learned("g1")["鱼鱼塞"]["m"] == "网上查到的意思"
    assert "鱼鱼塞" not in json.loads(tmp.read_text(encoding="utf-8"))["scoped"].get("g1", {})
    assert not slang.add_learned("yyds", "手写词表里有的不记")
    print("PASS  网上查得到的算大众梗，哪里都认；原来的私有梗升格后删掉")

    tmp.write_text(json.dumps({"entries": {"甲": {"m": "查过的", "how": "查"}, "乙": {"m": "猜的", "how": "猜"}}}), encoding="utf-8")
    slang._learned.update(loaded=False, public={}, scoped={})
    assert slang.hint("甲乙", scope="g1") == "甲=查过的"
    print("PASS  旧词表：查过的留成大众梗，猜的不知道出处就丢掉")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
