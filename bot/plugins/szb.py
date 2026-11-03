"""影之诗卡组：`/szb` 查询 + 投稿。

    /szb 12                   按序号查（序号就是卡组名前那个数字）
    /szb 查询 皇家             皇家·指定
    /szb 查询 皇家 无限
    /szb 查询 指定             指定环境所有职业
    /szb 查询 中速梦           按原来的说法查（别名），命中一套直接发图
    /szb 投稿 皇家 中速        投一套（环境可省，默认指定；名字可省，自动编号）

卡组数据在 `bot/data/szb_decks/decks.json`，由投稿和 shadowverse-wins.com 抓取写入。
投稿：先发指令再发图，或者先发图再发指令（60 秒内都算）。
"""

import re
import time

import httpx
from nonebot import on_message
from nonebot import on_command
from nonebot.adapters import Message
from nonebot.log import logger
from nonebot.params import CommandArg

from bot_guard import is_our_bot

import szb_decks

szb_cmd = on_command("szb", aliases={"SZB"}, priority=18, block=True)
# 投稿的图：谁在哪个会话里发的，60 秒内有效
szb_img = on_message(priority=19, block=False)

COOLDOWN_SEC = 3.0
_last: dict[str, float] = {}

CAPTURE_TTL = float(szb_decks.os.getenv("SZB_CAPTURE_TTL", "60"))
_IMG_TTL = 120.0
# (会话, QQ) -> {"cls","env","name","ts"}
_pending: dict[tuple[str, str], dict] = {}
# (会话, QQ) -> (ts, [bytes, ...])
_images: dict[tuple[str, str], tuple[float, list[bytes]]] = {}

USAGE = (
    "用法：\n"
    "/szb 12 —— 按序号看图（序号就是列表前面的数字）\n"
    "/szb 查询 皇家 —— 皇家·指定有哪些卡组\n"
    "/szb 查询 皇家 无限 —— 换环境\n"
    "/szb 查询 指定 —— 这个环境所有职业\n"
    "/szb 查询 中速梦 —— 按名字找，有就发图\n"
    "/szb 投稿 皇家 中速 —— 投稿，发完指令把卡组图发我"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MAX_IMAGE_BYTES = int(szb_decks.MAX_IMAGE_MB * 1024 * 1024)


def _session_key(event) -> str:
    if getattr(event, "message_type", "") == "group":
        return f"group_{event.group_id}"
    return f"private_{event.get_user_id()}"


def _who(event) -> str:
    return str(event.get_user_id())


def _tag(deck: dict) -> str:
    return "投稿" if deck.get("source") == "submit" else "抓取"


def _line(deck: dict) -> str:
    return f"- {szb_decks.deck_label(deck)}（{_tag(deck)}）"


async def _send_one(bot, event, deck: dict) -> None:
    """命中一套：先文字、再图（图发不出去就只留文字）。"""
    shots = len(szb_decks._deck_images(deck))
    text = f"{szb_decks.deck_label(deck)}（{deck.get('cls')}·{deck.get('env')}，{_tag(deck)}）——图给你"
    if shots > 1:
        text += f"（{shots} 张，见下面的消息记录）"
    # 多张图会打包成一条合并转发，文字只放在记录里那份就够，不再单独刷一条
    if shots <= 1:
        await szb_cmd.send(text)
    try:
        sent = await szb_decks.send_image(bot, event, deck)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"szb: 卡组图没发出去 {type(exc).__name__}: {exc}")
        sent = False
    if not sent:
        logger.warning(f"szb: 卡组图缺失 {deck.get('id')} {deck.get('image')}")
    await szb_cmd.finish()


def _list_block(decks: list[dict], head: str, extra: str = "", hint: str = "") -> str:
    lines = [head]
    if hint:
        lines.append(hint)
    lines.extend(_line(d) for d in decks)
    if extra:
        lines.append(extra)
    if len(decks) > 1:
        lines.append("要看图：/szb " + str(szb_decks.deck_num(decks[0])))
    return "\n".join(lines)


def _usage_text(event) -> str:
    if getattr(event, "message_type", "") == "group":
        return USAGE
    return USAGE


