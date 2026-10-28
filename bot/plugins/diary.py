"""小本本指令：看好感度和日记、让她忘掉自己。

- /小本本                群里：看本群的群日记（仅开发者）
- /小本本 @某人 或 QQ号   看这个人的好感、熟悉度和日记（仅开发者）
- /小本本 清空本群        清掉本群的群日记（仅开发者）
- /忘了我                 谁都能用：删掉关于自己的全部记录（好感、熟悉度、日记）
"""

from __future__ import annotations

import os

import bonds
from bot_guard import is_our_bot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.params import CommandArg
from persona_rules import attitude

DEV_UIN = os.getenv("DEV_UIN", "").strip()

notebook_cmd = on_command("小本本", priority=17, block=True)
forget_cmd = on_command("忘了我", aliases={"忘掉我"}, priority=17, block=True)


def _describe_user(uid: str) -> str:
    rec = bonds.user(uid)
    aff, fam = int(rec.get("aff", 0)), int(rec.get("fam", 0))
    notes = "；".join(f"{n['t']}{'（私聊）' if n.get('src') == 'p' else ''}" for n in rec.get("notes", [])) or "还没记什么"
    return f"{rec.get('name') or uid}：好感 {aff} / 熟悉 {fam}（{attitude(aff, fam)}）\n{notes}"


@notebook_cmd.handle()
async def _notebook(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return
    if not DEV_UIN or str(event.get_user_id()) != DEV_UIN:
        return
    target = next((str(seg.data.get("qq")) for seg in arg if seg.type == "at"), "")
    text = arg.extract_plain_text().strip()
    gid = str(getattr(event, "group_id", "") or "")
    if text == "清空本群" and gid:
        bonds.clear_group(gid)
        bonds.save(force=True)
        await notebook_cmd.finish("本群的群日记清掉了")
    if not target and text.isdigit():
        target = text
    if target:
        await notebook_cmd.finish(_describe_user(target))
    if gid:
        rec = bonds.group(gid)
        notes = "；".join(n["t"] for n in rec.get("notes", [])) or "还没记什么"
        style = "；".join(n["t"] for n in rec.get("style", [])) or "还没记什么"
        await notebook_cmd.finish(f"本群日记：{notes}\n本群风格：{style}")
    await notebook_cmd.finish("用法：/小本本 @某人 或 /小本本 QQ号；群里不带参数看群日记")


@forget_cmd.handle()
async def _forget(bot: Bot, event: MessageEvent) -> None:
    if not is_our_bot(event):
        return
    existed = bonds.forget_user(str(event.get_user_id()))
    bonds.save(force=True)
    await forget_cmd.finish("哼，忘了就忘了，谁稀罕记你" if existed else "本来就没记你什么")
