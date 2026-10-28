"""早柚核心各游戏的登录只走私聊，登录二维码 / 链接绝不发到群里。

三道保险，不依赖核心控制台的配置：
1. 群里的登录指令（扫码登录、ww登录 等，见 gscore_guard.PREFIXED_LOGIN）不转给核心
   （按核心的拼法判断，空格、表情隔开也算），核心就不会在群里生成二维码或登录链接；
2. 私聊告诉本人去私聊里发（先试群临时会话，再试好友私聊），发不出去也不在群里说任何话；
3. 发往群的消息带登录文案或登录链接（gscore_guard.LOGIN_MARKERS）就拦下，并在之后一分钟里拦掉发往该群的图片，
   防核心把文案和二维码拆成几条发（核心「EnableForwardMessage」不是「允许」时会拆）。
核心那边仍要把各登录服务设成 DIRECT（见 docs/早柚核心接入.md）。
"""

from __future__ import annotations
from bot_guard import is_our_bot

import time
from typing import Any

import gscore_guard
from nonebot import on_message
from nonebot.adapters import Bot as BaseBot
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.exception import IgnoredException, MockApiException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.message import run_preprocessor

LINK_PLUGIN = "GenshinUID"
QR_LOCK_SEC = 60
TIP_PRIVATE = "登录和账号凭据相关的指令只在私聊用：直接在这里回复「{cmd}」，结果会发在这里，别人看不到。"

# 群号 -> 截止时间：刚拦过二维码文案的群，这段时间里的图片一律不发
_qr_lock: dict[str, float] = {}

def _texts(message) -> list[str]:
    return [str(seg.data.get("text", "")) for seg in message if seg.type == "text"]


async def _is_login(event: MessageEvent) -> bool:
    return gscore_guard.login_hint(_texts(event.get_message())) is not None


# 私聊里的登录指令也会命中，但处理函数只收群消息；block 让人设插件别接这句
login_hint = on_message(rule=_is_login, priority=10, block=True)


def _in_group(event: MessageEvent) -> bool:
    return getattr(event, "message_type", "") == "group"


async def _is_confusing(event: MessageEvent) -> bool:
    return gscore_guard.confusing_hint(_texts(event.get_message()), _in_group(event)) is not None


# 照着米游社报错发的「绑定设备」、群里发的设备指令，核心都不会回：直接给正确说法，别让人设抢答
confusing_cmd = on_message(rule=_is_confusing, priority=11, block=True)


@run_preprocessor
async def _keep_login_out_of_group(matcher: Matcher, event: MessageEvent) -> None:
    """群里的登录指令不交给连接插件，核心收不到就不会在群里发二维码。"""
    if matcher.plugin_name != LINK_PLUGIN or getattr(event, "message_type", "") != "group":
        return
    for message in (event.get_message(), event.original_message):
        if gscore_guard.is_login_command(_texts(message)) or gscore_guard.confusing_hint(_texts(message), True):
            raise IgnoredException("群里的登录指令不转给早柚核心")


@BaseBot.on_calling_api
async def _block_qr_in_group(bot: BaseBot, api: str, data: dict[str, Any]) -> None:
    try:
        if not gscore_guard.is_group_send(api, data):
            return
        group = str(data.get("group_id"))
        caption, image = gscore_guard.scan_send(data)
        now = time.time()
        if caption:
            _qr_lock[group] = now + QR_LOCK_SEC
        elif not (image and now < _qr_lock.get(group, 0)):
            return
    except Exception as exc:  # noqa: BLE001
        # 判断本身出错时宁可不发带图的群消息：钩子里的普通异常不会拦住这次调用
        logger.error(f"gscore_login: 二维码拦截判断出错 {type(exc).__name__}: {exc}")
        if "image" not in repr(data.get("message", data.get("messages", "")))[:20000]:
            return
    logger.warning(f"gscore_login: 拦下一条发往群 {data.get('group_id')} 的登录二维码消息（{api}）")
    raise MockApiException(result={"message_id": 0})


@login_hint.handle()
async def _hint(bot: Bot, event: GroupMessageEvent) -> None:
    if not is_our_bot(event):
        return

    # SnowLuma 不能主动开临时会话，只能回对方 7 天内发起过的；没有就退回好友私聊。
    # 两条都发不出去也不在群里补话，本人可以自己点机器人头像发起临时会话
    tip = TIP_PRIVATE.format(cmd=gscore_guard.login_hint(_texts(event.get_message())))
    for via, extra in (("临时会话", {"group_id": event.group_id}), ("好友私聊", {})):
        try:
            await bot.send_private_msg(user_id=event.user_id, message=tip, **extra)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"gscore_login: {via}提醒 {event.user_id} 失败 {type(exc).__name__}: {exc}")
            continue
        logger.info(f"gscore_login: 已在{via}提醒 {event.user_id}（群 {event.group_id}）")
        return
    logger.warning(f"gscore_login: 没法私聊 {event.user_id}（没加好友、也没发起过临时会话），群里不提示")


@confusing_cmd.handle()
async def _confuse_hint(bot: Bot, event: MessageEvent) -> None:
    if not is_our_bot(event):
        return
    hint = gscore_guard.confusing_hint(_texts(event.get_message()), _in_group(event))
    if hint:
        logger.info(f"gscore_login: 提示 {event.get_user_id()} 绑定设备的正确用法")
        await confusing_cmd.finish(hint)
