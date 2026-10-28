r"""一次性迁移：给 fork#1（记忆按会话隔离）之前写进白守的旧日记补上会话标签，让自动回忆能按会话选中它们。

旧格式（fork#1 之前）→ 新格式：
- 群聊 `- HH:MM 群123 名字：…`              → `- HH:MM [群123] 名字：…`
  紧跟的回复 `- HH:MM 我：…`                → `- HH:MM [群123] 我：…`
  旧代码没压成一行，正文换行留下的续行并回这一条
- 私聊 `- HH:MM [私聊] …` 分不出是谁，默认不动；`--private-as QQ号` 可以全部归给一个人
- `/记` 的署名是当时发言人的群名片（那时人人能用），`--dev-alias 名片1,名片2` 把开发者自己的改成 --dev-name（默认酱酱鱼）
- 旧代码按文件名找「今天」的日记，会把机器人的话写进库里任何文件名带日期的笔记；
  新代码只读 Journals，`--include-outside` 把这些行挪进 Journals 同一天的日记

默认只打印会改什么；加 --apply 才写盘，写之前把要动的文件原样备份到库旁边的
「<库名>.迁移备份-时间」目录。已经是新格式的行不动，可以重复跑。

用法（仓库根目录）：
    .venv\Scripts\python tools\migrate_journal_tags.py
    .venv\Scripts\python tools\migrate_journal_tags.py --apply
库路径、日记子目录从 bot\persona.env 读，可用 --vault 覆盖。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATE_RE = re.compile(r"(\d{4})[-_.年](\d{1,2})[-_.月](\d{1,2})")
ITEM_RE = re.compile(r"^(?P<head>[-*] \d{1,2}:\d{2} )(?P<body>.*)$")
OLD_GROUP_RE = re.compile(r"^群(?P<gid>\d+) (?P<rest>.+)$")
TAG_RE = re.compile(r"^\[(?P<tag>[^\]]+)\] (?P<rest>.*)$")
OLD_PRIVATE_RE = re.compile(r"^\[私聊\] (对方|我)：")


@dataclass
class Stats:
    group: int = 0
    reply: int = 0
    merged: int = 0
    private: int = 0
    private_left: int = 0
    dev: int = 0
    other_tags: dict[str, int] = field(default_factory=dict)

    def changed(self) -> int:
        return self.group + self.reply + self.merged + self.private + self.dev

    def add(self, other: "Stats") -> None:
        for name in ("group", "reply", "merged", "private", "private_left", "dev"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for tag, n in other.other_tags.items():
            self.other_tags[tag] = self.other_tags.get(tag, 0) + n


def _split_eol(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body):]


def _is_continuation(text: str) -> bool:
    """旧条目正文换行留下的续行：非空、不是新的列表项/标题/分隔线。"""
    t = text.strip()
    return bool(t) and not t.startswith(("- ", "* ", "#", "---"))


def migrate_lines(
    lines: list[str],
    private_as: str = "",
    dev_aliases: tuple[str, ...] = (),
    dev_name: str = "",
) -> tuple[list[str], Stats]:
    """逐行补标签；lines 带行尾，返回的也带，行尾风格保持原样。"""
    out: list[str] = []
    stats = Stats()
    last_group = ""   # 上一条是旧群聊行时的群号，紧跟的「我：」归到这个群
    merging = False   # 正在把旧条目的续行并回上一行
    for line in lines:
        text, eol = _split_eol(line)
        m = ITEM_RE.match(text.strip())
        if m is None:
            if merging and _is_continuation(text):
                prev, prev_eol = _split_eol(out[-1])
                out[-1] = f"{prev} {' '.join(text.split())}{prev_eol}"
                stats.merged += 1
                continue
            merging = False
            out.append(line)
            continue

        head, body = m.group("head"), m.group("body")
        indent = text[: len(text) - len(text.lstrip())]
        group, tagged = OLD_GROUP_RE.match(body), TAG_RE.match(body)
        merging = False
        if group:
            body = f"[群{group.group('gid')}] {group.group('rest')}"
            last_group, merging = group.group("gid"), True
            stats.group += 1
        elif body.startswith("我：") and last_group:
            body = f"[群{last_group}] {body}"
            last_group, merging = "", True
            stats.reply += 1
        else:
            last_group = ""
            if tagged and tagged.group("tag") == "私聊":
                merging = True
                if private_as:
                    body = f"[私聊{private_as}] {tagged.group('rest')}"
                    stats.private += 1
                else:
                    stats.private_left += 1
            elif tagged and tagged.group("tag") in dev_aliases and dev_name:
                body = f"[{dev_name}] {tagged.group('rest')}"
                stats.dev += 1
            elif tagged and not tagged.group("tag").startswith(("群", "私聊")) and tagged.group("tag") != dev_name:
                tag = tagged.group("tag")
                stats.other_tags[tag] = stats.other_tags.get(tag, 0) + 1
        out.append(f"{indent}{head}{body}{eol}")
    return out, stats


def pick_outside(lines: list[str]) -> tuple[list[str], list[str]]:
    """库里非日记文件中机器人写的旧行（群聊 + 紧跟的回复、私聊）及其续行，拆成 (留下, 挪走)。"""
    keep: list[str] = []
    move: list[str] = []
    taking = False
    after_group = False
    for line in lines:
        text, _ = _split_eol(line)
        m = ITEM_RE.match(text.strip())
        if m is None:
            if taking and _is_continuation(text):
                move.append(line)
                continue
            taking = False
            keep.append(line)
            continue
        body = m.group("body")
        is_group = bool(OLD_GROUP_RE.match(body))
        taking = is_group or OLD_PRIVATE_RE.match(body) is not None or (after_group and body.startswith("我："))
        after_group = is_group
        (move if taking else keep).append(line)
    return keep, move


def _read(path: Path) -> tuple[list[str], bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig" if bom else "utf-8")
    return text.splitlines(keepends=True), bom


def _write(path: Path, lines: list[str], bom: bool) -> None:
    tmp = path.with_name(path.name + ".migrating")
    tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + "".join(lines).encode("utf-8"))
    tmp.replace(path)


def _date_of(path: Path, text: str) -> str:
    m = DATE_RE.search(path.name) or DATE_RE.search(text[:200])
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def _journal_for(diary: Path, date: str) -> Path:
    """Journals 里文件名带这一天的日记，和 memory._today_file 的找法一致。"""
    for path in sorted(diary.rglob("*.md")):
        if date in path.name:
            return path
    return diary / f"{date}.md"


def _env(name: str, default: str) -> str:
    try:
        from dotenv import dotenv_values

        values = dotenv_values(ROOT / "bot" / "persona.env")
    except Exception:  # noqa: BLE001
        values = {}
    return (os.getenv(name) or values.get(name) or default).strip()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="给旧日记补会话标签（默认只预览）")
    ap.add_argument("--vault", default=_env("BAISHOU_VAULT", str(Path.home() / "Documents" / "BaiShou")))
    ap.add_argument("--diary-dir", default=_env("BAISHOU_DIARY_DIR", "Journals"))
    ap.add_argument("--dev-name", default="酱酱鱼")
    ap.add_argument("--private-as", default="", help="旧 [私聊] 全部归给这个 QQ 号（只和一个人私聊过时用）")
    ap.add_argument("--dev-alias", default="", help="旧 /记 署名里哪些名字是开发者自己，英文逗号分隔")
    ap.add_argument("--include-outside", action="store_true", help="把日记目录外的机器人旧行挪进日记")
    ap.add_argument("--apply", action="store_true", help="真的写盘（先备份）")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser()
    diary = vault / args.diary_dir
    if not diary.is_dir():
        print(f"找不到日记目录：{diary}（用 --vault 指到白守的库）")
        return 1
    if args.private_as and not args.private_as.isdigit():
        print("--private-as 要填 QQ 号")
        return 1
    aliases = tuple(a.strip() for a in args.dev_alias.split(",") if a.strip())

    backup = vault.parent / f"{vault.name}.迁移备份-{datetime.now():%Y%m%d-%H%M%S}"
    plans: dict[Path, tuple[list[str], bool]] = {}   # 要写的文件 -> (新内容, BOM)
    total = Stats()
    outside_files: list[tuple[Path, int]] = []

    def load(path: Path) -> tuple[list[str], bool]:
        if path in plans:
            return plans[path]
        if path.is_file():
            return _read(path)
        return [f"---\ndate: {path.stem}\ntags: []\n---\n\n# {path.stem}\n\n"], False

    # 1) 日记目录外：先把机器人的旧行挪进对应日期的日记，再统一补标签
    for path in sorted(vault.rglob("*.md")):
        if diary in path.parents or backup in path.parents or not path.is_file():
            continue
        lines, bom = _read(path)
        keep, move = pick_outside(lines)
        if not move:
            continue
        outside_files.append((path, len(move)))
        if not args.include_outside:
            continue
        target = _journal_for(diary, _date_of(path, "".join(lines)))
        tlines, tbom = load(target)
        if tlines and not tlines[-1].endswith(("\n", "\r")):
            tlines = tlines[:-1] + [tlines[-1] + "\n"]
        plans[path] = (keep, bom)
        plans[target] = (tlines + move, tbom)

    # 2) 日记目录里补标签
    paths = {p for p in diary.rglob("*.md") if p.is_file()} | {p for p in plans if diary in p.parents}
    for path in sorted(paths):
        lines, bom = load(path)
        new, stats = migrate_lines(lines, args.private_as, aliases, args.dev_name)
        total.add(stats)
        if new != lines or path in plans:
            plans[path] = (new, bom)
            if stats.changed():
                print(f"  {path.relative_to(vault)}：群聊 {stats.group} / 回复 {stats.reply} / 续行 {stats.merged}"
                      f" / 私聊 {stats.private} / 开发者 {stats.dev}")

    print()
    print(f"日记目录：{diary}")
    print(f"群聊补标签 {total.group} 条，紧跟的回复 {total.reply} 条，续行并回 {total.merged} 行")
    if args.private_as:
        print(f"私聊归给 {args.private_as}：{total.private} 条")
    elif total.private_left:
        print(f"旧私聊 {total.private_left} 条分不出是谁，没动（只和一个人私聊过可以加 --private-as QQ号）")
    if aliases:
        print(f"/记 署名改成 {args.dev_name}：{total.dev} 条")
    if total.other_tags:
        names = "、".join(f"{t}（{n}）" for t, n in sorted(total.other_tags.items(), key=lambda kv: -kv[1])[:10])
        print(f"其它署名（旧 /记，人人可用时写的）：{names}；开发者自己的可以用 --dev-alias 改成 {args.dev_name}")
    if outside_files:
        verb = "挪进日记" if args.include_outside else "没动（加 --include-outside 挪进日记）"
        print(f"日记目录外有机器人写的旧行，{verb}：")
        for path, n in outside_files:
            print(f"  {path.relative_to(vault)}：{n} 行")

    if not plans:
        print("\n没有要改的。")
        return 0
    if not args.apply:
        print(f"\n以上是预览，要动 {len(plans)} 个文件。确认后加 --apply 执行（会先备份）。")
        return 0

    for path, (lines, bom) in plans.items():
        if path.is_file():
            dest = backup / path.relative_to(vault)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, lines, bom)
    print(f"\n已改 {len(plans)} 个文件，原文件备份在：{backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
