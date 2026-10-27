"""早柚核心扫码登录只走私聊：群里有人发「扫码登录」，用群临时会话告诉他在私聊里发。

核心那边把「扫码登陆」服务设成只在私聊响应（见 docs/早柚核心接入.md），
二维码只会出现在临时会话里，不会被群里别人先扫走。
"""

from __future__ import annotations
from bot_guard import is_our_bot

from nonebot import on_fullmatch
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment
from nonebot.log import logger

LOGIN_WORDS = ("扫码登录", "扫码登陆")
TIP_PRIVATE = "扫码登录只在私聊进行：直接在这里回复「扫码登录」，二维码会发在这里，别人看不到。"
TIP_GROUP = "扫码登录只在私聊进行：在群成员列表里点我发起临时会话，发「扫码登录」。"
TIP_SENT = " 已经在临时会话里告诉你怎么登录了；没收到就点我头像发起临时会话，发「扫码登录」。"

# 私聊里的「扫码登录」也会命中，但处理函数只收群消息；block 让人设插件别接这句
login_hint = on_fullmatch(LOGIN_WORDS, priority=10, block=True)


@login_hint.handle()
async def _hint(bot: Bot, event: GroupMessageEvent) -> None:
    if not is_our_bot(event):
        return

    try:
        await bot.send_private_msg(user_id=event.user_id, group_id=event.group_id, message=TIP_PRIVATE)
        logger.info(f"gscore_login: 已在临时会话提醒 {event.user_id}（群 {event.group_id}）")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"gscore_login: 临时会话发送失败 {type(exc).__name__}: {exc}")
        await login_hint.finish(TIP_GROUP)
    # 临时会话可能被 QQ 静默丢掉，群里再 @ 一下，让人知道去哪看
    await login_hint.finish(MessageSegment.at(event.user_id) + TIP_SENT)
