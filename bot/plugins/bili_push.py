"""B 站推送的样子（改 Bison 的 B 站平台解析）。

- 视频、直播：一条消息发完，标题 + 封面 + 链接，简介只留一小段；
- 其它动态拆成几条的（文字 + 好几张图），由 `bison_use_pic_merge=2`（bot/bot.py）合并转发成一条；
- 发的时候 saa 说「没有号能发到这」（新进的群、刚加的好友不在它的缓存里）就刷新一次再发，不然这条就丢了。
"""

from nonebot.log import logger

from persona_rules import compact_desc

try:
    import nonebot_bison.send as bison_send
    from nonebot_bison.platform.bilibili.platforms import Bilibili, Bilibililive
    from nonebot_plugin_saa.auto_select_bot import refresh_bots
    from nonebot_plugin_saa.utils import NoBotFound
except Exception as exc:  # noqa: BLE001
    Bilibili = Bilibililive = None
    logger.warning(f"bili_push: Bison 不可用，推送样式不改（{type(exc).__name__}: {exc}）")

VIDEO_CAT, LIVE_DYN_CAT = 3, 6  # Bison B 站动态类别：视频、直播动态


def _compact(post, tag: str) -> None:
    """压成一条：标题前标上是什么，只留第一张图（封面），简介截短。"""
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
