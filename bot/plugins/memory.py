"""记忆小窝：把白守的本地 Markdown 日记接进聊天。

- /记 <内容>    往今天的日记追加一条
- /回忆 <关键词> 检索历史日记
- /记忆         看库状态

人设插件在问到「还记得/上次」时会自动带上最近几条记忆。
三个指令都只给开发者（DEV_UIN）用：日记里有私聊和别的群的内容。
"""

from __future__ import annotations
from bot_guard import is_our_bot

import asyncio
import os
import time

import memory
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg

BOT_UIN = os.getenv("BOT_UIN", "").strip()
DEV_UIN = os.getenv("DEV_UIN", "").strip()
DEV_NAME = os.getenv("DEV_NAME", "酱酱鱼").strip()
COOLDOWN = float(os.getenv("MEMORY_COOLDOWN", "3"))

_last_used: dict[str, float] = {}

remember_cmd = on_command("记", aliases={"remember", "记住"}, priority=17, block=True)
recall_cmd = on_command("回忆", aliases={"search", "找找"}, priority=17, block=True)
status_cmd = on_command("记忆", aliases={"memory"}, priority=17, block=True)


def _guard(bot: Bot, event: MessageEvent) -> bool:
    if BOT_UIN and str(getattr(event, "self_id", "")) != BOT_UIN:
        return False
    if not DEV_UIN or str(event.get_user_id()) != DEV_UIN:
        return False
    key = str(event.get_session_id())
    now = time.time()
    if now - _last_used.get(key, 0) < COOLDOWN:
        return False
    _last_used[key] = now
    return True


@remember_cmd.handle()
async def _remember(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return

    if not _guard(bot, event):
        return

    text = arg.extract_plain_text().strip()
    if not text:
        await bot.send(event, "要记什么？用法：/记 今天多吃了一根棒棒糖")
        return
    if not memory.available():
        await bot.send(event, f"找不到白守的库：{memory.VAULT}\n把 BAISHOU_VAULT 指到你的库目录再试")
        return

    try:
        # 署名固定为 DEV_NAME：人设插件按这个标签取开发者笔记
        path = await asyncio.to_thread(memory.remember, text, DEV_NAME)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"memory: 写入失败 {type(exc).__name__}: {exc}")
        await bot.send(event, f"没写进去：{exc}")
        return

    await bot.send(event, f"记下了（{path.name}）")


@recall_cmd.handle()
async def _recall(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return

    if not _guard(bot, event):
        return

    keyword = arg.extract_plain_text().strip()
    if not keyword:
        await bot.send(event, "要找什么？用法：/回忆 棒棒糖")
        return
    if not memory.available():
        await bot.send(event, f"找不到白守的库：{memory.VAULT}")
        return

    # 群里只翻本群和开发者笔记，私聊（只有开发者能用）不限
    tags = (f"群{event.group_id}", DEV_NAME) if getattr(event, "message_type", "") == "group" else ()
    hits = await asyncio.to_thread(memory.search, keyword, 3, tags)
    if not hits:
        await bot.send(event, f"记忆里没有「{keyword}」")
        return
    await bot.send(event, "想起这些：\n" + "\n".join(hits))


@status_cmd.handle()
async def _status(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return

    if not _guard(bot, event):
        return

    s = memory.stats()
    if not s["exists"]:
        await bot.send(event, f"记忆库还没建：{s['vault']}")
        return
    await bot.send(event, f"记忆库 {s['vault']}｜{s['files']} 篇日记｜今天 {s['today']}")


if not memory.available():
    logger.info(f"memory: 白守库还没就绪（{memory.VAULT}），指令会提示先配置")

