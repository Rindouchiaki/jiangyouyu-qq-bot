"""B 站推送：Bison 只负责「发现有新动态」，发出去的内容交给解析插件渲染。

以前推送是「通知条 + 合并转发 + 自己画的卡片」，和群里有人贴链接时解析出来的
（卡片 + 正文配图/视频）差一截。现在直接从 Bison 的消息里抠出动态链接，交给
`nonebot_plugin_parser` 走和贴链接完全一样的 `render_messages()`：

- 图文动态：先一张卡片，再按原来的排版把配图和视频发出来；
- 视频：`plugins/parser_video_only.py` 已经把含视频的消息改成只发视频；
- 解析失败（比如直播间）再退回 Bison 原来的消息，至少不会漏推。

`bot/bot.py` 的账号守卫会丢掉机器人自己发的消息，`push_marks` 再记一下刚推过的
链接（`PUSH_LINK_TTL`），所以不会出现「推送一次、解析又一次」的套娃。
"""

import asyncio
import json
import os
import re
import time

from nonebot.log import logger

import push_marks

try:
    import nonebot_bison.send as bison_send
    from nonebot_bison.platform.bilibili.platforms import Bilibili, Bilibililive
    from nonebot_plugin_parser.config import pconfig as parser_config
    from nonebot_plugin_parser.parsers import BilibiliParser
    from nonebot_plugin_parser.renders import get_renderer
    from nonebot_plugin_saa import TargetQQGroup, TargetQQPrivate
    from nonebot_plugin_saa.auto_select_bot import refresh_bots
    from nonebot_plugin_saa.utils import NoBotFound
except Exception as exc:  # noqa: BLE001
    Bilibili = Bilibililive = None
    BilibiliParser = get_renderer = parser_config = None
    logger.warning(f"bili_push: Bison 不可用，推送样式不改（{type(exc).__name__}: {exc}）")

VIDEO_CAT, LIVE_DYN_CAT = 3, 6  # Bison B 站动态类别：视频、直播动态

_BOT_UIN = os.getenv("BOT_UIN", "").strip()

_URL_RE = re.compile(r"https?://[^\s，,。）)]+")


async def _bili_cookie_header() -> str:
    """从 Bison 那条实名 cookie 拼出 cookie 头，给解析插件用（不带就是 -352 / 412）。"""
    try:
        from nonebot_bison.config import config as bison_config

        cookies = await bison_config.get_cookie(site_name="bilibili.com", is_anonymous=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"bili_push: 取 Bison cookie 失败（{type(exc).__name__}: {exc}）")
        return ""
    for cookie in cookies:
        try:
            data = json.loads(cookie.content)
        except (TypeError, ValueError):
            continue
        if data.get("SESSDATA"):
            return "; ".join(f"{k}={v}" for k, v in data.items() if k and v)
    return ""


async def _ensure_parser_cookie() -> None:
    """解析插件没配 B 站 cookie 时，用 Bison 里那条实名 cookie 顶上，免得订阅能抓、解析抓不到。"""
    if parser_config is None or parser_config.parser_bili_ck:
        return
    header = await _bili_cookie_header()
    if header:
        parser_config.parser_bili_ck = header
        logger.info("bili_push: 解析插件用上 Bison 的 B 站 cookie")


def _texts_of(msgs) -> list[str]:
    """把 Bison 拼好的消息里的文字都抠出来（通知、正文、来源、详情）。"""
    texts: list[str] = []
    for msg in msgs:
        for seg in msg:
            data = getattr(seg, "data", None) or {}
            text = data.get("text")
            if text:
                texts.append(str(text))
    return texts


def _urls_of(msgs) -> list[str]:
    """从文字里找动态链接，保持出现顺序、去重。"""
    urls: list[str] = []
    for text in _texts_of(msgs):
        for url in _URL_RE.findall(text):
            if url not in urls:
                urls.append(url)
    return urls


def _pick_bot():
    """拿机器人号（BOT_UIN）的 Bot，推送不该从开发者自己的号发出去。"""
    import nonebot

    for bot in nonebot.get_bots().values():
        if _BOT_UIN and str(bot.self_id) != _BOT_UIN:
            continue
        return bot
    return None


