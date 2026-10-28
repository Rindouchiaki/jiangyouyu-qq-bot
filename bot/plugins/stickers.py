"""表情包插件：按标签挑一张本地表情发出去。

数据来自 tools/export_qq_emoji.py + ocr/tag 两步生成的 stickers/index.json。

用法（群里）：
    /表情            随机一张
    /表情 搞笑       按分类或标签/文字匹配
    /表情 分类       看有哪些分类
    /表情 收藏       看她最常用的几张表情和用途备注
    /表情 备注 <id前几位> <用途>   手动给某张表情写用途（仅开发者）

后台：本地视觉模型闲着时一张张读库里的表情（读过不再读），每天看一次自己的收藏，
真不喜欢的放 30 天、其它的放 90 天一次都没发过才删。
"""

from __future__ import annotations
from bot_guard import is_our_bot

import asyncio
import os
import time

import devs
import nonebot
import sticker_lib
import vision
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg

BOT_UIN = os.getenv("BOT_UIN", "").strip()
COOLDOWN = float(os.getenv("STICKER_COOLDOWN", "3"))

# 后台读表情：每张之间隔几秒（CPU 跑视觉模型，别和聊天抢）
STICKER_READ = os.getenv("STICKER_READ", "1").strip() not in ("0", "false", "False")
STICKER_READ_GAP = float(os.getenv("STICKER_READ_GAP", "20"))
# 清收藏别太严：真不喜欢的放 30 天没发过才删，其余放 90 天一次都没发过才删；发过的、可爱二次元的不删
STICKER_PRUNE_DAYS = float(os.getenv("STICKER_PRUNE_DAYS", "30"))
STICKER_IDLE_DAYS = float(os.getenv("STICKER_IDLE_DAYS", "90"))

_last_used: dict[str, float] = {}
_bg_task: asyncio.Task | None = None


async def _read_loop() -> None:
    """后台慢慢读表情；顺带每天清一次收藏。"""
    await asyncio.sleep(120)
    last_prune = 0.0
    while True:
        try:
            if time.time() - last_prune > 86400:
                last_prune = time.time()
                gone = await asyncio.to_thread(sticker_lib.prune, None, STICKER_PRUNE_DAYS, STICKER_IDLE_DAYS)
                if gone:
                    logger.info(f"stickers: 删掉 {len(gone)} 张不喜欢的收藏：{'、'.join(it['id'][:6] for it in gone)}")
            item = sticker_lib.next_unread() if STICKER_READ else None
            if item is None or not await vision.vlm_ready():
                await asyncio.sleep(600)
                continue
            path = sticker_lib.STICKER_DIR / item["file"]
            read = await vision.read_sticker(await asyncio.to_thread(path.read_bytes))
            # 没看懂也记一笔（desc 空），免得卡在同一张上反复读
            sticker_lib.set_read(item["id"], read or {"desc": "", "mean": "", "scene": "", "acg": False, "cute": 0})
            logger.debug(f"stickers: 读了 {item['id'][:6]} → {(read or {}).get('desc') or '没看懂'}，还剩 {sticker_lib.unread_count()} 张")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"stickers: 后台读表情出错 {type(exc).__name__}: {exc}")
            await asyncio.sleep(600)
        await asyncio.sleep(STICKER_READ_GAP)


@nonebot.get_driver().on_startup
async def _start_reader() -> None:
    global _bg_task
    _bg_task = asyncio.create_task(_read_loop())

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

    if keyword in ("收藏", "常用", "喜欢"):
        favs = sticker_lib.favorites()
        if not favs:
            await stickers_cmd.finish("还没有常用的表情")
        lines = [f"{it['id'][:6]} 用过{n.get('uses', 0)}次：{n.get('note') or it.get('category', '')}" for it, n in favs]
        await stickers_cmd.finish("\n".join(lines))

    if keyword.startswith("备注"):
        if not devs.is_dev(event.get_user_id()):
            return
        parts = keyword[2:].split(maxsplit=1)
        item = sticker_lib.set_note(parts[0], parts[1]) if len(parts) == 2 else None
        await stickers_cmd.finish(
            f"记下了：{item['id'][:6]} → {parts[1][:sticker_lib.NOTE_MAX_CHARS]}" if item
            else "用法：/表情 备注 <id前几位> <用途>（id 用 /表情 收藏 看，前几位要能唯一对上）"
        )

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
