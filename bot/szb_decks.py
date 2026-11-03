"""影之诗卡组库：/szb 查卡组、收投稿、人设推荐都走这里。

数据只有一份 `decks.json`，图片在 `images/` 下；写入先落临时文件再 os.replace，
避免写一半断电把整个库写坏。抓来的卡组（shadowverse-wins.com）标 source=scrape，
群里投稿的标 source=submit。
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path

DATA_DIR = Path(os.getenv("SZB_DECK_DIR", str(Path(__file__).resolve().parent / "data" / "szb_decks")))
INDEX_FILE = DATA_DIR / "decks.json"
IMAGE_DIR = DATA_DIR / "images"

CLASSES = ("皇家", "妖精", "超越者", "梦魇", "法师", "主教", "龙族")
ENVS = ("指定", "无限")

# 展示用的简称（拼卡组名时用）
CLASS_SHORT = {
    "皇家": "皇",
    "妖精": "妖",
    "超越者": "超",
    "梦魇": "梦",
    "法师": "法",
    "主教": "教",
    "龙族": "龙",
}

# 群友可能怎么叫，长的放前面，匹配时按顺序试
_CLASS_ALIASES = {
    "皇家": ("皇家", "皇", "皇家护卫", "royal", "ロイヤル"),
    "妖精": ("妖精", "精灵", "妖", "elf", "エルフ"),
    "超越者": ("超越者", "超越", "复仇者", "超", "portal", "ネメシス"),
    "梦魇": ("梦魇", "梦", "死灵", "吸血鬼", "鬼", "nightmare", "ナイトメア"),
    "法师": ("法师", "巫师", "法", "witch", "ウィッチ"),
    "主教": ("主教", "教", "bishop", "ビショップ"),
    "龙族": ("龙族", "龙", "dragon", "ドラゴン"),
}

_ENV_ALIASES = {
    "指定": ("指定", "轮换", "标准", "rotation", "standard"),
    "无限": ("无限", "无限赛制", "unlimited"),
}

MAX_NAME = 20
LIST_LIMIT = int(os.getenv("SZB_LIST_LIMIT", "15"))
MAX_IMAGE_MB = float(os.getenv("SZB_MAX_IMAGE_MB", "10"))
IMAGE_WIDTH = int(os.getenv("SZB_IMAGE_WIDTH", "1280"))
MAX_IMAGES = int(os.getenv("SZB_MAX_IMAGES", "4"))

_state: dict = {"version": 1, "next_id": 1, "decks": []}
_loaded = False
_dirty = False


class DeckError(Exception):
    """入库失败，message 直接回给用户。"""


def _load() -> None:
    global _loaded, _state
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("decks"), list):
            _state = raw
    except (OSError, ValueError):
        _state = {"version": 1, "next_id": 1, "decks": []}


def save(force: bool = False) -> None:
    global _dirty
    if not _dirty and not force:
        return
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    if INDEX_FILE.exists():
        try:
            INDEX_FILE.replace(INDEX_FILE.with_suffix(".json.bak"))
        except OSError:
            pass
    tmp = INDEX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, INDEX_FILE)
    _dirty = False


def reload() -> None:
    """改过文件（比如手动整理）后用一下。"""
    global _loaded
    _loaded = False
    _load()


def parse_class(text: str) -> str | None:
    """认职业。

    多字别名（皇家/妖精/超越…）与单字别名（皇/妖/超/梦…）都按子串认——
    「跳费龙」这种卡组名里也带职业字。整句正好是某个卡组名的情况，
    由 parse_query() 先行拦下，不会把名字啃掉一截。
    """
    low = (text or "").strip().lower()
    if not low:
        return None
    for name, aliases in _CLASS_ALIASES.items():
        for alias in aliases:
            if alias.lower() in low:
                return name
    return None


def parse_env(text: str) -> str | None:
    low = (text or "").strip().lower()
    if not low:
        return None
    for name, aliases in _ENV_ALIASES.items():
        for alias in aliases:
            if alias.lower() in low:
                return name
    return None


def _strip_class_env(text: str) -> str:
    """把「皇家」「无限」这些词从一句话里抠掉，剩下的当卡组名。

    先按空格整词删（「皇家 无限 控制皇」→「控制皇」），再把多字别名当子串删，
    单字别名（皇/妖/法/龙/教/超/梦）只在整词相同时删，免得把「控制皇」的「皇」也削掉。
    """
    tokens = [t for t in re.split(r"\s+", (text or "").strip()) if t]
    single = {a.lower() for aliases in _CLASS_ALIASES.values() for a in aliases if len(a) == 1}
    whole = {a.lower() for aliases in list(_CLASS_ALIASES.values()) + list(_ENV_ALIASES.values()) for a in aliases}
    keep = [t for t in tokens if t.lower() not in whole]
    left = " ".join(keep)
    for aliases in list(_CLASS_ALIASES.values()) + list(_ENV_ALIASES.values()):
        for alias in aliases:
            if len(alias) >= 2:
                left = re.sub(re.escape(alias), " ", left, flags=re.IGNORECASE)
    left = " ".join(t for t in left.split() if t.lower() not in single)
    return re.sub(r"\s+", " ", left).strip()


def parse_query(text: str) -> dict:
    """「皇家 无限 控制皇」→ {cls, env, name}，缺的给 None。

    整句正好是库里某个卡组名时直接按名字算，不当成「职业 + 别的词」。
    """
    _load()
    whole = (text or "").strip()
    if whole:
        for deck in _state["decks"]:
            if (deck.get("name") or "").strip() == whole or (deck.get("alias") or "").strip() == whole:
                return {"cls": None, "env": None, "name": whole}
    cls = parse_class(text)
    env = parse_env(text)
    name = _strip_class_env(text)
    return {"cls": cls, "env": env, "name": name or None}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")


def deck_num(deck: dict) -> int:
    """卡组序号（就是卡组名后面那个数字，也是 /szb <序号> 用的号）。"""
    num = deck.get("num")
    if num:
        return int(num)
    did = str(deck.get("id") or "")
    return int(did[1:]) if did[1:].isdigit() else 0


def deck_label(deck: dict) -> str:
    """列表里显示成「梦7（中速梦）」：名字短好打，括号里是原来的说法。"""
    name = str(deck.get("name") or "")
    alias = str(deck.get("alias") or "").strip()
    return f"{name}（{alias}）" if alias and alias != name else name


def _bigrams(text: str) -> set[str]:
    clean = re.sub(r"[^\w\u4e00-\u9fa5]", "", text or "")
    return {clean[i : i + 2] for i in range(len(clean) - 1)} if len(clean) > 1 else {clean}


def _score(deck: dict, text: str, cls: str | None, env: str | None) -> float:
    name = deck.get("name", "")
    score = 0.0
    if name and name in text:
        score += 100 + len(name)
    else:
        a, b = _bigrams(name), _bigrams(text)
        if a and b:
            score += 40 * len(a & b) / len(a)
    if cls and deck.get("cls") == cls:
        score += 20
    if env and deck.get("env") == env:
        score += 10
    return score


def list_decks(
    cls: str | None = None,
    env: str | None = None,
    name: str | None = None,
    limit: int = LIST_LIMIT,
) -> list[dict]:
    _load()
    out = []
    key = (name or "").strip().lower()
    for deck in _state["decks"]:
        if deck.get("status") not in (None, "ok"):
            continue
        if cls and deck.get("cls") != cls:
            continue
        if env and deck.get("env") != env:
            continue
        if key:
            hay = [
                (deck.get("name") or "").lower(),
                (deck.get("alias") or "").lower(),
                (deck.get("note") or "").lower(),
                str(deck_num(deck)),
            ]
            if not any(key in h for h in hay):
                continue
        out.append(deck)
    # 新的在前；投稿比抓取稍微靠前一点，免得第一个永远是抓来的
    out.sort(key=lambda d: (d.get("created_at") or "", 1 if d.get("source") == "submit" else 0), reverse=True)
    return out[:limit]


def count_decks() -> int:
    _load()
    return len(_state["decks"])


def find_one(name: str, env: str | None = None, cls: str | None = None) -> dict | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    pool = list_decks(cls, env, None, limit=500)
    if key.isdigit():
        for d in pool:
            if deck_num(d) == int(key):
                return d
    for d in pool:
        if (d.get("name") or "").lower() == key or (d.get("alias") or "").lower() == key:
            return d
    return None


def find_by_num(num: int) -> dict | None:
    for d in list_decks(None, None, None, limit=500):
        if deck_num(d) == int(num):
            return d
    return None


def best_match(text: str, cls: str | None = None, env: str | None = None) -> dict | None:
    """人设用：从这句话里挑最接近的一套，低于 20 分当没找到。"""
    pool = list_decks(cls, env, None, limit=200)
    if not pool:
        return None
    best, best_score = None, 0.0
    for deck in pool:
        sc = _score(deck, text, cls, env)
        if sc > best_score:
            best, best_score = deck, sc
    return best if best_score >= 20 else None


def deck_note(cls: str | None = None, env: str | None = None, limit: int = 2) -> str:
    """给模型看的几句：只给名字和来源，不给图。"""
    decks = list_decks(cls, env, None, limit=limit)
    if not decks:
        return ""
    parts = []
    for d in decks:
        src = "投稿" if d.get("source") == "submit" else "抓取"
        parts.append(f"{deck_label(d)}（{d.get('cls')}·{d.get('env')}，{src}）")
    return "；".join(parts)


def _image_path(deck_id: str, index: int = 1) -> Path:
    return IMAGE_DIR / f"{deck_id}-{index}.jpg"


def _deck_images(deck: dict) -> list[str]:
    """一套卡组的图：新数据是 images 列表，老数据只有一张 image。"""
    paths = [p for p in (deck.get("images") or []) if p]
    if not paths and deck.get("image"):
        paths = [deck["image"]]
    return paths


def _prepare_image(raw: bytes) -> bytes:
    """统一成宽 ≤1280 的 JPEG；Pillow 打不开就当不是图。"""
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(raw))
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if img.width > IMAGE_WIDTH:
            height = max(1, round(img.height * IMAGE_WIDTH / img.width))
            img = img.resize((IMAGE_WIDTH, height), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 - 用户发来的图什么格式都可能有
        raise DeckError("这张图打不开，换一张试试") from exc


def add_deck(
    *,
    name: str,
    cls: str,
    env: str = "指定",
    images: list[bytes] | None = None,
    image: bytes | None = None,  # 兼容老调用：单张图
    source: str = "submit",
    author: dict | None = None,
    group: str | None = None,
    meta: dict | None = None,
    note: str = "",
) -> dict:
    _load()
    global _dirty
    clean_name = re.sub(r"\s+", " ", (name or "").strip())[:MAX_NAME]
    if cls not in CLASSES:
        raise DeckError(f"职业只能是：{'、'.join(CLASSES)}")
    if env not in ENVS:
        raise DeckError("环境只能是：指定、无限")
    raw_shots = list(images or [])
    if image:
        raw_shots.append(image)
    shots = [i for i in raw_shots if i][:MAX_IMAGES]
    if not shots:
        raise DeckError("没图，没法收")

    raw_hash = hashlib.sha256(b"\x00".join(shots)).hexdigest()
    for deck in _state["decks"]:
        if deck.get("sha256") == raw_hash:
            raise DeckError(f"这张已经收过了：{deck.get('name')}")

    # 名字统一成「职业简称 + 序号」（梦7、皇12），原来的说法留作别名
    deck_id = f"d{_state['next_id']:04d}"
    num = int(deck_id[1:])
    final_name = f"{CLASS_SHORT[cls]}{num}"
    alias = clean_name if clean_name and clean_name != final_name else ""
    _state["next_id"] += 1
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for idx, shot in enumerate(shots, start=1):
        path = _image_path(deck_id, idx)
        path.write_bytes(_prepare_image(shot))
        saved.append(f"images/{path.name}")

    deck = {
        "id": deck_id,
        "num": num,
        "name": final_name,
        "alias": alias,
        "cls": cls,
        "env": env,
        "source": source,
        "status": "ok",
        "image": saved[0],
        "images": saved,
        "sha256": raw_hash,
        "author": author or {},
        "group": group,
        "note": (note or "")[:200],
        "created_at": _now(),
    }
    if meta:
        deck.update({k: v for k, v in meta.items() if v not in (None, "")})
    _state["decks"].append(deck)
    _dirty = True
    save(force=True)
    return deck


def replace_images(deck_id: str, images: list[bytes]) -> int:
    """把一套卡组的图整组换掉（抓取补图用），返回存了几张。"""
    _load()
    deck = next((d for d in _state["decks"] if d.get("id") == deck_id), None)
    if deck is None:
        raise DeckError("没有这套卡组")
    shots = [i for i in (images or []) if i][:MAX_IMAGES]
    if not shots:
        raise DeckError("没图，没法换")
    old = _deck_images(deck)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for idx, shot in enumerate(shots, start=1):
        path = _image_path(deck_id, idx)
        path.write_bytes(_prepare_image(shot))
        saved.append(f"images/{path.name}")
    for rel in old:
        if rel not in saved:
            try:
                (DATA_DIR / rel).unlink(missing_ok=True)
            except OSError:
                pass
    deck["image"] = saved[0]
    deck["images"] = saved
    deck["sha256"] = hashlib.sha256(b"\x00".join(shots)).hexdigest()
    save(force=True)
    return len(saved)


def remove_deck(deck_id: str, by_uin: str | None = None, is_dev: bool = False) -> bool:
    global _dirty
    _load()
    for i, deck in enumerate(_state["decks"]):
        if deck.get("id") != deck_id:
            continue
        author = str((deck.get("author") or {}).get("uin") or "")
        if not is_dev and by_uin != author:
            raise DeckError("只能删自己投的")
        _state["decks"].pop(i)
        _dirty = True
        save(force=True)
        for rel in _deck_images(deck):
            try:
                (DATA_DIR / rel).unlink(missing_ok=True)
            except OSError:
                pass
        return True
    return False


def stats() -> dict:
    _load()
    out: dict = {"total": len(_state["decks"]), "by_cls": {}, "by_source": {"submit": 0, "scrape": 0}}
    for deck in _state["decks"]:
        out["by_cls"][deck.get("cls")] = out["by_cls"].get(deck.get("cls"), 0) + 1
        src = deck.get("source") or "submit"
        out["by_source"][src] = out["by_source"].get(src, 0) + 1
    return out


def _deck_files(deck: dict) -> list:
    return [DATA_DIR / rel for rel in _deck_images(deck) if (DATA_DIR / rel).is_file()]


async def send_image(bot, event, deck: dict) -> bool:
    """把这套卡组的图发出去：多张就打包成一条「聊天记录」，不刷屏。"""
    files = _deck_files(deck)
    if not files:
        return False
    if len(files) > 1:
        try:
            if await _send_forward(bot, event, deck, files):
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"szb: 合并转发没成（{type(e).__name__}: {e}），改逐张发")
    return await _send_one_by_one(bot, event, files)


async def _send_forward(bot, event, deck: dict, files: list) -> bool:
    from nonebot_plugin_alconna import UniMessage
    from nonebot_plugin_alconna.uniseg import CustomNode, Image, Reference, Target, Text

    src = {"scrape": "抓取", "submit": "投稿"}.get(str(deck.get("source") or ""), str(deck.get("source") or ""))
    head = f"{deck_label(deck)}（{deck.get('cls')}·{deck.get('env')}，{src}）"
    nodes = [CustomNode(uid=str(bot.self_id), name="卡组", content=UniMessage([Text(head)]))]
    for path in files:
        nodes.append(
            CustomNode(uid=str(bot.self_id), name="卡组", content=UniMessage([Image(path=path.resolve())]))
        )
    group_id = getattr(event, "group_id", None)
    target = Target(id=str(group_id or event.get_user_id()), private=group_id is None, self_id=str(bot.self_id))
    await UniMessage(Reference(nodes=nodes)).send(target=target, bot=bot)
    return True


async def _send_one_by_one(bot, event, files: list) -> bool:
    import base64

    from nonebot.adapters.onebot.v11 import MessageSegment

    sent = False
    for path in files:
        try:
            await bot.send(event, MessageSegment.image(path.resolve().as_uri()))
            sent = True
            continue
        except Exception:  # noqa: BLE001
            pass
        try:
            data = base64.b64encode(path.read_bytes()).decode()
            await bot.send(event, MessageSegment.image(f"base64://{data}"))
            sent = True
        except Exception:  # noqa: BLE001
            continue
    return sent
