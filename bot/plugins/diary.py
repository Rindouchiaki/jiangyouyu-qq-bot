"""小本本指令：看好感度和群关系图，删记录，手动调好感度。

都是后台数据：只在「全是开发者」的对话里能用（开发者私聊，或者除了机器人全是开发者的群，比如内部测试群），
别的地方一律不理。看的指令当成请求问酱油鱼：她先用人设说两句、总结一下，再发原始资料；改的指令直接改。
日记（个人日记、群日记、群风格）谁都不能翻，开发者也不行：这些指令的资料里不带日记原文，
只有在本群里画关系图时连上本群群日记里的关系。

- /关系图 [群号]         那个群的关系图：她在中间，连到每个记过的群友（写态度档）；在那个群里画才连群友之间的关系
- /小本本 删除 @某人 或 QQ号   删掉关于这个人的全部记录（好感、熟悉度、日记），比如本人要求时
- /小本本 清空 群号      清掉那个群的群日记
- /好感 @某人            看这个人的好感 / 熟悉 / 态度档
- /好感 @某人 +10        好感加 10（也可以 -10；=30 或直接 30 是设成 30）
- /好感 @某人 熟悉 +5    调熟悉度（0~100），别的好感减太多人真的会讨厌你
"""

from __future__ import annotations

import asyncio
import re

import backstage
import bonds
import relation_graph
from bot_guard import is_our_bot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.params import CommandArg
from persona_rules import INITIAL_AFF, INITIAL_FAM, attitude, parse_relation

notebook_cmd = on_command("小本本", priority=17, block=True)
bond_cmd = on_command("好感", priority=17, block=True)
graph_cmd = on_command("关系图", priority=17, block=True)


def _describe_user(uid: str) -> str:
    """只给数字和态度档，不带日记：日记里有她和别人聊的私事。"""
    rec = bonds.user(uid)
    aff = int(rec.get("aff", INITIAL_AFF))
    fam = int(rec.get("fam", INITIAL_FAM))
    return f"{rec.get('name') or uid}：好感 {aff} / 熟悉 {fam}（{attitude(aff, fam)}）"


async def _pick_group(bot: Bot, event: MessageEvent, text: str) -> tuple[str, str]:
    """要看哪个群：写了群号就是它；群里没写就是本群；私聊没写就从记过的群里挑（只有一个直接用）。返回 (群号, 提示)。"""
    names = await backstage.group_names(bot)
    here = str(getattr(event, "group_id", "") or "")
    if text.isdigit():
        return text, ""
    if here:
        return here, ""
    known = [g for g in bonds.known_groups() if g != here]
    if len(known) == 1:
        return known[0], ""
    if not known:
        return "", "还没记过哪个群的群日记"
    listing = "、".join(f"{g}（{names.get(g) or '?'}）" for g in known[:10])
    return "", f"要看哪个群？{listing}，后面带上群号"


async def _graph(bot: Bot, gid: str, title: str, links_ok: bool) -> tuple[bytes, str]:
    """一个群的关系图（PNG）和对应的文字资料；links_ok 为假时不读群日记，只画她对每个人的态度。"""
    members = await backstage.group_members(bot, gid) or frozenset()
    self_id = str(bot.self_id)
    people = [(uid, rec) for uid, rec in bonds.known_people(members) if uid != self_id]
    nodes = []
    lines = []
    for uid, rec in people[: relation_graph.MAX_PEOPLE]:
        aff, fam = int(rec.get("aff", INITIAL_AFF)), int(rec.get("fam", INITIAL_FAM))
        name = rec.get("name") or uid
        nodes.append((name, attitude(aff, fam)))
        lines.append(f"{name}：{attitude(aff, fam)}（好感 {aff} / 熟悉 {fam}）")
    links, loose = [], []
    for note in bonds.group(gid).get("notes", []) if links_ok else []:
        rel = parse_relation(note["t"])
        (links if rel else loose).append(rel or note["t"])
    lines += [f"{a} — {b}：{r}" for a, b, r in links] + [f"（关系）{t}" for t in loose]
    png = await asyncio.to_thread(relation_graph.render, "酱油鱼", nodes, links, loose, title)
    return png, "\n".join(lines) or "这个群还没记过谁"


@notebook_cmd.handle()
async def _notebook(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event) or not await backstage.devs_only(bot, event):
        return
    target = next((str(seg.data.get("qq")) for seg in arg if seg.type == "at"), "")
    text = arg.extract_plain_text().strip()
    if text.startswith("清空"):
        gid = text[2:].strip().replace("本群", "") or str(getattr(event, "group_id", "") or "")
        if not gid.isdigit():
            await notebook_cmd.finish("用法：/小本本 清空 群号")
        bonds.clear_group(gid)
        bonds.save(force=True)
        await notebook_cmd.finish(f"群 {gid} 的群日记清掉了")
    if text.startswith("删除"):
        uid = target or text[2:].strip()
        if not uid.isdigit():
            await notebook_cmd.finish("用法：/小本本 删除 @某人 或 /小本本 删除 QQ号")
        existed = bonds.forget_user(uid)
        bonds.save(force=True)
        await notebook_cmd.finish(f"关于 {uid} 的记录删了" if existed else f"本来就没有 {uid} 的记录")
    # 翻日记拿掉了：谁都不能看别人的日记，开发者也不行
    await notebook_cmd.finish("小本本不给翻。只能 /小本本 删除 @某人（或 QQ号）、/小本本 清空 群号")


@graph_cmd.handle()
async def _graph_cmd(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event) or not await backstage.devs_only(bot, event):
        return
    gid, tip = await _pick_group(bot, event, arg.extract_plain_text().strip())
    if tip:
        await graph_cmd.finish(tip)
    names = await backstage.group_names(bot)
    title = f"群 {gid}{f'（{names[gid]}）' if names.get(gid) else ''} 的关系图"
    # 群日记只在本群里用，别的群的关系不带出来
    png, data = await _graph(bot, gid, title, gid == str(getattr(event, "group_id", "") or ""))
    await backstage.present(bot, event, "这个群的关系图", data, png)


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
    if not is_our_bot(event) or not await backstage.devs_only(bot, event):
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
        await backstage.present(bot, event, "对这个人的好感", _describe_user(target))
        return
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
