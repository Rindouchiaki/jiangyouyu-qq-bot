"""游戏查询：/hsr（星穹铁道）、/zzz（绝区零）。

数据在本地缓存（game-data/index.json），默认 24 小时过期后自动重抓，
抓取失败继续用旧数据，不影响查询。角色查询不需要 Cookie；体力/便笺要 MYS_COOKIE，仅 DEV_UIN 可用。
"""

from __future__ import annotations
from bot_guard import is_our_bot

import asyncio
import os
import random
import time

import game_data
import mys
from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.params import CommandArg

BOT_UIN = os.getenv("BOT_UIN", "").strip()
DEV_UIN = os.getenv("DEV_UIN", "").strip()
COOLDOWN = float(os.getenv("GAME_QUERY_COOLDOWN", "3"))
CHECK_INTERVAL = int(os.getenv("GAME_DATA_CHECK_INTERVAL", "3600"))
MAX_LIST = 8

_data: dict = {}
_last_used: dict[str, float] = {}
_refresh_task: asyncio.Task | None = None

hsr_cmd = on_command("hsr", priority=18, block=True)
zzz_cmd = on_command("zzz", priority=18, block=True)


def _reload() -> None:
    global _data
    _data = game_data.load_index()
    if _data:
        logger.info(
            "game_query: 载入 HSR %d / ZZZ %d"
            % (len(_data.get("hsr", {}).get("items", [])), len(_data.get("zzz", {}).get("items", [])))
        )


def _items(game: str) -> list[dict]:
    return _data.get(game, {}).get("items", [])


def _search(game: str, keyword: str) -> list[dict]:
    items = _items(game)
    if not keyword:
        return items
    kw = keyword.lower()
    exact = [i for i in items if i["name"].lower() == kw or i.get("name_en", "").lower() == kw]
    if exact:
        return exact
    return [i for i in items if kw in i["name"].lower() or kw in i.get("name_en", "").lower()]


def _fmt(game: str, c: dict) -> str:
    if game == "hsr":
        return f"{c['name']}｜{c.get('rarity')}★｜{c.get('element')}·{c.get('path')}"
    return f"{c['name']}｜{c.get('rarity')}｜{c.get('element')}"


@get_driver().on_startup
async def _startup() -> None:
    global _refresh_task
    _reload()

    if game_data.is_stale():
        ok, msg = await asyncio.to_thread(game_data.ensure_fresh)
        logger.info(f"game_query: 启动刷新 -> {msg}")
        if ok:
            _reload()

    async def _loop() -> None:
        while True:
            await asyncio.sleep(CHECK_INTERVAL)
            try:
                if game_data.is_stale():
                    ok, msg = await asyncio.to_thread(game_data.ensure_fresh)
                    logger.info(f"game_query: 定时刷新 -> {msg}")
                    if ok:
                        _reload()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"game_query: 定时刷新异常 {type(exc).__name__}: {exc}")

    # 事件循环只弱引用任务，不留引用可能被回收
    _refresh_task = asyncio.create_task(_loop())


async def _handle(game: str, bot: Bot, event: MessageEvent, arg) -> None:
    if BOT_UIN and str(getattr(event, "self_id", "")) != BOT_UIN:
        return

    key = str(event.get_session_id())
    now = time.time()
    if now - _last_used.get(key, 0) < COOLDOWN:
        return

    keyword = arg.extract_plain_text().strip()
    label = "星穹铁道" if game == "hsr" else "绝区零"

    # 手动强制刷新（仅开发者）
    if keyword in ("刷新", "更新") and DEV_UIN and str(event.get_user_id()) == DEV_UIN:
        _last_used[key] = now
        ok, msg = await asyncio.to_thread(game_data.ensure_fresh, True)
        if ok:
            _reload()
        await bot.send(event, msg)
        return

    # 绑定 UID / 查体力
    tokens = keyword.split()
    action = tokens[0] if tokens else ""
    qq = str(event.get_user_id())

    if action in ("绑定", "bind"):
        _last_used[key] = now
        uid = tokens[1] if len(tokens) > 1 else ""
        if not uid.isdigit() or not (8 <= len(uid) <= 12):
            await bot.send(event, f"用法：/{game} 绑定 <你的UID>")
            return
        mys.bind(qq, game, uid)
        await bot.send(event, f"已绑定 {label} UID {uid}")
        return

    if action in ("体力", "便笺", "note"):
        _last_used[key] = now
        # Cookie 是号主自己的账号凭据：别人查会拿号主的号去请求，容易触发米游社风控
        if not DEV_UIN or qq != DEV_UIN:
            await bot.send(event, "体力查询只给号主用")
            return
        uid = mys.get_uid(qq, game)
        if not uid:
            await bot.send(event, f"还没绑定，先发 /{game} 绑定 <UID>")
            return
        if not mys.has_cookie():
            await bot.send(
                event,
                "查体力需要米游社 Cookie（未配置）。\n"
                "在浏览器登录米游社 → F12 → Network → 任意请求里的 Cookie，"
                "填到 bot\\persona.env 的 MYS_COOKIE 后重启。",
            )
            return
        try:
            if game == "hsr":
                text = await asyncio.to_thread(mys.hsr_note, uid)
            else:
                text = await asyncio.to_thread(mys.zzz_note, uid)
        except Exception as exc:  # noqa: BLE001
            await bot.send(event, f"查询失败：{exc}")
            return
        await bot.send(event, f"{label} UID {uid}：{text}")
        return

    items = _items(game)
    if not items:
        await bot.send(event, "资料还没准备好，等下再来")
        return

    if not keyword:
        sample = random.choice(items)
        await bot.send(event, f"{label}共{len(items)}个，试试 /{game} {sample['name']}\n比如：{_fmt(game, sample)}")
        _last_used[key] = now
        return

    hits = _search(game, keyword)
    if not hits:
        await bot.send(event, f"{label}里没找到「{keyword}」")
        return

    _last_used[key] = now
    if len(hits) == 1:
        c = hits[0]
        icon = await asyncio.to_thread(game_data.icon_file, game, c)
        if icon:
            await bot.send(event, MessageSegment.image(icon.resolve().as_uri()))
        await bot.send(event, _fmt(game, c))
        return

    shown = hits[:MAX_LIST]
    lines = [_fmt(game, c) for c in shown]
    more = f"（共{len(hits)}个，只说前{MAX_LIST}个）" if len(hits) > MAX_LIST else ""
    await bot.send(event, f"{label}匹配「{keyword}」{more}\n" + "\n".join(lines))


@hsr_cmd.handle()
async def _hsr(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return

    await _handle("hsr", bot, event, arg)


@zzz_cmd.handle()
async def _zzz(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return

    await _handle("zzz", bot, event, arg)




