r"""影之诗卡牌资料（只读本地数据，不入库、不联网）。

数据来自 `Z:\ShadowverseWB_card_data\output\shadowverse_cards_chs.json`
（`SV_CARD_DATA` 可改），图片索引在 `output\images_index.json`（`SV_CARD_INDEX` 可改）。

人设只拿这里的一小段当参考，说得像自己知道的；查不到就说没查到，别编。
"""

from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path

DATA_FILE = Path(os.getenv("SV_CARD_DATA", r"Z:\ShadowverseWB_card_data\output\shadowverse_cards_chs.json"))
IMAGE_INDEX = Path(os.getenv("SV_CARD_INDEX", r"Z:\ShadowverseWB_card_data\output\images_index.json"))
IMAGE_ROOT = IMAGE_INDEX.parent

# class：0 中立、1 精灵（妖精）、2 皇家、3 巫师（法师）、4 龙族、5 梦魇、6 主教、7 超越者
# WB 把死灵和吸血鬼合成「梦魇」，复仇者改名「超越者」；对照卡牌 cn 名核对过：class 5 有腐臭的僵尸/夜之歌的演唱会，class 6 有圣盾祭司/修女，class 7 有组装失败/永不停火的枪手
CLASSES = {0: "中立", 1: "精灵", 2: "皇家", 3: "巫师", 4: "龙族", 5: "梦魇", 6: "主教", 7: "超越者"}
# type：1 随从、2/3 护符（3 是带吟唱的）、4 法术
TYPES = {1: "随从", 2: "护符", 3: "护符", 4: "法术"}
RARITIES = {1: "青铜", 2: "白银", 3: "黄金", 4: "传说"}

# 卡名里带这些词时，一句话里提到它多半是在说这张卡
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\u3000]+")
MAX_SKILL_CHARS = 110

_cache: dict[str, object] = {"mtime": 0.0, "cards": [], "by_id": {}, "images": {}}


def _clean(text) -> str:
    """去掉富文本标签和多余空白，太长就截。"""
    text = _TAG_RE.sub("", text or "")
    text = text.replace("\r", "").replace("<hr>", " ")
    text = _SPACE_RE.sub(" ", text).replace("\n ", "\n").strip()
    return text


