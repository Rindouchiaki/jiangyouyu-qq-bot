"""话题自学习的离线校验：词表识别 + bonds 里的权重与衰减。"""

import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="topics_"))
os.environ["PERSONA_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import bonds  # noqa: E402
import topics  # noqa: E402

DAY = 86400.0


def main() -> int:
    assert topics.size() >= 10
    assert topics.detect("原神抽卡又歪了，深渊打不过") == ["游戏"]
    assert topics.detect("今天加班到十点才下班") == ["工作"]
    assert topics.detect("随便聊聊吧") == []
    print("PASS  词表识别话题，认不出就什么都不记")

    now = 10_000_000.0
    assert bonds.learn_topics("20001", "夜雨轩烛", ["游戏", "数码"], now=now) == ["游戏", "数码"]
    bonds.learn_topics("20001", "", ["游戏"], now=now + 1)
    bonds.learn_topics("20001", "", ["游戏"], now=now + 2)
    assert bonds.top_topics("20001", now=now + 3)[0] == "游戏"
    print("PASS  聊得多的话题排前面")

    # 两周减半：30 天后游戏只剩 3 * 0.5^(30/14) ≈ 0.68，低于门槛，不再拿出来顺话题
    assert bonds.top_topics("20001", now=now + 30 * DAY) == []
    print("PASS  两周减半，久不提的话题自己退场")

    bonds.save(force=True)
    bonds.load()
    rec = bonds.user("20001")
    assert rec["topics"]["游戏"]["w"] == 3
    print("PASS  落盘后权重还在")

    # 新人没有话题记录：返回空，不额外拼提示词
    assert bonds.top_topics("99999") == []
    print("PASS  没聊过的人不拼话题")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