async def _send_uni(send_target, uni) -> None:
    """把解析插件渲染好的一条 UniMessage 发出去——和群里贴链接时 `message.send()` 同一套。"""
    from nonebot_plugin_alconna.uniseg import Target

    bot = _pick_bot()
    if bot is None:
        raise RuntimeError("没有可用的 bot")
    if isinstance(send_target, TargetQQGroup):
        target = Target(id=str(send_target.group_id), private=False, self_id=str(bot.self_id))
    elif isinstance(send_target, TargetQQPrivate):
        target = Target(id=str(send_target.user_id), private=True, self_id=str(bot.self_id))
    else:
        raise RuntimeError(f"不认识的目标 {send_target!r}")
    await uni.send(target=target, bot=bot)


async def _send_parsed(send_target, url: str) -> bool:
    """走解析插件：search_url → parse → render_messages，跟群里贴链接一模一样。"""
    if BilibiliParser is None:
        return False
    bot = _pick_bot()
    if bot is None:
        raise RuntimeError("没有可用的 bot")
    await _ensure_parser_cookie()
    parser = BilibiliParser()
    keyword, searched = BilibiliParser.search_url(url)
    result = await parser.parse(keyword, searched)
    renderer = get_renderer(result.platform.name)(result)
    # 图集这类会走 `UniHelper.construct_forward_message`，它要读 current_bot；
    # 平时在 matcher 里有上下文，主动推送没有，这里临时放一个。
    from nonebot.matcher import current_bot

    token = current_bot.set(bot)
    sent = 0
    try:
        async for uni in renderer.render_messages():
            await _send_uni(send_target, uni)
            sent += 1
    finally:
        current_bot.reset(token)
    return sent > 0


def _compact(post, tag: str) -> None:
    """压成一条：标题前标上是什么，只留第一张图（封面），简介截短。这是兜底路径的样式。"""
    from persona_rules import compact_desc

    post.compress = True
    if post.title and not post.title.startswith("【"):
        post.title = f"【{tag}】{post.title}"
    if post.images:
        post.images = list(post.images)[:1]
    post.content = compact_desc(post.content)


if Bilibili is not None:
    _dyn_parse = Bilibili.parse
    _live_parse = Bilibililive.parse

    async def _parse_dyn(self, raw_post):
        post = await _dyn_parse(self, raw_post)
        try:
            cat = self._do_get_category(raw_post.type)
            if cat == VIDEO_CAT:
                _compact(post, "新视频")
            elif cat == LIVE_DYN_CAT:
                _compact(post, "直播")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"bili_push: 动态样式没改成（{type(exc).__name__}: {exc}）")
        return post

    async def _parse_live(self, raw_post):
        post = await _live_parse(self, raw_post)
        # Bison 下播、改标题用的是直播关键帧，统一换成封面；标题「[开播] xxx」换成「【开播】xxx」
        if getattr(raw_post, "cover", ""):
            post.images = [raw_post.cover]
        if post.title and post.title.startswith("["):
            post.title = "【" + post.title[1:].replace("] ", "】", 1)
        post.compress = True
        return post

    Bilibili.parse = _parse_dyn
    Bilibililive.parse = _parse_live

    _do_send = bison_send._do_send

    async def _send_or_refresh(send_target, msg):
        try:
            await _do_send(send_target, msg)
        except NoBotFound:
            await refresh_bots()
            await _do_send(send_target, msg)

    bison_send._do_send = _send_or_refresh

    _send_msgs = bison_send.send_msgs

    _PARSE_TIMEOUT = float(os.getenv("BILI_PUSH_TIMEOUT", "240"))

    async def _send_msgs_with_parser(send_target, msgs):
        """能解析就发解析出来的内容；解析不了（直播间、下播通知）才发 Bison 原消息。"""
        for text in _texts_of(msgs):
            if text.strip():
                push_marks.mark_text(text)
        for url in _urls_of(msgs):
            t0 = time.monotonic()
            try:
                ok = await asyncio.wait_for(_send_parsed(send_target, url), timeout=_PARSE_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"bili_push: 解析推送没成（{type(exc).__name__}: {exc}），退回 Bison 原消息")
                ok = False
            else:
                cost = time.monotonic() - t0
                logger.info(f"bili_push: 解析推送 {url} 用时 {cost:.1f}s")
            if ok:
                return
        await _send_msgs(send_target, msgs)

    bison_send.send_msgs = _send_msgs_with_parser

    # scheduler 里是 `from ...send import send_msgs` 绑定的名字，得直接改那个模块
    try:
        from nonebot_bison.scheduler import scheduler as bison_scheduler

        bison_scheduler.send_msgs = _send_msgs_with_parser
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"bili_push: 推送发送没接上（{type(exc).__name__}: {exc}）")
