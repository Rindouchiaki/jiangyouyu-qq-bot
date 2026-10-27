"""米游社（mys）数据查询：绑定 UID + 查体力/便笺。

需要用户自己的 Cookie（网页版米游社 → F12 → Network → 任一请求的 Cookie 头）。
Cookie 只从环境变量读，不写进仓库：

    MYS_COOKIE=ltuid_v2=...; ltoken_v2=...; ...
    MYS_STUID=   # 可选，部分接口要

签名（DS）沿用社区通用算法：md5(salt=...&t=...&r=...&b=...&q=...)。
只做只读查询，不涉及登录态写入。
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

from nonebot.log import logger

BIND_FILE = Path(os.getenv("MYS_BIND_FILE", r"Z:\snowluma\game-data\bindings.json"))
COOKIE = os.getenv("MYS_COOKIE", "").strip()

APP_VERSION = "2.11.1"
CLIENT_TYPE = "5"
SALT = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 miHoYoBBS/2.11.1"
)

HSR_NOTE = "https://api-takumi-record.mihoyo.com/game_record/app/hkrpg/api/note"
ZZZ_NOTE = "https://api-takumi-record.mihoyo.com/game_record/app/nap/api/note"
SERVER = "prod_gf_cn"


def _ds(query: str = "", body: str = "") -> str:
    t = int(time.time())
    r = str(random.randint(100000, 200000))
    raw = f"salt={SALT}&t={t}&r={r}&b={body}&q={query}"
    return f"{t},{r},{hashlib.md5(raw.encode()).hexdigest()}"


def _get(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={
            "Cookie": COOKIE,
            "DS": _ds(query=query),
            "x-rpc-client_type": CLIENT_TYPE,
            "x-rpc-app_version": APP_VERSION,
            "User-Agent": UA,
            "Referer": "https://app.mihoyo.com",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_bindings() -> dict:
    try:
        return json.loads(BIND_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def bind(qq: str, game: str, uid: str) -> None:
    data = load_bindings()
    data.setdefault(str(qq), {})[game] = str(uid)
    BIND_FILE.parent.mkdir(parents=True, exist_ok=True)
    BIND_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_uid(qq: str, game: str) -> str | None:
    return (load_bindings().get(str(qq)) or {}).get(game)


def has_cookie() -> bool:
    return bool(COOKIE)


def hsr_note(uid: str) -> str:
    """返回一句体力概况；失败抛异常由调用方转成提示。"""
    data = _get(HSR_NOTE, {"server": SERVER, "role_id": uid})
    if data.get("retcode") != 0:
        raise RuntimeError(f"{data.get('message')}（retcode={data.get('retcode')}）")

    d = data.get("data") or {}
    cur, mx = d.get("current_stamina"), d.get("max_stamina")
    recover = int(d.get("stamina_recover_time") or 0)
    h, m = divmod(recover // 60, 60)
    parts = [f"开拓力 {cur}/{mx}"]
    if recover > 0:
        parts.append(f"{h}小时{m}分后满")
    exp = d.get("expeditions") or []
    if exp:
        parts.append(f"派遣 {len(exp)} 个")
    return "｜".join(parts)


def zzz_note(uid: str) -> str:
    """绝区零体力（接口较新，失败就当不支持）。"""
    data = _get(ZZZ_NOTE, {"server": SERVER, "role_id": uid})
    if data.get("retcode") != 0:
        raise RuntimeError(f"{data.get('message')}（retcode={data.get('retcode')}）")

    d = data.get("data") or {}
    cur, mx = d.get("energy"), d.get("max_energy")
    recover = int(d.get("energy_recover_time") or 0)
    h, m = divmod(recover // 60, 60)
    parts = [f"电量 {cur}/{mx}"]
    if recover > 0:
        parts.append(f"{h}小时{m}分后满")
    return "｜".join(parts)


logger.info(f"mys: Cookie {'已配置' if has_cookie() else '未配置（绑定可用，查询会提示缺 Cookie）'}")
