"""表情库的读写与发送，供 stickers / persona 两个插件共用。

索引来自 tools/export_qq_emoji.py + tag_stickers.py；聊天里她自己收藏的表情另存在
stickers/saved/ 和 saved.json（save_sticker），最多 STICKER_SAVE_MAX 张，满了丢最早的。
notes.json 是表情小本本：每张表情的用途备注和用过几次，按场景挑图时会看备注，用得多的更容易被挑中。
reads.json 是读后感：本地视觉模型看过一遍记下的画面、意思、场景、画风（按 id 存，读过不再读）；
她更喜欢可爱的二次元表情，挑图时更常发；自己收藏里真不喜欢、或者很久一次都没发过的才会被删（prune），
收藏满了先挤掉最不喜欢、最少用的。
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

from persona_rules import STICKER_LIKE_WEIGHT, sticker_keep_rank, sticker_like, sticker_prune_due

STICKER_DIR = Path(os.getenv("STICKER_DIR") or Path(__file__).resolve().parent.parent / "stickers")
INDEX_FILE = STICKER_DIR / "index.json"
SAVED_DIR = STICKER_DIR / "saved"
SAVED_INDEX = STICKER_DIR / "saved.json"
SAVE_MAX = int(os.getenv("STICKER_SAVE_MAX", "200"))
NOTES_FILE = STICKER_DIR / "notes.json"
NOTE_MAX_CHARS = 20
READS_FILE = STICKER_DIR / "reads.json"

_items: list[dict] = []
_categories: Counter = Counter()
_last_pick: dict[str, str] = {}
_notes: dict[str, dict] = {}  # id -> {"note": 用途备注, "uses": 用过几次}
_reads: dict[str, dict] = {}  # id -> {"desc", "mean", "scene", "acg", "cute", "at"}
# 每个会话最近发过的几张（越靠后越新）和各类用了几次：用来压住重复，别老发固定的那几张
_pick_hist: dict[str, list[str]] = {}
_cat_used: dict[str, Counter] = {}
HIST_MAX = 8
# 用过的次数越多越难再被选中：权重 1/(1 + USES_FADE * uses)
USES_FADE = float(os.getenv("STICKER_USES_FADE", "0.6"))
# 最近第 1 / 前 3 / 前 8 张的降权系数；同分类连发也降权
RECENT_FADE = (0.05, 0.2, 0.5)
CAT_FADE = float(os.getenv("STICKER_CAT_FADE", "0.35"))
# 已经在至少 6 张里能挑时，绝不再发上一张
HARD_SKIP = int(os.getenv("STICKER_HARD_SKIP", "6"))
# 心情 → 候选分类及概率：合适的分类只占一部分，剩下的给中性表情，免得一张图包办所有场合
MOOD_MIX = {
    "炸毛": (("生气", 0.35), ("拒绝", 0.10), ("无文字", 0.25), ("其他", 0.20), ("疑问", 0.05), ("搞笑", 0.05)),
    "甜": (("卖萌", 0.25), ("夸奖", 0.10), ("回应", 0.10), ("无文字", 0.25), ("其他", 0.20), ("搞笑", 0.10)),
    "不耐烦": (("拒绝", 0.20), ("生气", 0.10), ("无文字", 0.35), ("其他", 0.35)),
    "清醒": (("无文字", 0.35), ("其他", 0.30), ("疑问", 0.10), ("回应", 0.10), ("搞笑", 0.10), ("卖萌", 0.05)),
}
_by_cat: dict[str, list[dict]] = {}


def _weight(item: dict, session: str = "") -> float:
    """一张表情这回合被选中的相对权重：用得越多、最近刚发过、同分类连发，都会往下压。"""
    weight = 1.0 / (1.0 + USES_FADE * int((_notes.get(item["id"]) or {}).get("uses", 0)))
    # 喜好：可爱的二次元表情更常发
    weight *= STICKER_LIKE_WEIGHT.get(sticker_like(read_of(item["id"])) or "", 1.0)
    hist = _pick_hist.get(session, []) if session else []
    for depth, fade in zip((1, 3, 8), RECENT_FADE):
        if item["id"] in hist[-depth:]:
            weight *= fade
            break
    if session:
        used = _cat_used.get(session, Counter()).get(item.get("category", "其他"), 0)
        if used:
            weight *= 1.0 / (1.0 + CAT_FADE * used)
    return max(weight, 1e-5)


def _remember(session: str, item: dict) -> dict:
    """记下这次发了什么，供下一次降权用。"""
    if session:
        hist = _pick_hist.setdefault(session, [])
        hist.append(item["id"])
        del hist[:-HIST_MAX]
        _cat_used.setdefault(session, Counter())[item.get("category", "其他")] += 1
        _last_pick[session] = item["id"]
    return item


def _weighted(pool: list[dict], session: str = "", prefer_saved: float = 0.0) -> dict:
    """按权重抽一张；prefer_saved 是「先从自己收藏的里挑」的概率。"""
    saved = [it for it in pool if it.get("file", "").startswith("saved/")]
    if saved and prefer_saved > 0 and random.random() < prefer_saved:
        pool = saved
    return _remember(session, random.choices(pool, weights=[_weight(it, session) for it in pool])[0])


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
    try:
        _reads.clear()
        _reads.update(json.loads(READS_FILE.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    _categories.clear()
    _categories.update(item.get("category", "其他") for item in _items)
    _by_cat.clear()
    for item in _items:
        _by_cat.setdefault(item.get("category", "其他"), []).append(item)
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


def read_of(sid: str) -> dict | None:
    """这张表情的读后感；没读过、或者读了没看懂的返回 None。"""
    read = _reads.get(sid)
    return read if read and read.get("desc") else None


def has_read(sid: str) -> bool:
    """读过没有（含读了没看懂的）。"""
    return sid in _reads


def set_read(sid: str, read: dict) -> None:
    _reads[sid] = {**read, "at": time.time()}
    try:
        READS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = READS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_reads, ensure_ascii=False), encoding="utf-8")
        tmp.replace(READS_FILE)
    except OSError as exc:
        logger.warning(f"sticker_lib: 读后感保存失败 {exc}")


def next_unread() -> dict | None:
    """库里（原库 + 收藏）下一张还没读过的表情，后台慢慢读。"""
    return next((it for it in _items if it["id"] not in _reads), None)


def unread_count() -> int:
    return sum(1 for it in _items if it["id"] not in _reads)


def label(item: dict) -> str:
    """发出去的表情记进上下文时怎么写：读过的写画面，没读过写分类。"""
    read = read_of(item["id"]) or {}
    return read.get("mean") or read.get("desc") or item.get("category") or "表情"


def prune(now: float | None = None, dislike_days: float = 30, idle_days: float = 90) -> list[dict]:
    """删掉自己收藏里真不喜欢、或者很久一次都没发过的表情；原库不动。返回删掉的。"""
    now = time.time() if now is None else now
    saved = _read_saved()
    gone = [
        it for it in saved
        if sticker_prune_due(
            it, read_of(it["id"]), int((_notes.get(it["id"]) or {}).get("uses", 0)), now, dislike_days, idle_days,
        )
    ]
    if not gone:
        return []
    ids = {it["id"] for it in gone}
    for it in gone:
        (STICKER_DIR / it["file"]).unlink(missing_ok=True)
        _notes.pop(it["id"], None)
    tmp = SAVED_INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps({"items": [it for it in saved if it["id"] not in ids]}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SAVED_INDEX)
    _save_notes()
    load()
    return gone


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
    if len(saved) > SAVE_MAX:
        # 满了先挤掉最不喜欢、最少用、最早收的（刚收的这张不算）
        ranked = sorted(saved[:-1], key=lambda it: sticker_keep_rank(
            read_of(it["id"]), int((_notes.get(it["id"]) or {}).get("uses", 0)), float(it.get("saved_at", 0))))
        out = {it["id"] for it in ranked[: len(saved) - SAVE_MAX]}
        for old in ranked[: len(saved) - SAVE_MAX]:
            (STICKER_DIR / old["file"]).unlink(missing_ok=True)
        saved = [it for it in saved if it["id"] not in out]
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

    # 能挑的够多时先剔掉上一张，避免连着两次同一张
    hist = _pick_hist.get(session, []) if session else []
    if len(pool) >= HARD_SKIP and hist:
        fresh = [it for it in pool if it["id"] != hist[-1]]
        pool = fresh or pool
    return _weighted(pool, session)


def pick_for_mood(mood: str, session: str = "", prefer_saved: float = 0.0) -> dict | None:
    """按心情先挑分类、再在分类里按新鲜度挑一张：既对味，又不会老发固定那几张。

    心情合适的分类只占一部分概率（炸毛时 35% 生气 + 10% 拒绝），剩下分给无文字、
    其他这些中性表情；分类里不足 2 张就把它的概率匀回去，避免一张图反复发。
    """
    mix = list(MOOD_MIX.get(mood) or MOOD_MIX["清醒"])
    if prefer_saved > 0 and random.random() < prefer_saved:
        saved = [it for it in _items if it.get("file", "").startswith("saved/")]
        fitting = [it for it in saved if it.get("category") in {c for c, _ in mix}] or saved
        if fitting:
            return _weighted(fitting, session)
    # 分类里凑不够两张的（拒绝只有 1 张）不参与抽，概率按比例分给别人
    sized = [(cat, p) for cat, p in mix if len(_by_cat.get(cat, [])) >= 2]
    if not sized:
        return _weighted(_items, session) if _items else None
    total = sum(p for _, p in sized)
    roll = random.random() * total
    for cat, p in sized:
        roll -= p
        if roll <= 0:
            return _weighted(_by_cat[cat], session)
    return _weighted(_by_cat[sized[-1][0]], session)


def pick_for_scene(words: tuple[str, ...], session: str = "", prefer_saved: float = 0.0) -> dict | None:
    """找分类、标签或图上的字对得上场景的表情；一张都对不上返回 None（宁可不发也别乱发）。"""
    def fits(it: dict) -> bool:
        note = (_notes.get(it["id"]) or {}).get("note", "")
        read = _reads.get(it["id"]) or {}
        hay = (
            f"{it.get('category', '')} {' '.join(map(str, it.get('tags', [])))} {it.get('text', '')} {note} "
            f"{read.get('desc', '')} {read.get('mean', '')} {read.get('scene', '')}"
        )
        return any(w and w in hay for w in words)

    pool = [it for it in _items if fits(it)]
    if not pool:
        return None
    return _weighted(pool, session, prefer_saved)


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

