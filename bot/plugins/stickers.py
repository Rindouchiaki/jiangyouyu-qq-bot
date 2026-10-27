"""表情包插件：按标签挑一张本地表情发出去。

数据来自 tools/export_qq_emoji.py + ocr/tag 两步生成的 stickers/index.json。

用法（群里）：
    /表情            随机一张
    /表情 搞笑       按分类或标签/文字匹配
    /表情 分类       看有哪些分类
"""

from __future__ import annotations
from bot_guard import is_our_bot

import os
import time

import sticker_lib
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg

BOT_UIN = os.getenv("BOT_UIN", "").strip()
COOLDOWN = float(os.getenv("STICKER_COOLDOWN", "3"))

_last_used: dict[str, float] = {}

stickers_cmd = on_command("表情", priority=20, block=True)


@stickers_cmd.handle()
async def _handle(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return

    if BOT_UIN and str(getattr(event, "self_id", "")) != BOT_UIN:
        return

    key = str(event.get_session_id())
    now = time.time()
    if now - _last_used.get(key, 0) < COOLDOWN:
        return

    keyword = arg.extract_plain_text().strip()

    if keyword in ("分类", "列表", "tags"):
        cats = sticker_lib.categories()
        parts = "、".join(f"{name}{n}" for name, n in cats.most_common())
        await stickers_cmd.finish(f"共{sticker_lib.count()}张：{parts}")

    chosen = sticker_lib.pick(keyword, key)
    if not chosen:
        await stickers_cmd.finish(f"没有「{keyword}」的，换个词试试" if keyword else "库里还没表情")

    _last_used[key] = now
    logger.info(f"stickers -> {chosen['file']}（{chosen.get('category')}／{chosen.get('text', '')[:12]}）")
    await sticker_lib.send(bot, event, chosen)
