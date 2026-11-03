"""开发者的记忆指令，都走事件记忆（bot/episodes.py）。

只留两个指令（她平时自己会记、自己会想起，指令只管开发者要插手的时候）：

- /记 <内容>      记一条笔记（署名是写的那位），任何会话跟她说话、聊到相关的事都能想起来
- /记忆 [关键词]  不带关键词：各类记了多少条 + 她自己的（日常、态度、答应别人的），后台数据，只在全是开发者的对话里能看，
                  她先用人设说两句；带关键词：搜本会话记着的事（群里是本群的事，私聊是关于你的）和笔记。群友的事谁都不能翻

都只给开发者（bot/devs.py）用；删某个人的记忆用 /小本本 删除。
"""

from __future__ import annotations
from bot_guard import is_our_bot

import asyncio
import os
import time

import backstage
import devs
import episodes
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg
from persona_rules import EPISODE_NOTE_CHARS, fuzzy_when

BOT_UIN = os.getenv("BOT_UIN", "").strip()
COOLDOWN = float(os.getenv("MEMORY_COOLDOWN", "3"))
KIND_NAMES = {
    "person": "关于某人", "group": "群里的事", "self": "她自己的", "followup": "待跟进", "grudge": "记仇", "note": "笔记",
}

_last_used: dict[str, float] = {}

remember_cmd = on_command("记", aliases={"remember", "记住"}, priority=17, block=True)
status_cmd = on_command("记忆", aliases={"memory", "回忆"}, priority=17, block=True)


def _guard(bot: Bot, event: MessageEvent) -> bool:
    if BOT_UIN and str(getattr(event, "self_id", "")) != BOT_UIN:
        return False
    if not devs.is_dev(event.get_user_id()):
        return False
    key = str(event.get_session_id())
    now = time.time()
    if now - _last_used.get(key, 0) < COOLDOWN:
        return False
    _last_used[key] = now
    return True


@remember_cmd.handle()
async def _remember(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event) or not _guard(bot, event):
        return
    text = " ".join(arg.extract_plain_text().split())
    if not text:
        await bot.send(event, "要记什么？用法：/记 今天多吃了一根棒棒糖")
        return
    text = text[:EPISODE_NOTE_CHARS]
    try:
        vec = (await asyncio.to_thread(episodes.embed, [text]))[0]
        episodes.add("note", text, imp=4, vec=vec, who=devs.dev_name(event.get_user_id()))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"memory: 记笔记失败 {type(exc).__name__}: {exc}")
        await bot.send(event, f"没记进去：{exc}")
        return
    await bot.send(event, "记下了")


async def _search(bot: Bot, event: MessageEvent, keyword: str) -> None:
    # 只翻本会话：群里是本群的事，私聊是关于你自己的，别人的事不给翻
    gid = str(getattr(event, "group_id", "") or "")
    hits = await asyncio.to_thread(episodes.search, keyword, event.get_user_id(), gid)
    if not hits:
        await bot.send(event, f"记忆里没有「{keyword}」")
        return
    now = time.time()
    lines = [f"{fuzzy_when(now - h['t'])} · {h['text']}" for h in hits]
    await bot.send(event, "想起这些：\n" + "\n".join(lines))


@status_cmd.handle()
async def _status(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event) or not _guard(bot, event):
        return
    keyword = arg.extract_plain_text().strip()
    if keyword:
        await _search(bot, event, keyword)
        return
    if not await backstage.devs_only(bot, event):
        return
    counts = await asyncio.to_thread(episodes.stats)
    mine = await asyncio.to_thread(episodes.own)
    now = time.time()
    lines = ["各类记了多少：" + ("、".join(f"{KIND_NAMES.get(k, k)} {n}" for k, n in counts.items()) or "还没记过")]
    if mine:
        lines.append("她自己的（日常、态度、答应别人的）：")
        lines += [f"· {fuzzy_when(now - m['t'])}：{m['text']}" for m in mine]
    await backstage.present(bot, event, "记忆", "\n".join(lines))
