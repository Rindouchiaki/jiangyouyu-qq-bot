"""debug 群：报错自动发过去，群里也能看日志。群号写死在 devs.DEBUG_GROUP（作者定的，只有开发者在里面）。

- 警告和错误（loguru WARNING 及以上）攒 30 秒发一条，同一类只记次数，每小时最多 HOURLY_MAX 条；
- 连上 QQ 时发一句上线了（带代码版本），重启、掉线重连一眼能看到；
- /日志 [行数] [错误] [关键词]：看 nonebot 日志的最后几行（默认 30 行，最多 200）；
  只给开发者、只在全是开发者的对话里（日志里有私聊原话和她记的事），群里发成合并转发。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
import traceback
from pathlib import Path

import backstage
import debug_report
import devs
import nonebot
from bot_guard import is_our_bot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg

BOT_UIN = os.getenv("BOT_UIN", "").strip()
ROOT = Path(__file__).resolve().parents[2]
_log_dir = Path(os.getenv("LOG_DIR", "").strip() or "logs")
LOG_FILE = (_log_dir if _log_dir.is_absolute() else ROOT / _log_dir) / "nonebot.out.log"

log_cmd = on_command("日志", aliases={"log"}, priority=15, block=True)

_collector = debug_report.Collector()
_tasks: set[asyncio.Task] = set()
# 往 debug 群发东西自己出的错不再报回去，免得绕圈
_quiet = logger.bind(no_report=True)


def _sink(message) -> None:
    rec = message.record
    exc = rec["exception"]
    detail = ""
    if exc and exc.type:
        detail = "".join(traceback.format_exception(exc.type, exc.value, exc.traceback))
    _collector.add(rec["level"].name, rec["name"] or "", str(rec["message"]), detail)


def _bot() -> Bot | None:
    try:
        return nonebot.get_bot(BOT_UIN) if BOT_UIN else nonebot.get_bot()
    except Exception:  # noqa: BLE001
        return None


async def _post(text: str) -> None:
    bot = _bot()
    if bot is None:
        return
    try:
        await bot.send_group_msg(group_id=int(devs.DEBUG_GROUP), message=text)
    except Exception as exc:  # noqa: BLE001
        _quiet.debug(f"debug 群发不出去：{type(exc).__name__}: {exc}")


async def _loop() -> None:
    while True:
        await asyncio.sleep(debug_report.BATCH_SEC)
        try:
            if _bot() is None:
                continue  # 还没连上 QQ：先攒着
            for text in _collector.drain():
                await _post(text)
        except Exception as exc:  # noqa: BLE001
            _quiet.debug(f"debug 群批量发送出错：{type(exc).__name__}: {exc}")


def _version() -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %s"],
                             capture_output=True, text=True, timeout=5, encoding="utf-8")
        return out.stdout.strip()[:60]
    except (OSError, subprocess.SubprocessError):
        return ""


def _keep(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


driver = nonebot.get_driver()


@driver.on_startup
async def _start() -> None:
    logger.add(_sink, level="WARNING", filter=lambda r: not r["extra"].get("no_report"), format="{message}")
    _keep(_loop())


@driver.on_bot_connect
async def _online(bot: Bot) -> None:
    if BOT_UIN and str(bot.self_id) != BOT_UIN:
        return
    version = _version()
    _keep(_post(f"上线了{f'（{version}）' if version else ''}"))


async def _forward(bot: Bot, event: MessageEvent, parts: list[str]) -> None:
    from nonebot_plugin_alconna import UniMessage
    from nonebot_plugin_alconna.uniseg import CustomNode, Reference, Target, Text

    nodes = [CustomNode(uid=str(bot.self_id), name="日志", content=UniMessage([Text(p)])) for p in parts]
    target = Target(id=str(event.group_id), private=False, self_id=str(bot.self_id))
    await UniMessage(Reference(nodes=nodes)).send(target=target, bot=bot)


@log_cmd.handle()
async def _log(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event) or not devs.is_dev(event.get_user_id()):
        return
    # 日志里有私聊原话、她记的事：只在全是开发者的对话里给看
    if not await backstage.devs_only(bot, event):
        return
    count, keyword, errors = debug_report.parse_log_args(arg.extract_plain_text())
    lines = await asyncio.to_thread(debug_report.tail, LOG_FILE, count, keyword, errors)
    if not lines:
        what = "报错" if errors else (f"带「{keyword}」的" if keyword else "")
        await log_cmd.finish(f"日志里没找到{what}（{LOG_FILE}）")
    head = f"{LOG_FILE.name} 最后 {len(lines)} 行{'报错' if errors else ''}{f'（{keyword}）' if keyword else ''}，" \
           f"{time.strftime('%H:%M:%S')}"
    parts = debug_report.chunks(head + "\n" + "\n".join(lines))
    if getattr(event, "group_id", None):
        try:
            await _forward(bot, event, parts)
            return
        except Exception as exc:  # noqa: BLE001
            _quiet.debug(f"日志合并转发没成：{type(exc).__name__}")
    for part in parts[:5]:
        await bot.send(event, part)