async def _download_images(event) -> list[bytes]:
    """把这条消息里的图都下下来（最多 SZB_MAX_IMAGES 张，单张 ≤10MB）。"""
    urls = []
    for seg in event.get_message():
        if seg.type != "image":
            continue
        data = seg.data or {}
        url = data.get("url") or data.get("file") or ""
        if url.startswith("http"):
            urls.append(url)
    if not urls:
        return []
    out: list[bytes] = []
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": _UA, "Referer": "https://q.qq.com/"}) as client:
        for url in urls[: szb_decks.MAX_IMAGES]:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"szb: 投稿图下载失败 {type(exc).__name__}: {exc}")
                continue
            raw = resp.content
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                continue
            out.append(raw)
    return out


def _parse_submit(text: str) -> dict:
    """`皇家 中速` → {cls, env, name}；没有职业就报错。"""
    parsed = szb_decks.parse_query(text)
    cls = parsed["cls"]
    if not cls:
        raise szb_decks.DeckError("得先说要哪个职业：皇家/妖精/超越者/梦魇/法师/主教/龙族")
    return {"cls": cls, "env": parsed["env"] or "指定", "name": parsed["name"] or ""}


async def _do_submit(bot, event, st: dict, images: list[bytes]) -> None:
    name = st.get("name") or ""
    author = {"uin": _who(event), "name": getattr(event, "sender", None) and (event.sender.card or event.sender.nickname) or ""}
    group = str(event.group_id) if getattr(event, "message_type", "") == "group" else None
    try:
        deck = szb_decks.add_deck(
            name=name,
            cls=st["cls"],
            env=st["env"],
            images=images,
            source="submit",
            author=author,
            group=group,
            note=name,
        )
    except szb_decks.DeckError as exc:
        await szb_cmd.finish(f"没收下：{exc}")
    logger.info(f"szb: 投稿 {deck['id']} {deck['name']}（{deck['cls']}·{deck['env']}）")
    await szb_cmd.finish(
        f"收好了：{szb_decks.deck_label(deck)}（{deck['cls']}·{deck['env']}，投稿）\n"
        f"看图：/szb {szb_decks.deck_num(deck)}"
    )


@szb_img.handle()
async def _on_image(event, bot):
    """有人在会话里发图：缓存起来，若他正在投稿就直接收下。"""
    if not is_our_bot(event):
        return
    if getattr(event, "message_type", "") not in ("group", "private"):
        return
    if not any(seg.type == "image" for seg in event.get_message()):
        return
    key = (_session_key(event), _who(event))
    now = time.time()
    st = _pending.get(key)
    if st and now - st["ts"] <= CAPTURE_TTL:
        images = await _download_images(event)
        if not images:
            return
        _pending.pop(key, None)
        await _do_submit(bot, event, st, images)
        return
    # 不是投稿状态，就先存着（先发图、再发指令的写法）
    images = await _download_images(event)
    if images:
        _images[key] = (now, images)
        logger.debug(f"szb: 先收了 {len(images)} 张图，等投稿指令")


