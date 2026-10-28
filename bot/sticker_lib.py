"""表情库的读写与发送，供 stickers / persona 两个插件共用。

索引来自 tools/export_qq_emoji.py + tag_stickers.py；聊天里她自己收藏的表情另存在
stickers/saved/ 和 saved.json（save_sticker），最多 STICKER_SAVE_MAX 张，满了丢最早的。
notes.json 是表情小本本：每张表情的用途备注和用过几次，按场景挑图时会看备注，用得多的更容易被挑中。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import random
import time
from collections import Counter
from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.log import logger

STICKER_DIR = Path(os.getenv("STICKER_DIR") or Path(__file__).resolve().parent.parent / "stickers")
INDEX_FILE = STICKER_DIR / "index.json"
SAVED_DIR = STICKER_DIR / "saved"
SAVED_INDEX = STICKER_DIR / "saved.json"
SAVE_MAX = int(os.getenv("STICKER_SAVE_MAX", "200"))
NOTES_FILE = STICKER_DIR / "notes.json"
NOTE_MAX_CHARS = 20

_items: list[dict] = []
_categories: Counter = Counter()
_last_pick: dict[str, str] = {}
_notes: dict[str, dict] = {}  # id -> {"note": 用途备注, "uses": 用过几次}


def _read_saved() -> list[dict]:
    try:
        return json.loads(SAVED_INDEX.read_text(encoding="utf-8")).get("items", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load() -> None:
    global _items
    items: list[dict] = []
    try:
        items = json.loads(INDEX_FILE.read_text(encoding="utf-8")).get("items", [])
    except FileNotFoundError:
        logger.warning(f"sticker_lib: 没找到 {INDEX_FILE}")
    except json.JSONDecodeError as exc:
        logger.warning(f"sticker_lib: 索引解析失败 {exc}")

    _items = [it for it in items + _read_saved() if (STICKER_DIR / it["file"]).is_file()]
    try:
        _notes.clear()
        _notes.update(json.loads(NOTES_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    _categories.clear()
    _categories.update(item.get("category", "其他") for item in _items)
    logger.info(f"sticker_lib: {len(_items)} 张，分类 {dict(_categories)}")


def _save_notes() -> None:
    try:
        NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = NOTES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_notes, ensure_ascii=False), encoding="utf-8")
        tmp.replace(NOTES_FILE)
    except OSError as exc:
        logger.warning(f"sticker_lib: 表情备注保存失败 {exc}")


def _add_note(sid: str, words: str) -> None:
    rec = _notes.setdefault(sid, {"note": "", "uses": 0})
    if words and words not in rec["note"]:
        rec["note"] = "、".join(filter(None, (rec["note"], words)))[:NOTE_MAX_CHARS]


def mark_used(item: dict, scene: str | None = None) -> None:
    """发过一次：用过几次 +1，在什么场景用的记进备注（以后按场景挑图找得到）。"""
    _add_note(item["id"], scene or "")
    _notes[item["id"]]["uses"] = int(_notes[item["id"]].get("uses", 0)) + 1
    _save_notes()


def set_note(prefix: str, note: str) -> dict | None:
    """手动给某张表情写备注（id 前几位就行）。"""
    hits = [it for it in _items if it["id"].startswith(prefix)] if prefix else []
    if len(hits) != 1:
        return None
    _notes.setdefault(hits[0]["id"], {"note": "", "uses": 0})["note"] = note[:NOTE_MAX_CHARS]
    _save_notes()
    return hits[0]


def favorites(k: int = 5) -> list[tuple[dict, dict]]:
    """用得最多的几张，带备注。"""
    by_id = {it["id"]: it for it in _items}
    ranked = sorted(((by_id[i], n) for i, n in _notes.items() if i in by_id and n.get("uses")),
                    key=lambda pair: -int(pair[1].get("uses", 0)))
    return ranked[:k]


def save_sticker(raw: bytes, category: str, text: str = "", note: str = "") -> dict | None:
    """把聊天里看到的一张表情收进自己的库；已经有了就返回 None。"""
    sid = hashlib.sha1(raw).hexdigest()[:16]
    if any(it.get("id") == sid or it.get("sha1") == sid for it in _items):
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as img:
            fmt = (img.format or "png").lower()
            animated = (getattr(img, "n_frames", 1) or 1) > 1
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"sticker_lib: 不是能用的图片 {type(exc).__name__}")
        return None
    ext = {"jpeg": "jpg"}.get(fmt, fmt)
    item = {
        "id": sid, "sha1": sid, "file": f"saved/{sid}.{ext}", "format": fmt, "animated": animated,
        "tags": ["收藏", "动图" if animated else "静图"], "text": text[:30], "category": category,
        "saved_at": time.time(),
    }
    saved = _read_saved()
    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    (STICKER_DIR / item["file"]).write_bytes(raw)
    saved.append(item)
    saved.sort(key=lambda it: float(it.get("saved_at", 0)))
    for old in saved[:-SAVE_MAX]:
        (STICKER_DIR / old["file"]).unlink(missing_ok=True)
    saved = saved[-SAVE_MAX:]
    tmp = SAVED_INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps({"items": saved}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SAVED_INDEX)
    load()
    _add_note(sid, note)
    _save_notes()
    return item


def count() -> int:
    return len(_items)


def categories() -> Counter:
    return _categories


def pick(keyword: str = "", session: str = "") -> dict | None:
    pool = _items
    if keyword:
        kw = keyword.lower()
        pool = [
            it for it in _items
            if kw in it.get("category", "").lower()
            or any(kw in str(t).lower() for t in it.get("tags", []))
            or kw in it.get("text", "").lower()
        ]
    if not pool:
        return None

    recent = {_last_pick[session]} if session in _last_pick else set()
    fresh = [it for it in pool if it["id"] not in recent] or pool
    chosen = random.choice(fresh)
    if session:
        _last_pick[session] = chosen["id"]
    return chosen


def pick_for_mood(mood: str, session: str = "", prefer_saved: float = 0.0) -> dict | None:
    """炸毛挑生气的，甜挑卖萌的，兜底随机；prefer_saved 的概率先从自己收藏的里挑。"""
    order = ["生气", "卖萌"] if mood == "炸毛" else ["卖萌", "搞笑"]
    if prefer_saved > 0 and random.random() < prefer_saved:
        saved = [it for it in _items if it.get("file", "").startswith("saved/")]
        fitting = [it for it in saved if it.get("category") in order] or saved
        if fitting:
            chosen = random.choice(fitting)
            if session:
                _last_pick[session] = chosen["id"]
            return chosen
    for cat in order:
        chosen = pick(cat, session)
        if chosen:
            return chosen
    return pick("", session)


def pick_for_scene(words: tuple[str, ...], session: str = "", prefer_saved: float = 0.0) -> dict | None:
    """找分类、标签或图上的字对得上场景的表情；一张都对不上返回 None（宁可不发也别乱发）。"""
    def fits(it: dict) -> bool:
        note = (_notes.get(it["id"]) or {}).get("note", "")
        hay = f"{it.get('category', '')} {' '.join(map(str, it.get('tags', [])))} {it.get('text', '')} {note}"
        return any(w and w in hay for w in words)

    pool = [it for it in _items if fits(it)]
    if not pool:
        return None
    saved = [it for it in pool if it.get("file", "").startswith("saved/")]
    if saved and random.random() < prefer_saved:
        pool = saved
    recent = {_last_pick[session]} if session in _last_pick else set()
    pool = [it for it in pool if it["id"] not in recent] or pool
    # 用得多的是她喜欢的，更容易被挑中
    weights = [1 + min(10, int((_notes.get(it["id"]) or {}).get("uses", 0))) for it in pool]
    chosen = random.choices(pool, weights=weights)[0]
    if session:
        _last_pick[session] = chosen["id"]
    return chosen


async def send(bot: Bot, event: MessageEvent, item: dict) -> bool:
    path = (STICKER_DIR / item["file"]).resolve()
    try:
        await bot.send(event, MessageSegment.image(path.as_uri()))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"sticker_lib: file:// 失败（{type(exc).__name__}），改用 base64")
        try:
            data = base64.b64encode(path.read_bytes()).decode()
            await bot.send(event, MessageSegment.image(f"base64://{data}"))
            return True
        except Exception as exc2:  # noqa: BLE001
            logger.error(f"sticker_lib: 发送失败 {type(exc2).__name__}: {exc2}")
            return False


load()

