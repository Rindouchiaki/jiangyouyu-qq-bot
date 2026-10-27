"""解析缓存定时清理：默认保留 24 小时，到点自动删，省磁盘。"""

from __future__ import annotations

import asyncio
import os

import cache_clean
from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger

CLEAN_HOURS = float(os.getenv("CACHE_CLEAN_INTERVAL_HOURS", "1"))
ENABLED = os.getenv("CACHE_CLEAN_ENABLED", "1").strip() not in ("0", "false", "False")


def _clean_now() -> dict:
    return cache_clean.clean()


if ENABLED:
    try:
        from nonebot_plugin_apscheduler import scheduler

        @scheduler.scheduled_job("interval", hours=CLEAN_HOURS, id="parser_cache_clean")
        async def _job() -> None:
            stats = await asyncio.to_thread(_clean_now)
            if stats["files"]:
                logger.info(
                    f"cache_clean: 定时清理 {stats['files']} 个文件，释放 {stats['freed'] / 1048576:.1f}MB"
                )

        @get_driver().on_startup
        async def _startup_clean() -> None:
            await asyncio.to_thread(_clean_now)

        logger.info(
            f"cache_clean: 已启用（每 {CLEAN_HOURS:.0f}h 清一次，保留 {cache_clean.TTL_HOURS:.0f}h）"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"cache_clean: 定时任务注册失败 {type(exc).__name__}: {exc}")

cache_cmd = on_command("缓存", aliases={"cache"}, priority=20, block=True)


@cache_cmd.handle()
async def _cache_cmd(event: MessageEvent) -> None:
    from bot_guard import is_our_bot

    if not is_our_bot(event):
        return
    from persona_rules import DEV_UIN

    if DEV_UIN and str(event.get_user_id()) != DEV_UIN:
        return
    stats = await asyncio.to_thread(cache_clean.size_of)
    text = event.get_plaintext().strip()
    if "清理" in text:
        done = await asyncio.to_thread(_clean_now)
        await cache_cmd.finish(
            f"清了 {done['files']} 个过期文件，释放 {done['freed'] / 1048576:.1f}MB"
        )
    await cache_cmd.finish(
        f"解析缓存 {stats['files']} 个文件，共 {stats['bytes'] / 1048576:.1f}MB\n"
        f"保留 {cache_clean.TTL_HOURS:.0f} 小时，要立刻清就发 /缓存 清理"
    )