def _clip(text: str, limit: int = MAX_SKILL_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，,、；;：: ") + "…"


def _image_path(card_id: str) -> str:
    images = _cache.get("images") or {}
    rel = images.get(str(card_id)) or ""
    if not rel:
        return ""
    path = IMAGE_ROOT / rel
    return str(path) if path.exists() else ""


def load(force: bool = False) -> list[dict]:
    """读数据文件；文件没变就不重读（mtime 判断）。"""
    try:
        mtime = DATA_FILE.stat().st_mtime
    except OSError:
        return _cache["cards"] if isinstance(_cache["cards"], list) else []
    cards = _cache["cards"]
    if not force and mtime == _cache["mtime"] and cards:
        return cards

    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    details = (raw.get("data") or {}).get("card_details") or {}
    set_names = (raw.get("data") or {}).get("card_set_names") or {}

    images: dict[str, str] = {}
    try:
        for item in json.loads(IMAGE_INDEX.read_text(encoding="utf-8")):
            rel = item.get("normal_file") or ""
            if rel and item.get("card_id"):
                images[str(item["card_id"])] = rel
    except (OSError, ValueError):
        images = {}

    cards = []
    by_id: dict[str, dict] = {}
    # 先把图片索引放进 cache：下面 _image_path() 要读它（以前放在最后一步，第一轮读出来全是空图）
    _cache["images"] = images
    for cid, entry in details.items():
        common = (entry or {}).get("common") or {}
        name = (common.get("name") or "").strip()
        if not name:
            continue
        card = {
            "id": str(cid),
            "name": name,
            "cost": common.get("cost", 0),
            "atk": common.get("atk", 0),
            "life": common.get("life", 0),
            "class": CLASSES.get(common.get("class"), "中立"),
            "type": TYPES.get(common.get("type"), "卡牌"),
            "rarity": RARITIES.get(common.get("rarity"), ""),
            "set": set_names.get(str(common.get("card_set_id")), ""),
            "skill": _clean(common.get("skill_text")),
            "flavour": _clean(common.get("flavour_text")),
        }
        evo = (entry or {}).get("evo") or {}
        if evo.get("skill_text"):
            card["evo_skill"] = _clean(evo.get("skill_text"))
        card["image"] = _image_path(card["id"])
        cards.append(card)
        by_id[card["id"]] = card

    # 名字长的排前面：一句话里同时出现「妖精」和「纯真的水之妖精」时，先认整名
    cards.sort(key=lambda c: len(c["name"]), reverse=True)
    _cache.update({"mtime": mtime, "cards": cards, "by_id": by_id, "images": images})
    return cards


def size() -> int:
    return len(load())


def find(query: str, limit: int = 8) -> list[dict]:
    """按名字找卡：完全一样的最先，其次是包含这个词的。"""
    query = (query or "").strip()
    if not query:
        return []
    cards = load()
    exact = [c for c in cards if c["name"] == query]
    starts = [c for c in cards if c["name"] != query and c["name"].startswith(query)]
    inner = [c for c in cards if query in c["name"] and not c["name"].startswith(query)]
    return (exact + starts + inner)[:limit]


def mention(text: str, limit: int = 2) -> list[dict]:
    """这句话里点到了哪些卡（按卡名整名匹配，长的优先，最多 limit 张）。"""
    text = text or ""
    if not text:
        return []
    hits: list[dict] = []
    for card in load():
        name = card["name"]
        if len(name) < 2 or name not in text:
            continue
        # 「妖精」是「纯真的水之妖精」的子串：已经认出整名了，短的这张就不要再算一遍
        if any(name != other["name"] and name in other["name"] for other in hits):
            continue
        hits.append(card)
        if len(hits) >= limit:
            break
    return hits


_PUNCT_RE = re.compile(r"[\s·・，,。.「」『』《》()（）\[\]【】!！?？:：;；\"'“”‘’]+")

# 打分档位：名字完全一样 > 以这个词开头 > 名字里含这个词 > 名字相似 > 效果里提到
SCORE_EXACT = 100
SCORE_PREFIX = 86
SCORE_INNER = 78
SCORE_FUZZY = 55  # 再按相似度往上加
SCORE_SKILL = 40
FUZZY_MIN = 0.62  # 相似度低于这个就当没认出来，宁可问一句


def _norm(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "")).lower()


def search(query: str, limit: int = 5) -> list[tuple[float, dict, str]]:
    """模糊找卡，返回 [(分数, 卡, 命中方式)]，分数高的在前。

    命中方式：exact（名字一样）、prefix（开头）、inner（名字里含）、
    fuzzy（名字像，可能打错字）、skill（效果文本里提到）。
    """
    query = (query or "").strip()
    if not query:
        return []
    qn = _norm(query)
    if not qn:
        return []
    found: dict[str, tuple[float, dict, str]] = {}
    for card in load():
        name = card["name"]
        nn = _norm(name)
        score, why = 0.0, ""
        if nn == qn:
            score, why = SCORE_EXACT, "exact"
        elif nn.startswith(qn):
            score, why = SCORE_PREFIX, "prefix"
        elif qn in nn:
            score, why = SCORE_INNER, "inner"
        else:
            ratio = difflib.SequenceMatcher(None, qn, nn).ratio()
            if ratio >= FUZZY_MIN:
                score, why = round(SCORE_FUZZY + ratio * 30, 1), "fuzzy"
            elif len(qn) >= 2 and qn in _norm(card.get("skill", "")):
                score, why = SCORE_SKILL, "skill"
        if score:
            found[card["id"]] = (score, card, why)
    hits = sorted(found.values(), key=lambda x: (-x[0], len(x[1]["name"])))
    return hits[:limit]


def skill_matches(query: str, limit: int = 4) -> tuple[list[dict], int]:
    """效果文本里提到这个词的卡：关键词出现得越靠前越优先，返回 (前几张, 一共几张)。"""
    qn = _norm(query)
    if len(qn) < 2:
        return [], 0
    found: list[tuple[int, int, dict]] = []
    for card in load():
        text = _norm(card.get("skill", "")) + "\n" + _norm(card.get("evo_skill", ""))
        pos = text.find(qn)
        if pos >= 0:
            found.append((pos, len(text), card))
    found.sort(key=lambda t: (t[0], t[1], len(t[2]["name"])))
    return [card for _, _, card in found[:limit]], len(found)


