"""B 站推送的样子（改 Bison 的 B 站平台解析与发送）。

- 视频、直播：一条消息发完，标题 + 封面 + 链接，简介只留一小段；
- 其它动态拆成几条的（文字 + 好几张图），由 `bison_use_pic_merge=2`（bot/bot.py）合并转发成一条；
- 每条动态先发一条通知（【UP】更新了新动态！+ 传送门 + 直接截 B 站原动态的截图），再发那条合并转发，一共两条；
- 发的时候 saa 说「没有号能发到这」（新进的群、刚加的好友不在它的缓存里）就刷新一次再发，不然这条就丢了。
"""

import asyncio
import base64
import html
import time

import httpx
from nonebot.log import logger

from persona_rules import bili_notice, bili_shot_url, compact_desc

try:
    import nonebot_bison.send as bison_send
    from nonebot_bison.platform.bilibili.platforms import Bilibili, Bilibililive
    from nonebot_bison.post.abstract_post import AbstractPost
    from nonebot_plugin_htmlrender import get_render_context, html_to_pic
    from nonebot_plugin_saa import Image as SaaImage
    from nonebot_plugin_saa import MessageFactory
    from nonebot_plugin_saa.auto_select_bot import refresh_bots
    from nonebot_plugin_saa.utils import NoBotFound
except Exception as exc:  # noqa: BLE001
    Bilibili = Bilibililive = None
    logger.warning(f"bili_push: Bison 不可用，推送样式不改（{type(exc).__name__}: {exc}）")

VIDEO_CAT, LIVE_DYN_CAT = 3, 6  # Bison B 站动态类别：视频、直播动态

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


async def _data_uri(client: httpx.AsyncClient, url) -> str:
    """把图片下回来转成 data URI，卡片截图里直接内嵌（chromium 拿不到带 Referer 的图）。"""
    if not isinstance(url, str) or not url.startswith("http"):
        return ""
    try:
        resp = await client.get(url, headers={"User-Agent": _UA, "Referer": "https://www.bilibili.com/"})
        if resp.status_code != 200 or not resp.content:
            return ""
        ctype = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        if not ctype.startswith("image/"):
            ctype = "image/jpeg"
        return f"data:{ctype};base64,{base64.b64encode(resp.content).decode()}"
    except Exception:  # noqa: BLE001
        return ""


def _ago(ts) -> str:
    if not ts:
        return ""
    minutes = max(0.0, (time.time() - float(ts)) / 60)
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{int(minutes)} 分钟前"
    if minutes < 1440:
        return f"{int(minutes // 60)} 小时前"
    return f"{int(minutes // 1440)} 天前"


_SHOT_CSS = """
.bili-header, .bili-header__bar, .header-channel, .bili-header__banner,
.bili-dyn-detail__header, .right-container, .bili-dyn-detail__bottom { display: none !important; }
html, body { background: #fff !important; }
"""

# 动态页（t.bilibili.com）和跳转过去的 opus 页，那条动态的外框各叫这几个名字
_SHOT_SELECTOR = ".bili-dyn-item, .bili-opus-view, .opus-detail"
_shot_lock = asyncio.Lock()
# 同一条动态订了几个群就会生成几次消息，截过的按链接留 10 分钟
_CARD_TTL = 600
_card_cache: dict[str, tuple[float, bytes | None]] = {}


async def _shot_card(url: str) -> bytes | None:
    """直接截 B 站动态页里那条动态，省得本地拼版；浏览器用 htmlrender 共享的那个（断了它会重开）。"""
    async with _shot_lock:
        async with get_render_context(
            viewport={"width": 900, "height": 1200}, device_scale_factor=1.5, user_agent=_UA
        ) as page:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_selector(_SHOT_SELECTOR, timeout=15000)
            await page.add_style_tag(content=_SHOT_CSS)
            await page.wait_for_timeout(400)
            el = await page.query_selector(_SHOT_SELECTOR)
            if el is None:
                return None
            await el.scroll_into_view_if_needed()
            await page.wait_for_timeout(200)
            return await el.screenshot(type="png")


async def _card_image(post) -> bytes | None:
    """优先截 B 站上的原动态；截不到再退回本地画一张。只有要发通知条的动态才有 _card_url。"""
    url = getattr(post, "_card_url", "")
    if not url:
        return None
    now = time.time()
    for key in [k for k, (ts, _) in _card_cache.items() if now - ts > _CARD_TTL]:
        _card_cache.pop(key, None)
    if url in _card_cache:
        return _card_cache[url][1]
    try:
        card = await asyncio.wait_for(_shot_card(url), timeout=35)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"bili_push: 原页截图没成，改用本地画卡（{type(exc).__name__}: {exc}）")
        card = None
    if not card:
        card = await _drawn_card(post)
    _card_cache[url] = (now, card)
    return card


