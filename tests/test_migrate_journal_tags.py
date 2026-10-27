"""tools/migrate_journal_tags.py 的离线校验：在临时目录里造一个旧格式的白守库跑一遍。"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from migrate_journal_tags import migrate_lines, pick_outside  # noqa: E402

OLD = (
    "---\r\ndate: 2026-05-01\r\ntags: []\r\n---\r\n\r\n# 2026-05-01\r\n\r\n"
    "- 10:00 群123 路人甲：在吗\r\n"
    "第二行\r\n"
    "- 10:00 我：在\r\n"
    "- 10:05 [私聊] 对方：你好\r\n"
    "- 10:05 [私聊] 我：嗯\r\n"
    "- 10:06 [酱酱鱼本鱼] 明天考试\r\n"
    "- 10:07 [群456] 路人乙：新格式不动\r\n"
    "- 10:08 我：前面不是旧群聊行，不归群\r\n"
)


def main() -> int:
    lines = OLD.splitlines(keepends=True)
    new, stats = migrate_lines(lines)
    text = "".join(new)
    assert "- 10:00 [群123] 路人甲：在吗 第二行\r\n" in text
    assert "- 10:00 [群123] 我：在\r\n" in text
    assert "- 10:05 [私聊] 对方：你好\r\n" in text and stats.private_left == 2
    assert "- 10:08 我：前面不是旧群聊行，不归群\r\n" in text
    assert (stats.group, stats.reply, stats.merged) == (1, 1, 1)
    assert stats.other_tags == {"酱酱鱼本鱼": 1}
    print("PASS  migrate_lines：群聊和紧跟的回复补标签，续行并回，私聊默认不动")

    again, stats2 = migrate_lines(new)
    assert again == new and stats2.changed() == 0
    print("PASS  migrate_lines：已迁移的再跑一遍不变")

    new, stats = migrate_lines(lines, private_as="10002", dev_aliases=("酱酱鱼本鱼",), dev_name="酱酱鱼")
    text = "".join(new)
    assert "- 10:05 [私聊10002] 对方：你好\r\n" in text and "- 10:06 [酱酱鱼] 明天考试\r\n" in text
    print("PASS  migrate_lines：--private-as / --dev-alias")

    note = ["# 2026-05-02 会议\n", "- 记得带电脑\n", "- 09:00 群123 路人甲：早\n", "续行\n",
            "- 09:00 我：早\n", "- 09:30 自己的待办\n"]
    keep, move = pick_outside(note)
    assert keep == ["# 2026-05-02 会议\n", "- 记得带电脑\n", "- 09:30 自己的待办\n"]
    assert move == note[2:5]
    print("PASS  pick_outside：只挑机器人写的旧行")

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "BaiShou"
        (vault / "Journals").mkdir(parents=True)
        (vault / "Journals" / "2026-05-01.md").write_bytes(OLD.encode("utf-8"))
        (vault / "笔记").mkdir()
        (vault / "笔记" / "2026-05-02 会议.md").write_text("".join(note), encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        cmd = [sys.executable, str(ROOT / "tools" / "migrate_journal_tags.py"), "--vault", str(vault)]

        out = subprocess.run(cmd, capture_output=True, env=env, check=True).stdout.decode("utf-8")
        assert "预览" in out and "笔记" in out
        assert (vault / "Journals" / "2026-05-01.md").read_bytes() == OLD.encode("utf-8")

        subprocess.run(cmd + ["--apply", "--include-outside"], capture_output=True, env=env, check=True)
        journal = (vault / "Journals" / "2026-05-01.md").read_bytes().decode("utf-8")
        assert "- 10:00 [群123] 我：在\r\n" in journal
        moved = (vault / "Journals" / "2026-05-02.md").read_text(encoding="utf-8")
        assert "- 09:00 [群123] 路人甲：早 续行\n" in moved and "- 09:00 [群123] 我：早\n" in moved
        left = (vault / "笔记" / "2026-05-02 会议.md").read_text(encoding="utf-8")
        assert "群123" not in left and "自己的待办" in left
        backups = list(Path(tmp).glob("BaiShou.迁移备份-*"))
        assert len(backups) == 1 and (backups[0] / "Journals" / "2026-05-01.md").read_bytes() == OLD.encode("utf-8")

        out = subprocess.run(cmd + ["--apply", "--include-outside"], capture_output=True, env=env, check=True)
        assert "没有要改的" in out.stdout.decode("utf-8")

        os.environ["BAISHOU_VAULT"] = str(vault)
        sys.path.insert(0, str(ROOT / "bot"))
        import memory

        got = memory.recent(5, ("群123",))
        assert got and all("[群123]" in g for g in got) and len(got) == 4
    print("PASS  脚本：先预览不写盘，--apply 备份后改写，挪出的行能被 memory.recent 按会话选中，重复跑无变化")

    print("\n结果: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
