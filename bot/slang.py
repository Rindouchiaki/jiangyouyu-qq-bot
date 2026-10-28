"""网络热梗/黑话小词典：句子里真出现了才查，查到才拼进提示词（不额外花 token）。

词表在 bot/knowledge/slang.json，按文件修改时间自动重载——改完不用重启。
自己从聊天里学到的另放 data/slang_learned.json（不进 git），学错了删那一条就行，手写词表优先。
学到的分两种：上网查得到的算大众梗（public），哪个会话都能用；查不到的只算那个群 / 那个人私聊里的梗（scoped），
只在原来的会话里用，绝不带到别的群和私聊。
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
# 大众梗、每个会话的梗各最多留多少条，满了丢最久没更新的
LEARNED_MAX = int(os.getenv("SLANG_LEARNED_MAX", "300"))

_lock = threading.Lock()
_state: dict = {"mtime": 0.0, "entries": []}
_learned: dict = {"loaded": False, "public": {}, "scoped": {}}


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


def lookup(text: str, limit: int | None = None, scope: str = "") -> list[tuple[str, str]]:
    """找出句子里出现的热梗，长的优先，最多 limit 条；scope 是会话（g群号 / p QQ号），只带这个会话自己的梗。"""
    if not text:
        return []
    low = text.lower()
    hits = [(it["t"], it["m"]) for it in load() if it["t"].lower() in low]
    have = {t.lower() for t, _ in hits}
    for term, rec in learned(scope).items():
        if term.lower() in low and term.lower() not in have:
            hits.append((term, rec["m"]))
    hits.sort(key=lambda pair: -len(pair[0]))
    return hits[: limit if limit is not None else HINT_MAX]


def hint(text: str, limit: int | None = None, scope: str = "") -> str:
    """拼成一句给提示词用的话；没命中返回空串，什么都不多花。"""
    hits = lookup(text, limit, scope)
    if not hits:
        return ""
    return "；".join(f"{term}={meaning}" for term, meaning in hits)


def size() -> int:
    return len(load())


def reload() -> int:
    load(force=True)
    return size()


def _valid(d) -> dict:
    return {str(k): v for k, v in d.items() if isinstance(v, dict) and v.get("m")} if isinstance(d, dict) else {}


def _load_learned() -> None:
    if _learned["loaded"]:
        return
    _learned["loaded"] = True
    try:
        data = json.loads(LEARNED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    if "entries" in data and "public" not in data:
        # 旧格式没记是哪个会话学的：查过的算大众梗，猜的不知道出处，丢掉免得串到别的群
        old = _valid(data.get("entries"))
        _learned["public"] = {t: {"m": r["m"], "t": r.get("t", 0)} for t, r in old.items() if r.get("how") == "查"}
        dropped = len(old) - len(_learned["public"])
        if dropped:
            logger.info(f"slang: 旧词表里 {dropped} 个没查证的梗不知道是哪个会话的，丢掉")
        return
    _learned["public"] = _valid(data.get("public"))
    scoped = data.get("scoped")
    _learned["scoped"] = {str(k): _valid(v) for k, v in scoped.items()} if isinstance(scoped, dict) else {}


def learned(scope: str = "") -> dict[str, dict]:
    """这个会话能用的学到的词：大众梗 + 本会话自己的梗（同名时本会话的优先）。"""
    with _lock:
        _load_learned()
        out = dict(_learned["public"])
        if scope:
            out.update(_learned["scoped"].get(scope, {}))
        return out


def known_terms(scope: str = "") -> set[str]:
    return {it["t"] for it in load()} | set(learned(scope))


def _trim(bucket: dict) -> None:
    if len(bucket) > LEARNED_MAX:
        for old in sorted(bucket, key=lambda k: float(bucket[k].get("t") or 0))[: len(bucket) - LEARNED_MAX]:
            bucket.pop(old, None)


def add_learned(term: str, meaning: str, scope: str = "") -> bool:
    """记下一个新学的词。scope 为空 = 网上查实的大众梗（顺手从各会话的私有梗里删掉）；否则只记在这个会话。"""
    term, meaning = term.strip(), meaning.strip()
    if not term or not meaning or term.lower() in {it["t"].lower() for it in load()}:
        return False
    with _lock:
        _load_learned()
        if scope:
            if term in _learned["public"]:
                return False
            bucket = _learned["scoped"].setdefault(scope, {})
        else:
            bucket = _learned["public"]
            for other in _learned["scoped"].values():
                other.pop(term, None)
        bucket[term] = {"m": meaning, "t": time.time()}
        _trim(bucket)
        try:
            LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = LEARNED_FILE.with_suffix(".tmp")
            payload = {"version": 2, "public": _learned["public"], "scoped": _learned["scoped"]}
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(LEARNED_FILE)
        except OSError as exc:
            logger.warning(f"slang: 学到的词保存失败 {type(exc).__name__}")
    return True
