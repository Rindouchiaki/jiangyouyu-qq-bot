"""群友小本本：好感度、熟悉度和简短日记。

- 按 QQ 号存一份，群里的 A 和私聊的 A 是同一条记录；
- 每个群另有一份群日记：群友之间的关系（谁和谁常一起玩什么），和本群的说话风格、常玩的梗；
- 日记每条不超过 DIARY_NOTE_CHARS 字，每人 DIARY_USER_NOTES 条、每群 DIARY_GROUP_NOTES 条，满了丢最旧的；
- 私聊里听来的事记 src="p"，只在私聊里用（见 persona_rules.visible_notes）。

数据在 data/bonds.json（和 history.json 同目录），不依赖 NoneBot，方便离线测。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import devs
from persona_rules import INITIAL_AFF, INITIAL_FAM, dev_floor, merge_notes, new_bond, update_bond

# 初始好感度迁移标记：老数据里「刚认识」的人抬到礼貌底线，只做一次
FLOOR_VERSION = 1

_data_env = os.getenv("PERSONA_DATA_DIR", "").strip()
DATA_FILE = (Path(_data_env) if _data_env else Path(__file__).resolve().parent / "data") / "bonds.json"
USER_NOTE_CAP = int(os.getenv("DIARY_USER_NOTES", "6"))
GROUP_NOTE_CAP = int(os.getenv("DIARY_GROUP_NOTES", "8"))
GROUP_STYLE_CAP = int(os.getenv("DIARY_GROUP_STYLE", "4"))
NOTE_MAX_CHARS = int(os.getenv("DIARY_NOTE_CHARS", "20"))
# 话题权重：聊到一次 +1，最多 TOPIC_MAX；两周没提权重减半，低于 TOPIC_MIN_SCORE 就当没这个兴趣
TOPIC_MAX = int(os.getenv("TOPIC_MAX_WEIGHT", "60"))
TOPIC_HALF_DAYS = float(os.getenv("TOPIC_HALF_DAYS", "14"))
TOPIC_MIN_SCORE = float(os.getenv("TOPIC_MIN_SCORE", "1.2"))

_lock = threading.RLock()
_data: dict = {"users": {}, "groups": {}}
_state = {"dirty": False, "saved": 0.0}


def load(path: Path | None = None) -> None:
    global DATA_FILE
    if path is not None:
        DATA_FILE = path
    with _lock:
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            raw = {}
        _data["users"] = raw.get("users") if isinstance(raw.get("users"), dict) else {}
        _data["groups"] = raw.get("groups") if isinstance(raw.get("groups"), dict) else {}
        _data["floor"] = raw.get("floor", 0)
        _state["dirty"] = _raise_floor()
        if _state["dirty"]:
            # 迁移的结果先落盘，别等下一次互动才写，避免重启后又回到旧值再迁一次
            save(force=True)


def _raise_floor() -> bool:
    """老数据里好感低、还没混熟的人抬到礼貌底线（好感 0 以下的不动，那是真被惹到了）。

    只做一次，用 floor 字段记账，之后新建的记录直接就是新底线。
    """
    if int(_data.get("floor") or 0) >= FLOOR_VERSION:
        return False
    for rec in _data["users"].values():
        aff, fam = int(rec.get("aff", 0)), int(rec.get("fam", 0))
        if 0 <= aff < INITIAL_AFF:
            rec["aff"] = INITIAL_AFF
        if fam < INITIAL_FAM:
            rec["fam"] = INITIAL_FAM
    _data["floor"] = FLOOR_VERSION
    return True


def save(force: bool = False) -> None:
    """有改动才写；平时最多 10 秒写一次，写临时文件再替换，断电也不会写坏。"""
    with _lock:
        if not _state["dirty"] or (not force and time.time() - _state["saved"] < 10):
            return
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(DATA_FILE)
        _state["dirty"], _state["saved"] = False, time.time()


def user(uid: str) -> dict:
    """只读拿一份（没有就是初始值），不会建记录。"""
    with _lock:
        rec = dict(_data["users"].get(str(uid)) or new_bond())
    # 开发者好感最低「有好感」：旧记录、/好感 手动调低的也按保底算
    return dev_floor(rec) if devs.is_dev(uid) else rec


def find_user(text: str) -> list[str]:
    """按昵称找 QQ 号：昵称里包含关键字就算，忽略大小写。

    私聊里没法 @ 人，只能靠这个把人名翻译成 QQ 号；群聊里也顺手支持。
    返回匹配到的 QQ 号列表（0 个 / 1 个 / 多个，由调用方决定怎么处理）。
    """
    key = (text or "").strip().lower()
    if not key:
        return []
    with _lock:
        return [
            uid
            for uid, rec in _data["users"].items()
            if key and key in str(rec.get("name") or "").lower()
        ]


def touch(uid: str, name: str, delta: int, now: float | None = None) -> dict:
    """这个人跟我说了句话：更新好感、熟悉度和最近用的名字。"""
    with _lock:
        rec = _data["users"].get(str(uid)) or {"notes": []}
        rec.update(update_bond(rec, delta, now, dev=devs.is_dev(uid)))
        rec["name"] = name
        _data["users"][str(uid)] = rec
        _state["dirty"] = True
        return dict(rec)


def set_levels(
    uid: str, name: str = "", aff: int | None = None, fam: int | None = None
) -> tuple[dict, dict]:
    """开发者手动调好感/熟悉度（/好感）：给 None 的项不动。返回 (改前, 改后)。"""
    with _lock:
        rec = _data["users"].setdefault(str(uid), new_bond())
        before = dict(rec)
        if name:
            rec["name"] = name
        if aff is not None:
            rec["aff"] = max(-100, min(100, int(aff)))
        if fam is not None:
            rec["fam"] = max(0, min(100, int(fam)))
        if devs.is_dev(uid):
            rec.update(dev_floor(rec))
        _state["dirty"] = True
        return before, dict(rec)


def learn_topics(uid: str, name: str = "", words: list[str] | tuple[str, ...] = (),
                 now: float | None = None) -> list[str]:
    """这个人又聊到这些话题了：每个话题权重 +1（封顶 TOPIC_MAX），记下最近一次时间。"""
    words = [w for w in dict.fromkeys(words) if w]
    if not words:
        return []
    ts = time.time() if now is None else now
    with _lock:
        rec = _data["users"].setdefault(str(uid), new_bond())
        if name:
            rec["name"] = name
        topics = rec.setdefault("topics", {})
        for w in words:
            item = topics.setdefault(w, {"w": 0.0, "t": ts})
            item["w"] = min(TOPIC_MAX, float(item.get("w", 0)) + 1.0)
            item["t"] = ts
        _state["dirty"] = True
    return words


def top_topics(uid: str, k: int = 3, now: float | None = None) -> list[str]:
    """最近常聊的话题：按「两周减半」衰减后取前 k 个；没什么记录就返回空。"""
    ts = time.time() if now is None else now
    with _lock:
        rec = _data["users"].get(str(uid)) or {}
        topics = dict(rec.get("topics") or {})
    scored: list[tuple[float, str]] = []
    for word, item in topics.items():
        weight = float(item.get("w", 0) or 0)
        days = max(0.0, (ts - float(item.get("t", 0) or 0)) / 86400)
        score = weight * (0.5 ** (days / TOPIC_HALF_DAYS))
        if score >= TOPIC_MIN_SCORE:
            scored.append((score, word))
    scored.sort(key=lambda pair: -pair[0])
    return [word for _, word in scored[:k]]


def add_user_notes(uid: str, texts: list[str], src: str, now: float | None = None) -> int:
    if not texts:
        return 0
    with _lock:
        rec = _data["users"].setdefault(str(uid), new_bond())
        rec["notes"] = merge_notes(rec.get("notes"), [t[:NOTE_MAX_CHARS] for t in texts], src, now, USER_NOTE_CAP)
        _state["dirty"] = True
    return len(texts)


def group(gid: str) -> dict:
    with _lock:
        return dict(_data["groups"].get(str(gid)) or {"notes": [], "style": []})


def known_groups() -> list[str]:
    """记过群日记或群风格的群号。"""
    with _lock:
        return [gid for gid, rec in _data["groups"].items() if rec.get("notes") or rec.get("style")]


def known_people(ids: object) -> list[tuple[str, dict]]:
    """这些 QQ 号里她有记录的人（只读副本，开发者按保底算），按熟悉度从高到低。"""
    wanted = {str(i) for i in ids}
    with _lock:
        recs = [(uid, dict(rec)) for uid, rec in _data["users"].items() if uid in wanted]
    recs = [(uid, dev_floor(rec) if devs.is_dev(uid) else rec) for uid, rec in recs]
    return sorted(recs, key=lambda pair: -int(pair[1].get("fam", 0)))


def add_group_notes(gid: str, texts: list[str], now: float | None = None) -> int:
    if not texts:
        return 0
    with _lock:
        rec = _data["groups"].setdefault(str(gid), {"notes": []})
        rec["notes"] = merge_notes(rec.get("notes"), [t[:NOTE_MAX_CHARS] for t in texts], "g", now, GROUP_NOTE_CAP)
        _state["dirty"] = True
    return len(texts)


def add_group_style(gid: str, texts: list[str], now: float | None = None) -> int:
    if not texts:
        return 0
    with _lock:
        rec = _data["groups"].setdefault(str(gid), {"notes": []})
        rec["style"] = merge_notes(rec.get("style"), [t[:NOTE_MAX_CHARS] for t in texts], "g", now, GROUP_STYLE_CAP)
        _state["dirty"] = True
    return len(texts)


def mark_private(uid: str, now: float | None = None) -> None:
    """对方私聊找我了：记下时间，主动找他没回的次数清零（lp / pu，见 persona_rules.proactive_due）。"""
    with _lock:
        rec = _data["users"].get(str(uid))
        if rec is None:
            return
        rec["lp"] = now or time.time()
        rec["pu"] = 0
        _state["dirty"] = True


def mark_proactive(uid: str, now: float | None = None) -> None:
    """我主动找了他一次：记时间，没回的次数 +1，他一回就清零。"""
    with _lock:
        rec = _data["users"].get(str(uid))
        if rec is None:
            return
        rec["pa"] = now or time.time()
        rec["pu"] = int(rec.get("pu") or 0) + 1
        _state["dirty"] = True


def private_contacts() -> list[tuple[str, dict]]:
    """私聊过的人（只读副本），主动找人时从这里挑。"""
    with _lock:
        recs = [(uid, dict(rec)) for uid, rec in _data["users"].items() if rec.get("lp")]
    return [(uid, dev_floor(rec) if devs.is_dev(uid) else rec) for uid, rec in recs]


def forget_user(uid: str) -> bool:
    """开发者删某人的记录（/小本本 删除）：整条删掉（群日记里提到他的不动，那是群里公开说过的）。"""
    with _lock:
        existed = _data["users"].pop(str(uid), None) is not None
        _state["dirty"] = _state["dirty"] or existed
    return existed


def clear_group(gid: str) -> bool:
    with _lock:
        existed = _data["groups"].pop(str(gid), None) is not None
        _state["dirty"] = _state["dirty"] or existed
    return existed


load()