# ---- 筛选：职业 / 费用·攻击·血量 / 能力词条 ----

CLASS_ALIASES = {
    "中立": "中立",
    "皇": "皇家", "皇家": "皇家", "皇家的": "皇家",
    "精灵": "精灵", "妖精": "精灵", "妖": "精灵",
    "法师": "巫师", "巫师": "巫师", "法": "巫师",
    "龙": "龙族", "龙族": "龙族", "跳费龙": "龙族",
    "梦魇": "梦魇", "死灵": "梦魇", "死": "梦魇", "吸血鬼": "梦魇", "鬼": "梦魇",
    "主教": "主教", "教": "主教",
    "超越者": "超越者", "复仇者": "超越者", "仇": "超越者", "超": "超越者",
}

# 能力词表：用来认「疾驰守护」这种连写，也用来判断一个词是卡名还是效果词
ABILITY_WORDS = (
    "疾驰", "守护", "突进", "必杀", "虹吸", "速攻", "潜行", "入场曲", "谢幕曲", "进化时",
    "攻击时", "交战时", "回合结束时", "自己的回合中", "无法攻击", "无法被攻击", "受到伤害",
    "回复", "抽卡", "破坏", "消失", "连击", "觉醒", "奥义", "解放", "狂乱", "财宝", "共鸣",
    "反击", "土之秘术", "魔力增幅", "融合", "激奏", "结晶", "瞬念", "主战者", "减伤", "护盾",
    "无法指定", "变身", "召唤", "费用", "手牌", "牌堆", "墓场", "随机",
)

_COST_RE = re.compile(r"^(\d+)\s*(?:费|c|C)?$")
_STAT_RE = re.compile(r"^(\d+)(?:[/／](\d*))?(?:[/／](\d*))?$")


def _stat_parts(token: str) -> tuple[int | None, int | None, int | None] | None:
    """把 `5`、`5/4`、`5/4/4`、`5／4／4` 拆成 (费用, 攻击, 血量)，没写的算 None。"""
    tok = token.replace("／", "/")
    if "/" not in tok:
        m = _COST_RE.match(tok)
        if not m:
            return None
        return int(m.group(1)), None, None
    parts = tok.split("/")
    if len(parts) > 3 or not any(parts):
        return None
    out: list[int | None] = []
    for part in parts:
        if part == "":
            out.append(None)
        elif part.isdigit():
            out.append(int(part))
        else:
            return None
    while len(out) < 3:
        out.append(None)
    return out[0], out[1], out[2]


def _looks_like_ability(token: str) -> bool:
    return any(word in token for word in ABILITY_WORDS)


def parse_filters(text: str) -> dict:
    """把 `/卡 皇 5/4/4 疾驰` 拆成 {cls, cost, atk, life, abilities, names}。

    认不出类别的词先当卡名；只有一个词、又不含能力词时一定是卡名。
    """
    spec = {"cls": [], "cost": None, "atk": None, "life": None, "abilities": [], "names": []}
    rest: list[str] = []
    for token in re.split(r"\s+", (text or "").strip()):
        if not token:
            continue
        cls = CLASS_ALIASES.get(token)
        if cls:
            if cls not in spec["cls"]:
                spec["cls"].append(cls)
            continue
        stats = _stat_parts(token)
        if stats:
            cost, atk, life = stats
            if cost is not None:
                spec["cost"] = cost
            if atk is not None:
                spec["atk"] = atk
            if life is not None:
                spec["life"] = life
            continue
        rest.append(token)

    if rest:
        if len(rest) == 1 and not _looks_like_ability(rest[0]):
            spec["names"] = rest
        else:
            spec["abilities"] = rest
    return spec


def has_filters(spec: dict) -> bool:
    return bool(
        spec.get("cls")
        or spec.get("abilities")
        or spec.get("cost") is not None
        or spec.get("atk") is not None
        or spec.get("life") is not None
    )


