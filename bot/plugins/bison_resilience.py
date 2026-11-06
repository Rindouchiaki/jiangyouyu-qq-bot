"""Bison 的 B 站动态列表偶尔被风控（HTTP 412），别让它把调度器整轮打挂。

`nonebot_bison.platform.bilibili.platforms.Bilibili.get_sub_list` 里 `timeout=4.0`，
b 站风控命中时直接回一个 412 的 HTML 安全页，`res.raise_for_status()` 抛
`httpx.HTTPStatusError`：调度任务记一条 `[ERROR] apscheduler Job ... raised an exception`，
再加上一整页 HTML 进日志和 debug 群。

风控通常只持续几分钟，这一轮跳过、下一轮自然会好。这里做三件事：
1. 412（以及连接/超时抖动）当成「这一轮没结果」返回空列表，不再抛给 apscheduler；
2. 412 命中后冷却 `BISON_412_COOLDOWN` 秒（默认 300），冷却期内直接返回空，不去硬撞，
   免得把短风控撞成长风控；
3. 网络抖动（DNS/TCP/超时）先立刻重试一次（`BISON_RETRY_DELAY`，默认 0.8 秒），
   还不行才跳过这一轮，且只记 INFO —— 这类抖动不值得推到 debug 群。
判定逻辑在 `bot/bison_guard.py`（纯函数，可离线测试）。
"""

import asyncio
import os
import time

from nonebot.log import logger

import bison_guard

_RETRY_DELAY = float(os.getenv("BISON_RETRY_DELAY", "0.8"))

try:
    import httpx
    from nonebot_bison.platform.bilibili.platforms import Bilibili
except Exception as exc:  # noqa: BLE001
    logger.warning(f"bison_resilience: 未就绪，跳过补丁（{type(exc).__name__}: {exc}）")
else:
    _cool = bison_guard.Cooldown(float(os.getenv("BISON_412_COOLDOWN", str(bison_guard.COOLDOWN_DEFAULT))))
    _orig_get_sub_list = Bilibili.get_sub_list

    async def _get_sub_list(self, target, *args, **kwargs):
        now = time.time()
        if _cool.active(now):
            logger.debug(f"bison_resilience: 冷却中，跳过 host_mid={target}（还剩 {_cool.remaining(now)}s）")
            return []
        try:
            return await _orig_get_sub_list(self, target, *args, **kwargs)
        except httpx.HTTPError as exc:
            if not bison_guard.is_transient(exc):
                raise
            if bison_guard.is_rate_limited(exc):
                _cool.trip(time.time())
                logger.warning(
                    f"bison_resilience: 动态被风控（412），跳过这一轮，{_cool.seconds:.0f} 秒内不再请求",
                    extra={"no_report": True},
                )
                return []
            # 网络抖动（DNS/TCP/超时）：多半是一次性的，马上再试一次；
            # 还不行才放弃这一轮，而且只记 INFO —— 这条不值得推到 debug 群。
            await asyncio.sleep(_RETRY_DELAY)
            try:
                return await _orig_get_sub_list(self, target, *args, **kwargs)
            except httpx.HTTPError as retry_exc:
                if not bison_guard.is_transient(retry_exc):
                    raise
                if bison_guard.is_rate_limited(retry_exc):
                    _cool.trip(time.time())
                    logger.warning(
                        f"bison_resilience: 动态被风控（412），跳过这一轮，{_cool.seconds:.0f} 秒内不再请求",
                        extra={"no_report": True},
                    )
                    return []
                logger.info(
                    f"bison_resilience: 动态列表两次都没连上（{type(retry_exc).__name__}），跳过这一轮"
                )
                return []

    Bilibili.get_sub_list = _get_sub_list
    logger.info("bison_resilience: 已启用（412 冷却跳过；网络抖动先重试一次）")
