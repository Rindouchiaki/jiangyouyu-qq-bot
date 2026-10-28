"""话题词表：从一句话里认出在聊哪类事，用来给好感高的人做「越聊越对味」。

词表在 bot/knowledge/topics.json，按文件修改时间自动重载；没命中的话什么都不做。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from nonebot.log import logger

DEFAULT_FILE = Path(__file__).resolve().parent / "knowledge" / "topics.json"
TOPICS_FILE = Path(os.getenv("TOPICS_FILE") or DEFAULT_FILE)

_lock = threading.Lock()
_state: dict = {"mtime": 0.0, "lexicon": []}


def load(force: bool = False) -> list[tuple[str, tuple[str, ...]]]:
    """读词表，返回 [(话题, (别名...))]；文件没变就用缓存。"""
    with _lock:
        try:
            mtime = TOPICS_FILE.stat().st_mtime
        except OSError:
            if force:
                logger.warning(f"topics: 没找到词表 {TOPICS_FILE}")
            return _state["lexicon"]
        if not force and mtime == _state["mtime"]:
            return _state["lexicon"]
        try:
            data = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"topics: 词表解析失败 {type(exc).__name__}")
            return _state["lexicon"]
        lexicon = [
            (str(topic), tuple(str(a).lower() for a in aliases if str(a).strip()))
            for topic, aliases in (data.get("topics") or {}).items()
        ]
        _state["lexicon"] = [(t, a) for t, a in lexicon if a]
        _state["mtime"] = mtime
        logger.debug(f"topics: 载入 {len(_state['lexicon'])} 类，更新 {data.get('updated', '?')}")
        return _state["lexicon"]


def detect(text: str) -> list[str]:
    """这句话在聊哪几类话题（最多 3 类）。"""
    if not text:
        return []
    low = text.lower()
    hits = [topic for topic, aliases in load() if any(a in low for a in aliases)]
    return hits[:3]


def size() -> int:
    return len(load())


def reload() -> int:
    load(force=True)
    return size()
