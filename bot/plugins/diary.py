"""小本本指令（都只给开发者）：看好感度和日记，删记录，手动调好感度。

- /小本本                群里：看本群的群日记
- /小本本 @某人 或 QQ号   看这个人的好感、熟悉度和日记
- /小本本 删除 @某人 或 QQ号   删掉关于这个人的全部记录（好感、熟悉度、日记），比如本人要求时
- /小本本 清空本群        清掉本群的群日记
- /好感 @某人            看这个人的好感 / 熟悉 / 态度档
- /好感 @某人 +10        好感加 10（也可以 -10；=30 或直接 30 是设成 30）
- /好感 @某人 熟悉 +5    调熟悉度（0~100），别的好感减太多人真的会讨厌你
"""

from __future__ import annotations

import re

import bonds
import devs
from bot_guard import is_our_bot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.params import CommandArg
from persona_rules import INITIAL_AFF, INITIAL_FAM, attitude

notebook_cmd = on_command("小本本", priority=17, block=True)
bond_cmd = on_command("好感", priority=17, block=True)


def _describe_user(uid: str) -> str:
    rec = bonds.user(uid)
    aff = int(rec.get("aff", INITIAL_AFF))
    fam = int(rec.get("fam", INITIAL_FAM))
    notes = "；".join(f"{n['t']}{'（私聊）' if n.get('src') == 'p' else ''}" for n in rec.get("notes", [])) or "还没记什么"
    return f"{rec.get('name') or uid}：好感 {aff} / 熟悉 {fam}（{attitude(aff, fam)}）\n{notes}"


@notebook_cmd.handle()
async def _notebook(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return
    if not devs.is_dev(event.get_user_id()):
        return
    target = next((str(seg.data.get("qq")) for seg in arg if seg.type == "at"), "")
    text = arg.extract_plain_text().strip()
    gid = str(getattr(event, "group_id", "") or "")
    if text == "清空本群" and gid:
        bonds.clear_group(gid)
        bonds.save(force=True)
        await notebook_cmd.finish("本群的群日记清掉了")
    if text.startswith("删除"):
        uid = target or text[2:].strip()
        if not uid.isdigit():
            await notebook_cmd.finish("用法：/小本本 删除 @某人 或 /小本本 删除 QQ号")
        existed = bonds.forget_user(uid)
        bonds.save(force=True)
        await notebook_cmd.finish(f"关于 {uid} 的记录删了" if existed else f"本来就没有 {uid} 的记录")
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


def _bond_usage(event: MessageEvent) -> str:
    """群里能 @ 人，私聊只能写 QQ 号或名字，用法提示跟着变。"""
    who = "@某人、QQ号 或名字" if getattr(event, "message_type", "") == "group" else "QQ号 或名字"
    return (
        f"用法：/好感 {who} —— 看对方现在的好感/熟悉\n"
        f"/好感 {who} +10 加好感、-10 减、=30 设成 30；写「熟悉 +5」是调熟悉度\n"
        f"不写对象就是改你自己：/好感 熟悉 +50、/好感 +10"
    )


def _pick_by_name(text: str) -> tuple[str, str, str]:
    """没给 QQ 号时按昵称找人：返回 (QQ号, 剩下的话, 提示)。

    一对一碰上就把昵称从文本里挖掉，剩下的（+10 / 熟悉 +5）照常解析；
    碰上多个或者一个都没碰上，第三个返回值就是给用户看的提示。
    """
    hint = re.sub(r"[+\-=]?\s*\d{1,3}", " ", text)
    hint = hint.replace("熟悉", " ").replace("好感", " ").strip()
    if not hint:
        return "", text, ""
    hits = bonds.find_user(hint)
    if len(hits) == 1:
        return hits[0], text.replace(hint, " "), ""
    if len(hits) > 1:
        names = "、".join(f"{bonds.user(u).get('name') or u}({u})" for u in hits[:6])
        return "", text, f"好几个都叫这个：{names}，用 QQ 号再点一下"
    return "", text, f"没找到叫「{hint}」的人，写 QQ 号吧"


@bond_cmd.handle()
async def _bond(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    """开发者手动调好感/熟悉度：/好感 @人（看）、+10 / -10 / =30 / 熟悉 +5。"""
    if not is_our_bot(event):
        return
    if not devs.is_dev(event.get_user_id()):
        return
    target = next((str(seg.data.get("qq")) for seg in arg if seg.type == "at"), "")
    text = arg.extract_plain_text().strip().translate(str.maketrans("＋－＝", "+-="))
    m = re.search(r"(?<!\d)\d{5,}(?!\d)", text)
    if not target and m:
        target = m.group(0)
        text = (text[:m.start()] + " " + text[m.end():]).strip()
    if not target:
        target, text, tip = _pick_by_name(text)
        if tip:
            await bond_cmd.finish(tip)
    if not target:
        # 没点名就默认改当前说话的人：私聊是对方，群里是发指令的人
        if re.search(r"[+\-=]?\s*\d", text) or "熟悉" in text or "好感" in text:
            target = str(event.get_user_id())
        else:
            await bond_cmd.finish(_bond_usage(event))
    field = "fam" if ("熟悉" in text) else "aff"
    level = re.search(r"([+\-=]?)\s*(\d{1,3})", text)
    if not level:
        await bond_cmd.finish(_describe_user(target))
    op, val = level.group(1) or "=", int(level.group(2))
    cur = bonds.user(target)
    cur_aff, cur_fam = int(cur.get("aff", INITIAL_AFF)), int(cur.get("fam", INITIAL_FAM))
    if field == "fam":
        new_fam = cur_fam + val if op == "+" else cur_fam - val if op == "-" else val
        before, after = bonds.set_levels(target, fam=new_fam)
    else:
        new_aff = cur_aff + val if op == "+" else cur_aff - val if op == "-" else val
        before, after = bonds.set_levels(target, aff=new_aff)
    bonds.save(force=True)
    name = after.get("name") or target
    aff0, aff1 = int(before.get("aff", INITIAL_AFF)), int(after["aff"])
    fam0, fam1 = int(before.get("fam", INITIAL_FAM)), int(after["fam"])
    changed = f"好感 {aff0}→{aff1}" if field == "aff" else f"熟悉 {fam0}→{fam1}"
    await bond_cmd.finish(f"{name}：{changed}（{attitude(aff1, fam1)}）｜现在 好感 {aff1} / 熟悉 {fam1}")
