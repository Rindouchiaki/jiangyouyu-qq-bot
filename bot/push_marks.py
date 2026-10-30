"""刚推送出去过的链接，短时间内不再当「用户贴的链接」去解析。

B 站推送（bili_push）发出去的每条消息里都带原动态/视频链接，SnowLuma 有可能把这条消息
再当成事件推回来；万一账号守卫没拦住（比如以后接了别的发送通道），链接就会被解析插件
再抓一遍，转发记录里又带链接，一层层套下去。这里记一个短命的「刚推过」名单，
机器人侧在事件入口查一下，命中就直接忽略。
"""

from __future__ import annotations

import os
import re
import threading
import time

# 多久之内算「刚推过」。默认 15 分钟，够覆盖一轮轮询加转发延迟；0 就是不记。
TTL_SECONDS = float(os.getenv("PUSH_LINK_TTL", "15"))

_URL_RE = re.compile(r"https?://[^\s\"'<>，。！？、）)】]+", re.IGNORECASE)

_lock = threading.Lock()
_marks: dict[str, float] = {}


def _urls(text: str) -> list[str]:
    """把文本里的链接抠出来，去掉结尾的标点。"""
    found = []
    for raw in _URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:!?)]}，。！？、）】")
        if url:
            found.append(url)
    return found


def mark_text(text: str, now: float | None = None) -> int:
    """记下这段文本里的链接，返回记了几条。"""
    ts = time.time() if now is None else now
    urls = _urls(text)
    if not urls or TTL_SECONDS <= 0:
        return 0
    with _lock:
        for url in urls:
            _marks[url] = ts
    return len(urls)


def contains_recent(text: str, now: float | None = None) -> bool:
    """这段文本里有没有刚推送过的链接。"""
    ts = time.time() if now is None else now
    urls = _urls(text)
    if not urls:
        return False
    with _lock:
        expired = [u for u, t in _marks.items() if ts - t > TTL_SECONDS]
        for url in expired:
            _marks.pop(url, None)
        return any(url in _marks for url in urls)


def clear() -> None:
    """清空（测试用）。"""
    with _lock:
        _marks.clear()


def size() -> int:
    with _lock:
        return len(_marks)