def describe_filters(spec: dict) -> str:
    parts: list[str] = list(spec.get("cls") or [])
    if spec.get("cost") is not None:
        parts.append(f"{spec['cost']}费")
    if spec.get("atk") is not None or spec.get("life") is not None:
        atk = "" if spec.get("atk") is None else str(spec["atk"])
        life = "" if spec.get("life") is None else str(spec["life"])
        parts.append(f"{atk}/{life}")
    if spec.get("abilities"):
        parts.append("+".join(spec["abilities"]))
    if spec.get("names"):
        parts.append("「" + " ".join(spec["names"]) + "」")
    return " ".join(parts) if parts else "全部"


def _ability_hit(text: str, token: str) -> bool:
    """效果文本里有没有这个词；「疾驰守护」这种连写拆成能力词，每段都要在文本里。"""
    want = _norm(token)
    if not want:
        return False
    if want in text:
        return True
    remain = want
    matched: list[str] = []
    for word in sorted(ABILITY_WORDS, key=len, reverse=True):
        wn = _norm(word)
        if wn and wn in remain:
            remain = remain.replace(wn, "", 1)
            matched.append(wn)
    if not matched or remain:
        return False
    return all(wn in text for wn in matched)


def filter_cards(spec: dict, limit: int = 4) -> tuple[list[dict], int]:
    """按条件筛卡：职业/身材是硬条件，能力词命中越多排越前。返回 (前几张, 总共几张)。"""
    picked: list[tuple[int, int, dict]] = []
    for card in load():
        if spec.get("cls") and card["class"] not in spec["cls"]:
            continue
        for key in ("cost", "atk", "life"):
            if spec.get(key) is not None and card.get(key) != spec[key]:
                break
        else:
            text = _norm(card.get("skill", "")) + "\n" + _norm(card.get("evo_skill", ""))
            hits = sum(1 for token in spec.get("abilities") or [] if _ability_hit(text, token))
            if spec.get("abilities") and hits == 0:
                continue
            name_hit = 0
            if spec.get("names"):
                q = _norm(" ".join(spec["names"]))
                nn = _norm(card["name"])
                if not q or q not in nn:
                    continue
                name_hit = 1
            picked.append((hits, name_hit, card))
    picked.sort(key=lambda t: (-t[0], -t[1], t[2].get("cost", 0), t[2]["name"]))
    return [card for _, _, card in picked[:limit]], len(picked)

def detail(card: dict, skill_chars: int = 200) -> str:
    """查卡时发的那段：身材、职业、能力、进化后都写全，能力不截太狠。"""
    stats = f"{card['cost']}费 {card['atk']}/{card['life']}"
    kind = f"{card['class']}·{card['type']}"
    if card.get("rarity"):
        kind += f"·{card['rarity']}"
    head = f"{card['name']}（{stats}，{kind}"
    if card.get("set"):
        head += f"，{card['set']}"
    head += "）"
    lines = [head]
    skill = _clean(card.get("skill", ""))
    lines.append(f"能力：{_clip(skill, skill_chars)}" if skill else "能力：无")
    evo = _clean(card.get("evo_skill", ""))
    if evo and evo != skill:
        lines.append(f"进化后：{_clip(evo, skill_chars)}")
    return "\n".join(lines)


def brief(card: dict) -> str:
    """一条卡牌简介（聊天里看的那种）。"""
    stats = f"{card['cost']}费 {card['atk']}/{card['life']}"
    kind = f"{card['class']}·{card['type']}"
    if card.get("rarity"):
        kind += f"·{card['rarity']}"
    line = f"{card['name']}（{stats}，{kind}）"
    skill = _clip(card.get("skill", ""))
    if skill:
        line += f"\n{skill}"
    if card.get("evo_skill"):
        evo = _clip(card["evo_skill"], 70)
        if evo and evo != skill:
            line += f"\n进化后：{evo}"
    return line


def for_prompt(cards: list[dict]) -> str:
    """给模型的参考资料：只给要紧的字段，别把整段风味文本塞进去。"""
    lines = []
    for card in cards[:2]:
        stats = f"{card['cost']}费 {card['atk']}/{card['life']}"
        kind = f"{card['class']}·{card['type']}"
        if card.get("rarity"):
            kind += f"·{card['rarity']}"
        line = f"「{card['name']}」{stats}，{kind}"
        if card.get("set"):
            line += f"，{card['set']}"
        skill = _clip(card.get("skill", ""), 90)
        if skill:
            line += f"；能力：{skill}"
        lines.append(line)
    return "\n".join(lines)
