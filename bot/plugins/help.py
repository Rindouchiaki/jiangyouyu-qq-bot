"""/帮助（/菜单、/指令、/help）：一次看全部能用的指令。

群友看到群友能用的；开发者只有在开发者私聊或全是开发者的群里，才额外看到管理、记忆、后台数据的指令
（普通群里列出来等于告诉大家这是 bot、谁是开发者）。群里发成一条合并转发，不刷屏；私聊直接发。
"""

from __future__ import annotations

import backstage
from bot_guard import is_our_bot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger
from persona_rules import help_sections, help_text

help_cmd = on_command("帮助", aliases={"菜单", "指令", "help"}, priority=15, block=True)


async def _forward(bot: Bot, event: MessageEvent, parts: list[str]) -> bool:
    from nonebot_plugin_alconna import UniMessage
    from nonebot_plugin_alconna.uniseg import CustomNode, Reference, Target, Text

    nodes = [CustomNode(uid=str(bot.self_id), name="指令", content=UniMessage([Text(p)])) for p in parts]
    target = Target(id=str(event.group_id), private=False, self_id=str(bot.self_id))
    await UniMessage(Reference(nodes=nodes)).send(target=target, bot=bot)
    return True


@help_cmd.handle()
async def _help(bot: Bot, event: MessageEvent) -> None:
    if not is_our_bot(event):
        return
    parts = help_text(help_sections(await backstage.devs_only(bot, event)))
    if getattr(event, "group_id", None):
        try:
            if await _forward(bot, event, parts):
                return
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"help: 合并转发没成（{type(exc).__name__}），直接发")
    await bot.send(event, "\n\n".join(parts))
