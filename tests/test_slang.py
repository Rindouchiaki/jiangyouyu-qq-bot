"""热梗词典的离线校验：只读 bot/knowledge/slang.json，不联网。"""

import sys
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
