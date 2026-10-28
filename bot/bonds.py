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

from persona_rules import merge_notes, update_bond

_data_env = os.getenv("PERSONA_DATA_DIR", "").strip()
DATA_FILE = (Path(_data_env) if _data_env else Path(__file__).resolve().parent / "data") / "bonds.json"
USER_NOTE_CAP = int(os.getenv("DIARY_USER_NOTES", "6"))
GROUP_NOTE_CAP = int(os.getenv("DIARY_GROUP_NOTES", "8"))
GROUP_STYLE_CAP = int(os.getenv("DIARY_GROUP_STYLE", "4"))
NOTE_MAX_CHARS = int(os.getenv("DIARY_NOTE_CHARS", "20"))

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
        _state["dirty"] = False


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
    """只读拿一份（没有就是空的默认值），不会建记录。"""
    with _lock:
        return dict(_data["users"].get(str(uid)) or {"aff": 0, "fam": 0, "notes": []})


def touch(uid: str, name: str, delta: int, now: float | None = None) -> dict:
    """这个人跟我说了句话：更新好感、熟悉度和最近用的名字。"""
    with _lock:
        rec = _data["users"].get(str(uid)) or {"notes": []}
        rec.update(update_bond(rec, delta, now))
        rec["name"] = name
        _data["users"][str(uid)] = rec
        _state["dirty"] = True
        return dict(rec)


def add_user_notes(uid: str, texts: list[str], src: str, now: float | None = None) -> int:
    if not texts:
        return 0
    with _lock:
        rec = _data["users"].setdefault(str(uid), {"aff": 0, "fam": 0, "notes": []})
        rec["notes"] = merge_notes(rec.get("notes"), [t[:NOTE_MAX_CHARS] for t in texts], src, now, USER_NOTE_CAP)
        _state["dirty"] = True
    return len(texts)


def group(gid: str) -> dict:
    with _lock:
        return dict(_data["groups"].get(str(gid)) or {"notes": [], "style": []})


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


def forget_user(uid: str) -> bool:
    """本人要求忘掉：整条删掉（群日记里提到他的不动，那是群里公开说过的）。"""
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
