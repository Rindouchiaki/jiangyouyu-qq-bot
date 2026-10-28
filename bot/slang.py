"""网络热梗/黑话小词典：句子里真出现了才查，查到才拼进提示词（不额外花 token）。

词表在 bot/knowledge/slang.json，按文件修改时间自动重载——改完不用重启。
自己从聊天里学到的另放 data/slang_learned.json（不进 git），学错了删那一条就行，手写词表优先。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from nonebot.log import logger

DEFAULT_FILE = Path(__file__).resolve().parent / "knowledge" / "slang.json"
SLANG_FILE = Path(os.getenv("SLANG_FILE") or DEFAULT_FILE)
HINT_MAX = int(os.getenv("SLANG_HINT_MAX", "3"))
_data_env = os.getenv("PERSONA_DATA_DIR", "").strip()
LEARNED_FILE = (Path(_data_env) if _data_env else Path(__file__).resolve().parent / "data") / "slang_learned.json"
# 学到的词最多留多少条，满了丢最久没见到的
LEARNED_MAX = int(os.getenv("SLANG_LEARNED_MAX", "300"))

_lock = threading.Lock()
_state: dict = {"mtime": 0.0, "entries": []}
_learned: dict = {"loaded": False, "entries": {}}


def load(force: bool = False) -> list[dict]:
    """读词表；文件没变就用缓存（一次磁盘 stat，比 parse 便宜）。"""
    with _lock:
        try:
            mtime = SLANG_FILE.stat().st_mtime
        except OSError:
            if force:
                logger.warning(f"slang: 没找到词表 {SLANG_FILE}")
            return _state["entries"]
        if not force and mtime == _state["mtime"]:
            return _state["entries"]
        try:
            data = json.loads(SLANG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"slang: 词表解析失败 {type(exc).__name__}")
            return _state["entries"]
        entries = [
            {"t": str(it.get("t", "")).strip(), "m": str(it.get("m", "")).strip()}
            for it in data.get("entries", [])
        ]
        _state["entries"] = [it for it in entries if it["t"] and it["m"]]
        _state["mtime"] = mtime
        logger.debug(f"slang: 载入 {len(_state['entries'])} 条，更新 {data.get('updated', '?')}")
        return _state["entries"]


def lookup(text: str, limit: int | None = None) -> list[tuple[str, str]]:
    """找出句子里出现的热梗，长的优先，最多 limit 条。"""
    if not text:
        return []
    low = text.lower()
    hits = [(it["t"], it["m"]) for it in load() if it["t"].lower() in low]
    have = {t.lower() for t, _ in hits}
    for term, rec in learned().items():
        if term.lower() in low and term.lower() not in have:
            hits.append((term, rec["m"]))
    hits.sort(key=lambda pair: -len(pair[0]))
    return hits[: limit if limit is not None else HINT_MAX]


def hint(text: str, limit: int | None = None) -> str:
    """拼成一句给提示词用的话；没命中返回空串，什么都不多花。"""
    hits = lookup(text, limit)
    if not hits:
        return ""
    return "；".join(f"{term}={meaning}" for term, meaning in hits)


def size() -> int:
    return len(load())


def reload() -> int:
    load(force=True)
    return size()


def learned() -> dict[str, dict]:
    """学到的词：{词: {"m": 意思, "how": 猜/查, "t": 最近一次见到}}。"""
    with _lock:
        if not _learned["loaded"]:
            _learned["loaded"] = True
            try:
                data = json.loads(LEARNED_FILE.read_text(encoding="utf-8"))
                entries = data.get("entries") if isinstance(data, dict) else None
                if isinstance(entries, dict):
                    _learned["entries"] = {
                        str(k): v for k, v in entries.items() if isinstance(v, dict) and v.get("m")
                    }
            except (OSError, ValueError):
                pass
        return _learned["entries"]


def known_terms() -> set[str]:
    return {it["t"] for it in load()} | set(learned())


def add_learned(term: str, meaning: str, how: str) -> bool:
    """记下一个新学的词；手写词表里已经有的不记。"""
    term, meaning = term.strip(), meaning.strip()
    if not term or not meaning or term.lower() in {t.lower() for t in (it["t"] for it in load())}:
        return False
    entries = learned()
    with _lock:
        entries[term] = {"m": meaning, "how": how, "t": time.time()}
        if len(entries) > LEARNED_MAX:
            for old in sorted(entries, key=lambda k: float(entries[k].get("t") or 0))[: len(entries) - LEARNED_MAX]:
                entries.pop(old, None)
        try:
            LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = LEARNED_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(LEARNED_FILE)
        except OSError as exc:
            logger.warning(f"slang: 学到的词保存失败 {type(exc).__name__}")
    return True
