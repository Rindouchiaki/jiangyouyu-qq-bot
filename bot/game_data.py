"""游戏数据的抓取 / 缓存 / 过期刷新。

沿用上游项目的思路：数据站是版本化的、内容不常变，客户端按天缓存，过期再拉。
- 缓存文件：game-data/index.json（含 generated_at）
- 默认 24 小时过期（GAME_DATA_TTL 可调）
- 抓取失败时继续用旧数据，不打断查询
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from nonebot.log import logger

DATA_DIR = Path(os.getenv("GAME_DATA_DIR", r"Z:\snowluma\game-data"))
INDEX_FILE = DATA_DIR / "index.json"
RAW_DIR = DATA_DIR / "raw"
TTL_SECONDS = int(os.getenv("GAME_DATA_TTL", str(24 * 60 * 60)))

HSR_ELEMENT = {
    "Physical": "物理", "Fire": "火", "Ice": "冰", "Lightning": "雷",
    "Wind": "风", "Quantum": "量子", "Imaginary": "虚数", "Thunder": "雷",
}
HSR_PATH = {
    "Warrior": "毁灭", "Rogue": "巡猎", "Mage": "智识", "Shaman": "同谐",
    "Warlock": "虚无", "Knight": "存护", "Priest": "丰饶", "Memory": "记忆",
    "Trailblaze": "开拓",
}
ZZZ_ELEMENT = {
    "Physical": "物理", "Fire": "火", "Ice": "冰", "Electric": "电",
    "Ether": "以太", "Wind": "风", "Frost": "霜", "Frostburn": "霜燃",
}

# 数据源的 zh 常是简称（雅、柳），这里补全常用全名；没有的仍用源里的 zh
ZZZ_CN = {
    "Anby": "安比", "Soldier 0 - Anby": "零号·安比", "Nekomata": "猫又",
    "Nicole": "妮可", "Soldier 11": "11号", "Corin": "可琳", "Billy": "比利",
    "Koleda": "珂蕾妲", "Ben": "本·比格", "Lycaon": "冯·莱卡恩",
    "Soukaku": "苍角", "Anton": "安东", "Rina": "丽娜", "Grace": "格莉丝",
    "Ellen": "艾莲·乔", "Zhu Yuan": "朱鸢", "Qingyi": "青衣", "Jane": "简·杜",
    "Seth": "塞斯", "Caesar": "凯撒", "Burnice": "柏妮思", "Yanagi": "月城柳",
    "Lighter": "莱特", "Miyabi": "星见雅", "Harumasa": "浅羽悠真",
    "Trigger": "扳机", "Vivian": "薇薇安", "Hugo": "雨果", "Astra Yao": "耀嘉音",
    "Evelyn": "伊芙琳", "Pulchra": "波可娜", "Lucy": "露西", "Piper": "派派",
    "Yixuan": "仪玄", "Pan Yinhu": "潘引壶", "Ju Fufu": "橘福福",
    "Yuzuha": "柚叶", "Alice": "爱丽丝", "Seed": "席德", "Starlight - Billy": "星辉·比利",
}

SOURCES = {
    "hsr": [
        "https://gh-proxy.com/https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/index_min/cn/characters.json",
        "https://api.github.com/repos/Mar-7th/StarRailRes/contents/index_min/cn/characters.json?ref=master",
    ],
    "zzz_agents": [
        "https://gh-proxy.com/https://raw.githubusercontent.com/seriaati/ZenlessAssetScrape/main/data/agent_data.json",
    ],
}


def _download(urls: list[str], dest: Path, timeout: int = 40) -> bytes:
    """依次尝试多个镜像，成功就落盘。"""
    last: Exception | None = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 snowluma-bot"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if len(data) < 1000:
                raise ValueError(f"响应过短: {len(data)} bytes")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            logger.debug(f"game_data: {url} 失败 {type(exc).__name__}")
    raise RuntimeError(f"全部源都失败: {last}")


def _fetch_zzz_version(timeout: int = 25) -> str:
    req = urllib.request.Request(
        "https://static.nanoka.cc/manifest.json", headers={"User-Agent": "Mozilla/5.0 snowluma-bot"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        manifest = json.loads(resp.read().decode("utf-8"))
    version = manifest.get("zzz", {}).get("live")
    if not version:
        raise RuntimeError("manifest 里没有 zzz.live")
    return str(version)


def _fetch_zzz_characters(version: str, dest: Path) -> bytes:
    url = f"https://static.nanoka.cc/zzz/{version}/character.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 snowluma-bot"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


def _build(hsr_bytes: bytes, zzz_bytes: bytes, zzz_agents: bytes, zzz_version: str) -> dict:
    hsr_raw = json.loads(hsr_bytes.decode("utf-8"))
    nano = json.loads(zzz_bytes.decode("utf-8"))
    agents = json.loads(zzz_agents.decode("utf-8"))
    by_en = {a.get("name"): a for a in agents.values() if a.get("name")}

    hsr = []
    for cid, c in hsr_raw.items():
        name = c.get("name") or ""
        if not name or "{" in name:
            continue
        hsr.append({
            "id": cid,
            "name": name,
            "rarity": c.get("rarity"),
            "element": HSR_ELEMENT.get(c.get("element", ""), c.get("element")),
            "path": HSR_PATH.get(c.get("path", ""), c.get("path")),
            "icon": c.get("icon", ""),
        })
    hsr.sort(key=lambda x: (-(x.get("rarity") or 0), x["name"]))

    zzz = []
    for aid, a in nano.items():
        en = a.get("en") or ""
        if not en:
            continue
        meta = by_en.get(en, {})
        elem_en = meta.get("element", "")
        zzz.append({
            "id": aid,
            "name": ZZZ_CN.get(en) or a.get("zh") or en,
            "name_en": en,
            "rarity": "S" if (a.get("rank") or 0) >= 4 else "A",
            "element": ZZZ_ELEMENT.get(elem_en, elem_en),
            "icon": meta.get("icon_url", ""),
        })
    zzz.sort(key=lambda x: x["name_en"])

    return {
        "meta": {
            "generated_at": int(time.time()),
            "zzz_version": zzz_version,
            "sources": {
                "hsr": "Mar-7th/StarRailRes (index_min/cn)",
                "zzz": f"static.nanoka.cc/zzz/{zzz_version}",
                "zzz_meta": "seriaati/ZenlessAssetScrape",
            },
        },
        "hsr": {"count": len(hsr), "items": hsr},
        "zzz": {"count": len(zzz), "items": zzz},
    }


def is_stale(ttl: int | None = None) -> bool:
    ttl = TTL_SECONDS if ttl is None else ttl
    if not INDEX_FILE.is_file():
        return True
    try:
        meta = json.loads(INDEX_FILE.read_text(encoding="utf-8")).get("meta", {})
        generated = int(meta.get("generated_at", 0))
    except Exception:  # noqa: BLE001
        return True
    if generated <= 0:
        return True
    return (time.time() - generated) > ttl


def ensure_fresh(force: bool = False) -> tuple[bool, str]:
    """过期就重新抓取并重建索引。返回 (是否刷新, 说明)。"""
    if not force and not is_stale():
        return False, "缓存未过期"

    try:
        hsr_bytes = _download(SOURCES["hsr"], RAW_DIR / "hsr_characters.json")
        zzz_agents = _download(SOURCES["zzz_agents"], RAW_DIR / "zzz_agents.json")
        version = _fetch_zzz_version()
        zzz_bytes = _fetch_zzz_characters(version, RAW_DIR / "zzz_nanoka.json")

        index = _build(hsr_bytes, zzz_bytes, zzz_agents, version)
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INDEX_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(INDEX_FILE)

        msg = f"已更新 HSR {index['hsr']['count']} 角色 / ZZZ {index['zzz']['count']} 代理人（zzz {version}）"
        logger.info(f"game_data: {msg}")
        return True, msg
    except Exception as exc:  # noqa: BLE001
        keep = "继续用旧数据" if INDEX_FILE.is_file() else "且没有旧数据"
        logger.warning(f"game_data: 刷新失败（{type(exc).__name__}: {exc}），{keep}")
        return False, f"刷新失败：{exc}（{keep}）"


def load_index() -> dict:
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"game_data: 索引读取失败 {type(exc).__name__}: {exc}")
        return {}


ICON_DIR = DATA_DIR / "icons"
HSR_ICON_BASE = (
    "https://gh-proxy.com/https://raw.githubusercontent.com/Mar-7th/StarRailRes/master/"
)


def icon_file(game: str, item: dict) -> Path | None:
    """按需下载角色头像并缓存为 png；失败返回 None（不影响文字回复）。"""
    raw = item.get("icon") or ""
    if not raw:
        return None

    cid = str(item.get("id") or "x")
    out = ICON_DIR / f"{game}_{cid}.png"
    if out.is_file() and out.stat().st_size > 500:
        return out

    url = raw if raw.startswith("http") else HSR_ICON_BASE + raw.lstrip("/")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 snowluma-bot"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if len(data) < 200:
            raise ValueError(f"图片过短 {len(data)}")

        ICON_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import io

            from PIL import Image

            with Image.open(io.BytesIO(data)) as img:
                img.convert("RGBA").save(out, "PNG")
        except Exception:  # noqa: BLE001 - 转码失败就原样存
            out = out.with_suffix(Path(raw).suffix or ".png")
            out.write_bytes(data)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"game_data: 头像下载失败 {item.get('name')} {type(exc).__name__}: {exc}")
        return None


