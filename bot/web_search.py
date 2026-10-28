"""联网：DeepSeek 官方 Search & Fetch（和对话共用一个 key），带缓存和限额。

- 搜索 POST {SEARCH_BASE_URL}/v1/tools/search，看网页 POST /v1/tools/fetch，各 0.75 美元 / 千次成功调用；
- 同一个查询 SEARCH_CACHE_SEC 秒内直接用缓存；
- 全局每天 SEARCH_DAILY_MAX 次、每人每小时 SEARCH_PER_USER_HOUR 次，超了就当没查到（计数按天落盘，重启不清零）。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from nonebot.log import logger

PROVIDER = os.getenv("SEARCH_PROVIDER", "deepseek").strip().lower()
BASE_URL = os.getenv("SEARCH_BASE_URL", "https://api.deepseek.com").rstrip("/")
API_KEY = os.getenv("SEARCH_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()
COUNT = int(os.getenv("SEARCH_COUNT", "5"))
DAILY_MAX = int(os.getenv("SEARCH_DAILY_MAX", "100"))
PER_USER_HOUR = int(os.getenv("SEARCH_PER_USER_HOUR", "6"))
CACHE_SEC = float(os.getenv("SEARCH_CACHE_SEC", "600"))
TIMEOUT = float(os.getenv("SEARCH_TIMEOUT", "15"))

_data_env = os.getenv("PERSONA_DATA_DIR", "").strip()
COUNT_FILE = (Path(_data_env) if _data_env else Path(__file__).resolve().parent / "data") / "search_count.json"

_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, object]] = {}
_per_user: dict[str, deque] = defaultdict(lambda: deque(maxlen=64))
_day = {"date": "", "n": 0}


def enabled() -> bool:
    return PROVIDER == "deepseek" and bool(API_KEY)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load_count() -> None:
    if _day["date"] == _today():
        return
    _day.update(date=_today(), n=0)
    try:
        data = json.loads(COUNT_FILE.read_text(encoding="utf-8"))
        if data.get("date") == _day["date"]:
            _day["n"] = int(data.get("n") or 0)
    except (OSError, ValueError, TypeError):
        pass


def _bump() -> None:
    _day["n"] += 1
    try:
        COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
        COUNT_FILE.write_text(json.dumps(dict(_day)), encoding="utf-8")
    except OSError as exc:
        logger.debug(f"web_search: 计数保存失败 {type(exc).__name__}")


def today_count() -> int:
    with _lock:
        _load_count()
        return _day["n"]


def allow(user_id: str = "") -> tuple[bool, str]:
    """这次还能不能查：全局每天、每人每小时两道额度。"""
    if not enabled():
        return False, "没开联网"
    with _lock:
        _load_count()
        if DAILY_MAX > 0 and _day["n"] >= DAILY_MAX:
            return False, f"今天已经查了 {_day['n']} 次"
        if user_id and PER_USER_HOUR > 0:
            q = _per_user[user_id]
            now = time.time()
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= PER_USER_HOUR:
                return False, "这个人这小时查太多了"
    return True, ""


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _cached(kind: str, key: str):
    hit = _cache.get((kind, key))
    if hit and time.time() - hit[0] < CACHE_SEC:
        return hit[1]
    return None


def _remember(kind: str, key: str, value) -> None:
    if len(_cache) > 300:
        for old in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(old, None)
    _cache[(kind, key)] = (time.time(), value)


def _charge(user_id: str) -> None:
    # 只有拿到结果的调用才计费，计数跟着走
    with _lock:
        _load_count()
        _bump()
        if user_id:
            _per_user[user_id].append(time.time())


def search(query: str, user_id: str = "", count: int | None = None) -> list[dict]:
    """搜一次，返回 results（title / url / summary / snippet / site_name / date）；查不了或出错返回空。"""
    q = " ".join((query or "").split())[:128]
    if not q:
        return []
    cached = _cached("s", q)
    if cached is not None:
        return cached
    ok, why = allow(user_id)
    if not ok:
        logger.info(f"web_search: 不查「{q}」（{why}）")
        return []
    try:
        data = _post("/v1/tools/search", {"query": q, "count": max(1, min(10, count or COUNT))})
    except urllib.error.HTTPError as exc:
        logger.warning(f"web_search: 搜索 HTTP {exc.code}「{q}」")
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"web_search: 搜索失败 {type(exc).__name__}「{q}」")
        return []
    results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
    if results:
        _charge(user_id)
    _remember("s", q, results)
    logger.info(f"web_search: 「{q}」{len(results)} 条，今天第 {today_count()} 次")
    return results


def fetch(url: str, user_id: str = "", max_chars: int = 1500) -> str:
    """把一个网页转成 Markdown 正文（截到 max_chars 字）；只认 http/https。"""
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")) or len(u) > 2000:
        return ""
    cached = _cached("f", u)
    if cached is not None:
        return cached
    ok, why = allow(user_id)
    if not ok:
        logger.info(f"web_search: 不看网页（{why}）")
        return ""
    try:
        data = _post("/v1/tools/fetch", {"url": u})
    except urllib.error.HTTPError as exc:
        logger.warning(f"web_search: 看网页 HTTP {exc.code}")
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"web_search: 看网页失败 {type(exc).__name__}")
        return ""
    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "").strip()
    if content:
        _charge(user_id)
    text = (f"# {title}\n" if title else "") + content[:max_chars]
    _remember("f", u, text)
    return text


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "上网搜索。要最新消息、拿不准的事实、没听过的梗时用。"
                "query 只写要查的事（中文关键词即可），不要写群友的名字、QQ 号或聊天原文。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词，128 字以内"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "打开一个网页看正文。只在对方发了链接、或者搜索结果不够用时用。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "http/https 网址"}},
                "required": ["url"],
            },
        },
    },
]