async def _drawn_card(post) -> bytes | None:
    """本地画卡片（截图失败的兜底）：头像 + 昵称 + 时间、正文、配图、来源。"""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        avatar = await _data_uri(client, getattr(post, "avatar", None))
        pics = []
        for url in list(getattr(post, "images", None) or [])[:4]:
            uri = await _data_uri(client, url)
            if uri:
                pics.append(uri)

    name = html.escape(getattr(post, "nickname", None) or "B站 UP主")
    body = html.escape((getattr(post, "content", None) or "").strip())
    title = html.escape((getattr(post, "title", None) or "").strip())
    repost = getattr(post, "repost", None)
    repost_html = ""
    if repost is not None:
        repost_html = (
            '<div class="repost">//@'
            f'{html.escape(getattr(repost, "nickname", None) or "")}：'
            f'{html.escape((getattr(repost, "content", None) or "")[:160])}</div>'
        )

    avatar_html = (
        f'<img class="avatar" src="{avatar}">'
        if avatar
        else f'<div class="avatar">{html.escape(name[:1])}</div>'
    )
    pics_html = "".join(f'<img class="pic" src="{uri}">' for uri in pics)

    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ box-sizing: border-box; margin: 0; padding: 0; }}
      body {{ width: 500px; padding: 18px 18px 12px; background: #fff;
              font-family: "Microsoft YaHei", "Segoe UI", sans-serif; color: #222; }}
      .head {{ display: flex; align-items: center; gap: 10px; }}
      .avatar {{ width: 40px; height: 40px; border-radius: 50%; object-fit: cover;
                 background: #ff6699; color: #fff; font-size: 20px; line-height: 40px; text-align: center; }}
      .who {{ display: flex; flex-direction: column; }}
      .name {{ font-size: 15px; font-weight: 600; }}
      .meta {{ font-size: 12px; color: #999; margin-top: 2px; }}
      .title {{ font-size: 15px; font-weight: 600; margin-top: 12px; }}
      .text {{ font-size: 14px; line-height: 1.7; margin-top: 10px; white-space: pre-wrap;
               word-break: break-word; }}
      .pic {{ display: block; width: 100%; max-height: 420px; object-fit: cover; border-radius: 8px; margin-top: 10px; }}
      .repost {{ font-size: 13px; color: #666; line-height: 1.6; margin-top: 10px;
                 padding: 8px 10px; background: #f5f5f5; border-radius: 8px;
                 white-space: pre-wrap; word-break: break-word; }}
      .foot {{ font-size: 12px; color: #aaa; margin-top: 14px; }}
    </style></head><body>
      <div class="head">{avatar_html}
        <div class="who"><div class="name">{name}</div>
          <div class="meta">{_ago(getattr(post, "timestamp", None))} · 动态</div></div>
      </div>
      {f'<div class="title">{title}</div>' if title else ''}
      {f'<div class="text">{body}</div>' if body else ''}
      {pics_html}
      {repost_html}
      <div class="foot">来自 B 站 · 酱油鱼推送</div>
    </body></html>"""

    return await html_to_pic(page, viewport={"width": 500, "height": 300})


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
            else:
                post._card_url = bili_shot_url(getattr(raw_post, "id_str", None)) or (post.url or "")
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

    _send_msgs_dispatch = bison_send._send_msgs_dispatch
    _send_msgs = bison_send.send_msgs

    def _notice_of(msgs) -> str:
        """从 Bison 拼好的消息里抠出文字段，交给 bili_notice 拼通知（只有图文这种多条消息才发）。"""
        texts = [getattr(seg, "data", {}).get("text") or "" for msg in msgs for seg in msg]
        return bili_notice(texts)

    _cards: list[bytes | None] = []

    _gen_messages = AbstractPost.generate_messages

    async def _gen_with_card(self):
        """生成消息的同时，把这条动态画成卡片图，留给通知条用。"""
        msgs = await _gen_messages(self)
        card = None
        try:
            card = await _card_image(self)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"bili_push: 卡片没画出来（{type(exc).__name__}: {exc}）")
        _cards.append(card)
        return msgs

    AbstractPost.generate_messages = _gen_with_card

    async def _send_msgs_with_notice(send_target, msgs):
        """先发通知（文字 + 整条动态的卡片图）、再发合并转发，一共两条；视频、直播本来就一条，不动。"""
        card = _cards.pop(0) if _cards else None
        notice = _notice_of(msgs)
        if notice and len(msgs) > 1:
            first = MessageFactory([notice, SaaImage(card)]) if card else MessageFactory(notice)
            await _send_msgs_dispatch(send_target, first)
        await _send_msgs(send_target, msgs)

    bison_send.send_msgs = _send_msgs_with_notice

    # scheduler 里是 `from ...send import send_msgs` 绑定的名字，得直接改那个模块
    try:
        from nonebot_bison.scheduler import scheduler as bison_scheduler

        bison_scheduler.send_msgs = _send_msgs_with_notice
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"bili_push: 通知条没接上（{type(exc).__name__}: {exc}）")
