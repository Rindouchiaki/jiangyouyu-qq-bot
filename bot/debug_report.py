"""debug 群（devs.DEBUG_GROUP）用的纯逻辑：攒报错、合并重复、限流，读日志文件。不依赖 NoneBot，方便离线测。"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

# 每多少秒发一批、每小时最多发几条、一条最长多少字
BATCH_SEC = 30
HOURLY_MAX = 20
MESSAGE_CHARS = 1500
QUEUE_MAX = 500

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_NUMBERS = re.compile(r"\d+")
LEVEL_NAMES = {"WARNING": "警告", "ERROR": "错误", "CRITICAL": "严重"}
# 日志里算报错的行
_BAD_LINE = re.compile(r"\b(WARNING|ERROR|CRITICAL|Traceback)\b|Exception|Error:")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "")


class Collector:
    """loguru 的 sink 往里塞，后台任务定时取：同一类报错（数字不同也算同一类）只记次数。"""

    def __init__(self, hourly_max: int = HOURLY_MAX) -> None:
        self._lock = threading.Lock()
        self._items: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self._hour = ("", 0)
        self._held = 0
        self.hourly_max = hourly_max

    def add(self, level: str, name: str, message: str, detail: str = "", now: float | None = None) -> None:
        now = time.time() if now is None else now
        text = " ".join(strip_ansi(message).split())[:300]
        key = (level, _NUMBERS.sub("#", f"{name}:{text}"))
        with self._lock:
            item = self._items.get(key)
            if item:
                item["n"] += 1
                item["last"] = now
                return
            if len(self._items) >= QUEUE_MAX:
                self._items.popitem(last=False)
            self._items[key] = {"level": level, "name": name, "text": text, "detail": strip_ansi(detail)[-600:],
                                "n": 1, "first": now, "last": now}

    def drain(self, now: float | None = None) -> list[str]:
        """取出攒着的，拼成要发的几条；这个小时发够了就先压着，下个小时开头说一声压了多少。"""
        now = time.time() if now is None else now
        hour = datetime.fromtimestamp(now).strftime("%Y%m%d%H")
        with self._lock:
            if not self._items:
                return []
            if self._hour[0] != hour:
                self._hour = (hour, 0)
            if self._hour[1] >= self.hourly_max:
                self._held += sum(i["n"] for i in self._items.values())
                self._items.clear()
                return []
            items = list(self._items.values())
            self._items.clear()
            held, self._held = self._held, 0
        lines = []
        if held:
            lines.append(f"（上个小时发太多，压了 {held} 条没发，/日志 错误 看）")
        for it in items:
            when = datetime.fromtimestamp(it["first"]).strftime("%H:%M:%S")
            if it["n"] > 1:
                when += f"~{datetime.fromtimestamp(it['last']).strftime('%H:%M:%S')} ×{it['n']}"
            lines.append(f"[{LEVEL_NAMES.get(it['level'], it['level'])}] {when} {it['name']}：{it['text']}")
            if it["detail"]:
                lines.append(it["detail"])
        out = chunks("\n".join(lines))
        with self._lock:
            self._hour = (hour, self._hour[1] + len(out))
        return out


def chunks(text: str, size: int = MESSAGE_CHARS) -> list[str]:
    """按行切成每段不超过 size 字（单行太长就硬切）。"""
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:size])
            line = line[size:]
        if cur and len(cur) + 1 + len(line) > size:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def tail(path: Path, count: int = 30, keyword: str = "", errors: bool = False, scan_bytes: int = 4_000_000) -> list[str]:
    """日志文件最后几行（只读文件末尾一段）；keyword 只要带这个词的，errors 只要报错的。"""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - scan_bytes))
            raw = f.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    lines = [strip_ansi(line).rstrip() for line in text.splitlines()]
    if size > scan_bytes:
        lines = lines[1:]  # 第一行多半是半截
    lines = [line for line in lines if line]
    if errors:
        lines = [line for line in lines if _BAD_LINE.search(line)]
    if keyword:
        lines = [line for line in lines if keyword in line]
    return lines[-count:]


def parse_log_args(text: str) -> tuple[int, str, bool]:
    """/日志 后面的参数：数字是行数（最多 200），「错误」只看报错，别的当关键词。返回 (行数, 关键词, 只看报错)。"""
    count, keyword, errors = 30, "", False
    for word in (text or "").split():
        if word.isdigit():
            count = max(1, min(200, int(word)))
        elif word in ("错误", "报错", "error", "errors"):
            errors = True
        else:
            keyword = word
    return count, keyword, errors