@szb_cmd.handle()
async def _szb(event, bot, args: Message = CommandArg()):
    if not is_our_bot(event):
        return
    key = _session_key(event)
    now = time.time()
    if now - _last.get(key, 0.0) < COOLDOWN_SEC:
        return
    _last[key] = now

    text = args.extract_plain_text().strip()
    if not text:
        await szb_cmd.finish(USAGE)

    sub = text.split()[0]
    rest = text[len(sub):].strip()

    # 投稿：先登记，等图（或者用刚发过的图）
    if sub in ("投稿", "投"):
        try:
            st = _parse_submit(rest)
        except szb_decks.DeckError as exc:
            await szb_cmd.finish(f"{exc}\n写法：/szb 投稿 皇家 中速（环境可省，默认指定）")
        st["ts"] = now
        cache_key = (_session_key(event), _who(event))
        cached = _images.get(cache_key)
        if cached and now - cached[0] <= _IMG_TTL:
            _images.pop(cache_key, None)
            await _do_submit(bot, event, st, cached[1])
        _pending[cache_key] = st
        await szb_cmd.finish(
            f"收到，{st['cls']}·{st['env']}{('，名字「' + st['name'] + '」') if st['name'] else '，名字自动编号'}。\n"
            f"{int(CAPTURE_TTL)} 秒内把卡组图发我（可以一次发几张），发别的就算了。"
        )

    if sub in ("管理",):
        st = szb_decks.stats()
        await szb_cmd.finish(
            f"卡组库共 {st['total']} 套：投稿 {st['by_source']['submit']}，抓取 {st['by_source']['scrape']}"
        )
    if sub not in ("查询", "查", "列表", "看看", "找"):
        # 没写「查询」也当按序号/名字/职业查，顺手一点
        rest = text

    if not rest:
        await szb_cmd.finish(USAGE)

    # 纯序号：直接发那一套
    if re.fullmatch(r"#?\d{1,4}", rest):
        deck = szb_decks.find_by_num(int(rest.lstrip("#")))
        if not deck:
            await szb_cmd.finish(f"没有 {rest.lstrip('#')} 号，/szb 管理 看总数")
        await _send_one(bot, event, deck)

    parsed = szb_decks.parse_query(rest)
    cls, env, name = parsed["cls"], parsed["env"], parsed["name"]

    # 1) 只给了名字：跨职业找，命中一套就发图
    if name and not cls:
        exact = szb_decks.find_one(name)
        if exact:
            logger.info(f"szb: 发卡组 {exact['name']}（{exact['cls']}·{exact['env']}）")
            await _send_one(bot, event, exact)
        hits = szb_decks.list_decks(None, env, name, limit=szb_decks.LIST_LIMIT)
        if not hits:
            await szb_cmd.finish(f"库里没有「{name}」这套，/szb 查询 指定 看看都收了哪些")
        extra = "" if env else "要限定环境就加上「指定」或「无限」"
        await szb_cmd.finish(_list_block(hits, f"叫「{name}」的有 {len(hits)} 套：", extra))

    # 2) 只给了环境：按职业分组列一下
    if env and not cls:
        decks = szb_decks.list_decks(None, env, name, limit=500)
        if not decks:
            await szb_cmd.finish(f"{env}环境还没收卡组")
        by_cls: dict[str, list[dict]] = {}
        for d in decks:
            by_cls.setdefault(d["cls"], []).append(d)
        lines = [f"{env}环境共 {len(decks)} 套："]
        for c in szb_decks.CLASSES:
            group = by_cls.get(c)
            if not group:
                continue
            labels = "、".join(szb_decks.deck_label(d) for d in group[:5])
            more = f" 等 {len(group)} 套" if len(group) > 5 else ""
            lines.append(f"{c}（{len(group)}）：{labels}{more}")
        lines.append("看图：/szb 查询 皇家 指定")
        await szb_cmd.finish("\n".join(lines))

    # 3) 职业（+环境）：列出来
    if cls:
        target_env = env or "指定"
        decks = szb_decks.list_decks(cls, target_env, name, limit=500)
        fallback = ""
        if not decks and name:
            # 说了名字但库里没有：别只说没有再，把该职业现有的摆出来
            decks = szb_decks.list_decks(cls, target_env, None, limit=500)
            fallback = f"库里没有叫「{name}」的，"
        if not decks:
            tip = f"要不要看看{('无限' if target_env == '指定' else '指定')}环境：/szb 查询 {cls} "
            tip += "无限" if target_env == "指定" else "指定"
            await szb_cmd.finish(f"{cls}·{target_env} 还一套都没收。{tip}")
        if name:
            exact = szb_decks.find_one(name, target_env, cls)
            if exact:
                await _send_one(bot, event, exact)
        shown = decks[: szb_decks.LIST_LIMIT]
        extra = ""
        if len(decks) > len(shown):
            extra = f"还有 {len(decks) - len(shown)} 套没列出来，名字再具体点"
        hint = ""
        if fallback:
            # 名字对不上时找找最像的那套（比如改名前的「中速超」→「中速梦」）
            best = szb_decks.best_match(name, None, None)
            if best and best["cls"] != cls:
                hint = f"是不是「{szb_decks.deck_label(best)}」（{best['cls']}·{best['env']}）？"
        await szb_cmd.finish(
            _list_block(shown, f"{fallback}{cls} · {target_env}（共 {len(decks)} 套）", extra, hint)
        )

    await szb_cmd.finish(USAGE)
