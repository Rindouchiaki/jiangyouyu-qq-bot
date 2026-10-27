"""早柚核心没连上时，连接插件先不处理消息。

连接插件（优先级 0）对每条消息都会先试着连核心，核心没开时每条要卡 4 秒左右，
后面的人设插件也跟着等。开了 GSUID_CORE_REPEAT 时它每 10 秒自己重连一次，
没连上的这段时间里消息直接跳过它就行；手动「连接core」不拦。
"""

from __future__ import annotations

from nonebot.exception import IgnoredException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.message import run_preprocessor

LINK_PLUGIN = "GenshinUID"


@run_preprocessor
async def _skip_link_when_core_down(matcher: Matcher) -> None:
    if matcher.plugin_name != LINK_PLUGIN:
        return
    try:
        import GenshinUID
        from GenshinUID.config import gs_config
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"gscore_link: 读不到连接插件状态 {type(exc).__name__}: {exc}")
        return
    if type(matcher) is getattr(GenshinUID, "connect_core", None):
        return
    if getattr(GenshinUID, "gsclient", None) is None and gs_config().gsuid_core_repeat:
        raise IgnoredException("早柚核心未连接，等连接插件定时重连")
