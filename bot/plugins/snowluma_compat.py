"""SnowLuma 兼容补丁：表情回应 + B 站 cookie 的虚假「需要刷新」。

1) 解析插件每解析一条消息会发两次表情回应（resolving / done），uni seg 的 OneBot v11
   导出器只认 LLOneBot / Lagrange / NapCat / ws-plugin，SnowLuma 落到 else 分支刷
   `Unsupported Client: SnowLuma for message reaction!`。SnowLuma 其实实现了
   `set_msg_emoji_like`（message_id / emoji_id / set），这里补上。

2) parser 的 B 站凭据每轮都 `check_refresh()`，我们的 cookie 里没有 `ac_time_value`
   （没有它就调不了续期接口），于是每次都刷
   `哔哩哔哩凭证刷新需要包含 SESSDATA, ac_time_value`。SESSDATA 还有效时直接用，
   没有 ac_time_value 就不算「需要刷新」。
"""

from nonebot.log import logger

try:
    from nonebot_plugin_alconna.uniseg.adapters.onebot11.exporter import Onebot11MessageExporter
except Exception as exc:  # noqa: BLE001
    logger.warning(f"snowluma_compat: uniseg 未就绪，跳过表情回应补丁（{type(exc).__name__}: {exc}）")
else:
    _orig_reaction = Onebot11MessageExporter.reaction

    async def _reaction(self, emoji, mid, bot, context, delete: bool = False):
        try:
            info = await bot.get_version_info()
        except Exception:  # noqa: BLE001
            info = {}
        if str((info or {}).get("app_name", "")) == "SnowLuma":
            message_id = mid["message_id"] if isinstance(mid, dict) else mid
            try:
                await bot.call_api(
                    "set_msg_emoji_like",
                    message_id=int(message_id),
                    emoji_id=str(emoji.id),
                    set=not delete,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"snowluma_compat: 表情回应没成（{type(exc).__name__}: {exc}）")
            return
        return await _orig_reaction(self, emoji, mid, bot, context, delete)

    Onebot11MessageExporter.reaction = _reaction
    logger.info("snowluma_compat: 已启用（SnowLuma 的表情回应用 set_msg_emoji_like）")

try:
    from bilibili_api.utils.network import Credential
except Exception as exc:  # noqa: BLE001
    logger.debug(f"snowluma_compat: bilibili_api 未就绪，跳过 cookie 刷新补丁（{type(exc).__name__}）")
else:
    if not getattr(Credential.check_refresh, "_snowluma_patched", False):
        _orig_check_refresh = Credential.check_refresh

        async def _check_refresh(self) -> bool:
            # 没有 ac_time_value 就调不了续期接口；SESSDATA 还有效时直接当「不用刷新」
            if not self.has_ac_time_value():
                return False
            return await _orig_check_refresh(self)

        _check_refresh._snowluma_patched = True
        Credential.check_refresh = _check_refresh
