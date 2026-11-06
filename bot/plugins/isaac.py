"""以撒 wiki 查询：/以撒 道具名 / 角色 / 机制。

资料是 `tools/crawl_isaac_wiki.py` 抓下来的本地 wiki，不联网；查不到就直说，
把 wiki 原文发出去，不自己总结成别的说法。
"""

import time

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg

from bot_guard import is_our_bot

import isaac_wiki

isaac_cmd = on_command("以撒", aliases={"isaac", "以撒wiki"}, priority=18, block=True)

COOLDOWN_SEC = 3.0
_last: dict[str, float] = {}

USAGE = (
    "用法：/以撒 道具名，比如 /以撒 蓝蜡烛、/以撒 以撒的结合\n"
    "也可以问角色、头目、饰品、机制，资料来自以撒灰机 wiki。"
)


def _session_key(event) -> str:
    if getattr(event, "message_type", "") == "group":
        return f"group_{event.group_id}"
    return f"private_{event.get_user_id()}"


def _stats_text() -> str:
    info = isaac_wiki.stats()
    if not info.get("ready"):
        return "本地还没有以撒知识库，先跑 tools/crawl_isaac_wiki.py。"
    age = isaac_wiki.age_hours()
    when = "刚抓的" if age < 1 else f"{age:.0f} 小时前抓的"
    return (
        f"本地以撒 wiki：{info['pages']} 篇 / {info['chunks']} 块，"
        f"其中 {info['embedded']} 块有向量（{when}）。"
    )


@isaac_cmd.handle()
async def _isaac(event: MessageEvent, arg: Message = CommandArg()):
    if not is_our_bot(event):
        return
    key = _session_key(event)
    now = time.time()
    if now - _last.get(key, 0.0) < COOLDOWN_SEC:
        return
    _last[key] = now

    query = arg.extract_plain_text().strip()
    if not query:
        await isaac_cmd.finish(USAGE)
    if query in ("状态", "统计"):
        await isaac_cmd.finish(_stats_text())
    if not isaac_wiki.ready():
        await isaac_cmd.finish("本地还没有以撒知识库，先让开发者跑一次抓取。")

    hits = isaac_wiki.recall(query, limit=2)
    if not hits:
        await isaac_cmd.finish(
            f"知识库里没找到「{query}」。说说道具大概叫什么、或者是什么角色/头目？"
        )
    # 名字完全对上的就不带第二条了，省得「成就/59」这种跟着刷
    if hits[0]["score"] >= 0.95:
        hits = hits[:1]
    logger.info(f"isaac: 「{query}」-> {[h['title'] for h in hits]}")
    text = isaac_wiki.format_reply(hits)
    if len(hits) >= 2 and hits[0]["score"] - hits[1]["score"] < 0.05 and hits[1]["score"] >= 0.8:
        names = "、".join(isaac_wiki.label(h) for h in hits)
        text = f"这几个都对得上：{names}。你要问哪个？\n\n" + text
    await isaac_cmd.finish(text)
