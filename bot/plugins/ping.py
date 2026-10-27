"""示例插件：群里 /ping，回 pong。

用来验证 SnowLuma -> NoneBot2 的链路是否打通。
只允许机器人号（BOT_UIN）回应，避免另一个号也抢答。
"""

import os
from bot_guard import is_our_bot

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.params import CommandArg

BOT_UIN = os.getenv("BOT_UIN", "").strip()

ping = on_command("ping", priority=5, block=True)


@ping.handle()
async def _ping(event: GroupMessageEvent, args: Message = CommandArg()):
    if not is_our_bot(event):
        return

    if BOT_UIN and str(getattr(event, "self_id", "")) != BOT_UIN:
        return
    await ping.finish("pong" + (f" {args.extract_plain_text()}" if args else ""))
