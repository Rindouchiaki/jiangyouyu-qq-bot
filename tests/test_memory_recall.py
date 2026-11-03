"""白守记忆召回（memory.recall）的离线测试：不用真库，造一个临时库。"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

VAULT = tempfile.mkdtemp(prefix="baishou-test-")
JOURNALS = Path(VAULT) / "Journals"
JOURNALS.mkdir(parents=True)
os.environ["BAISHOU_VAULT"] = VAULT

import memory  # noqa: E402


def _write(day: str, lines: list[str]) -> None:
    body = f"---\ndate: {day}\ntags: []\n---\n\n# {day}\n\n" + "\n".join(lines) + "\n"
    (JOURNALS / f"{day}.md").write_text(body, encoding="utf-8")


def main() -> None:
    today = memory.datetime.now().strftime("%Y-%m-%d")
    _write(
        "2026-01-01",
        [
            "- 15:07 [群111] 小明：我家猫叫橙子，三岁了",
            "- 15:08 [群111] 我：橙子挺能吃的吧",
            "- 15:09 [群222] 小红：我在玩影之诗",
        ],
    )
    _write(today, ["- 09:00 [群111] 小明：今天好热", "- 09:01 [群111] 我：热就开空调"])

    # 问到旧事：能翻到 1 月那天，而且排在前面
    hits = memory.recall("你还记得橙子几岁了吗", ("群111",), 3)
    assert hits, hits
    assert "橙子" in hits[0] and "2026-01-01" in hits[0], hits

    # 自己说过的话不算事实
    assert all("我：" not in h for h in hits), hits

    # 会话隔离：别的群那条不能出现
    assert all("影之诗" not in h for h in hits), hits

    # 问别的事、关键词对不上：退回最近几条也有内容，不会空
    other = memory.recall("你还记得奥特曼吗", ("群111",), 2)
    assert other and all("群111" in h for h in other), other

    # 没有标签就别把私聊/别的会话带出来
    tagged = memory.recall("橙子", ("群222",), 3)
    assert all("橙子" not in h for h in tagged), tagged

    print("test_memory_recall: 全部通过", VAULT)


if __name__ == "__main__":
    main()
