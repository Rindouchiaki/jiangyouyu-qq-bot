"""表情库的读写与发送，供 stickers / persona 两个插件共用。

索引来自 tools/export_qq_emoji.py + tag_stickers.py。
"""

from __future__ import annotations

import base64
import json
import os
import random
from collections import Counter
from pathlib import Path

from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.log import logger

STICKER_DIR = Path(os.getenv("STICKER_DIR") or Path(__file__).resolve().parent.parent / "stickers")
INDEX_FILE = STICKER_DIR / "index.json"

_items: list[dict] = []
_categories: Counter = Counter()
_last_pick: dict[str, str] = {}


def load() -> None:
    global _items
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning(f"sticker_lib: 没找到 {INDEX_FILE}")
        return
    except json.JSONDecodeError as exc:
        logger.warning(f"sticker_lib: 索引解析失败 {exc}")
        return

    _items = [it for it in data.get("items", []) if (STICKER_DIR / it["file"]).is_file()]
    _categories.clear()
    _categories.update(item.get("category", "其他") for item in _items)
    logger.info(f"sticker_lib: {len(_items)} 张，分类 {dict(_categories)}")


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


def pick_for_mood(mood: str, session: str = "") -> dict | None:
    """炸毛挑生气的，甜挑卖萌的，兜底随机。"""
    order = ["生气", "卖萌"] if mood == "炸毛" else ["卖萌", "搞笑"]
    for cat in order:
        chosen = pick(cat, session)
        if chosen:
            return chosen
    return pick("", session)


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

