r"""白守（BaiShou）本地记忆桥：直接读写它的 Markdown 日记库。

白守以本地 Markdown 为唯一事实来源，所以不需要 App 运行也能用：
- search(): 关键词检索历史日记
- recent(): 最近记的几条
- remember(): 往今天的日记里追加一条

库路径由 BAISHOU_VAULT 指定（默认 文档\BaiShou）。
只读写库里的 DIARY_SUBDIR 子目录：库的其它部分是主人的私人笔记，不能被群聊翻出来。
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

from nonebot.log import logger

VAULT = Path(os.getenv("BAISHOU_VAULT", str(Path.home() / "Documents" / "BaiShou")))
DIARY_SUBDIR = os.getenv("BAISHOU_DIARY_DIR", "Journals")
DATE_RE = re.compile(r"(\d{4})[-_.年](\d{1,2})[-_.月](\d{1,2})")


def available() -> bool:
    return VAULT.is_dir()


def _diary_root() -> Path:
    return VAULT / DIARY_SUBDIR


def _iter_md():
    root = _diary_root()
    if not root.is_dir():
        return
    for path in root.rglob("*.md"):
        if path.is_file():
            yield path


def _date_of(path: Path, text: str) -> str:
    m = DATE_RE.search(path.name) or DATE_RE.search(text[:200])
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def _today_file() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    for path in _iter_md():
        if today in path.name:
            return path
    target = _diary_root() / f"{today}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(
            f"---\ndate: {today}\ntags: []\n---\n\n# {today}\n\n",
            encoding="utf-8",
        )
    return target


def remember(text: str, who: str = "") -> Path:
    path = _today_file()
    stamp = datetime.now().strftime("%H:%M")
    with path.open("a", encoding="utf-8") as f:
        prefix = f"[{who}] " if who else ""
        # 压成一行：换行会被当成新的列表项，可以伪造别的会话标签
        f.write(f"- {stamp} {prefix}{' '.join(text.split())}\n")
    logger.info(f"memory: 记到 {path.name}: {text[:30]}")
    return path


def _has_tag(line: str, marks: tuple[str, ...]) -> bool:
    """列表项「- HH:MM [tag] ...」是否带其中某个标签。"""
    line = line.strip()
    return line.startswith(("- ", "* ")) and line[2:].strip().split(" ", 1)[-1].startswith(marks)


def recent(limit: int = 5, tags: tuple[str, ...] = ()) -> list[str]:
    """最近几条记录（按文件日期倒序，取每篇末尾的列表项）。

    tags 非空时只要带 [tag] 前缀的条目，防止 A 群/私聊的内容被 B 群带出来。
    """
    marks = tuple(f"[{t}] " for t in tags if t)
    items: list[tuple[str, int, str]] = []
    for path in _iter_md():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        date = _date_of(path, text)
        for idx, line in enumerate(text.splitlines()):
            line = line.strip()
            if line.startswith(("- ", "* ")) and len(line) > 4:
                if marks and not _has_tag(line, marks):
                    continue
                items.append((date, idx, line[2:].strip()))
    # 同一天里按行号倒序，取到的是当天最新的几条
    items.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [f"{d} {t}" for d, _, t in items[:limit]]


def search(keyword: str, limit: int = 3, tags: tuple[str, ...] = ()) -> list[str]:
    """关键词检索，返回带日期的片段；tags 含义同 recent()。"""
    kw = keyword.strip()
    if not kw:
        return []
    marks = tuple(f"[{t}] " for t in tags if t)
    hits: list[tuple[int, str, str]] = []
    for path in _iter_md():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if kw not in text:
            continue
        date = _date_of(path, text)
        snippet = ""
        count = 0
        for line in text.splitlines():
            if kw not in line or line.strip() in ("---",):
                continue
            if marks and not _has_tag(line, marks):
                continue
            count += line.count(kw)
            if not snippet:
                snippet = line.strip()[:120]
        if count:
            hits.append((count, date, snippet))
    hits.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [f"{d}：{s}" for _, d, s in hits[:limit]]


def stats() -> dict:
    files = list(_iter_md())
    return {
        "vault": str(_diary_root()),
        "files": len(files),
        "exists": VAULT.is_dir(),
        "today": datetime.now().strftime("%Y-%m-%d"),
    }



