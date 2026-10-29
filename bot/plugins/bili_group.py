"""开发者给指定群或私聊配置 B 站订阅（走 Bison 的配置接口）。

Bison 自带的 /添加订阅 只认当前会话、一步步问，群里想给别的群配就得 @ 她、还挺吵。这里两条指令：
`/群订阅` 点名群号给群配，`/私聊订阅` 推到某人的私聊；一句话写完，一次能订好几个 UP，动态和开播提醒一起配。
写入的是同一份订阅库，Bison 的调度会通过它的 add/delete hook 立刻同步。
"""

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment
from nonebot.log import logger

import devs
from bot_guard import is_our_bot
from persona_rules import (
    BILI_DYN_CATS,
    BILI_LIVE_DYN_CAT,
    GROUP_SUB_USAGE,
    PRIVATE_SUB_USAGE,
    bili_cat_name,
    bili_sub_cats,
    parse_sub_command,
)

try:  # Bison 没装或加载失败时整条指令静默不注册
    import httpx
    import nonebot_plugin_saa.auto_select_bot as saa_auto
    from nonebot_bison.config import config as bison_config
    from nonebot_bison.platform import platform_manager
    from nonebot_plugin_saa import TargetQQGroup, TargetQQPrivate

    _BISON_OK = True
except Exception as exc:  # noqa: BLE001
    _BISON_OK = False
    logger.warning(f"bili_group: Bison 不可用，/群订阅 /私聊订阅 不注册（{type(exc).__name__}: {exc}）")

group_sub = on_command("群订阅", priority=19, block=True)
private_sub = on_command("私聊订阅", priority=19, block=True)

DYN = "bilibili"  # 动态
LIVE = "bilibili-live"  # 开播提醒，Bison 里类别 1
LIVE_CATS = [1]


async def _target_name(target: str) -> str:
    """问 B 站要 UP 的名字；要不到就先用 UID 顶上。"""
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        try:
            name = await platform_manager[DYN].get_target_name(client, target)
            if name:
                return name
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"bili_group: Bison 取 UP 名字失败 {target}（{type(exc).__name__}）")
        try:  # 没开过直播间的 UP 那边查不到，直接问一下名片接口
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/card",
                params={"mid": target},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
            )
            name = ((resp.json().get("data") or {}).get("card") or {}).get("name")
            if name:
                return str(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"bili_group: 名片接口取名字失败 {target}（{type(exc).__name__}）")
    return f"UID{target}"


def _user(kind: str, oid: str):
    return TargetQQGroup(group_id=int(oid)) if kind == "group" else TargetQQPrivate(user_id=int(oid))


async def _label(bot: Bot, kind: str, oid: str) -> str:
    try:
        if kind == "group":
            name = (await bot.get_group_info(group_id=int(oid), no_cache=False)).get("group_name") or ""
            return f"群 {oid}（{name}）" if name else f"群 {oid}"
        name = (await bot.get_stranger_info(user_id=int(oid))).get("nickname") or ""
        return f"{name}（{oid}）的私聊" if name else f"{oid} 的私聊"
    except Exception:  # noqa: BLE001
        return f"群 {oid}" if kind == "group" else f"{oid} 的私聊"


async def _unreachable(bot: Bot, kind: str, oid: str) -> str:
    """推不推得过去：群要在群里，私聊要是好友。查不了就当推得过去。"""
    try:
        if kind == "group":
            ids = {str(g.get("group_id")) for g in await bot.get_group_list()}
            return "" if oid in ids else "我不在这个群里，推不过去。"
        ids = {str(f.get("user_id")) for f in await bot.get_friend_list()}
        return "" if oid in ids else "TA 还没加我好友，私聊推不过去；加了好友再来订。"
    except Exception:  # noqa: BLE001
        return ""


async def _refresh_push_cache(user) -> None:
    """saa 按「哪个号能发到哪」的缓存挑号：新进的群、新加的好友不在里面，推送会一直发不出去。"""
    try:
        if not any(user in targets for targets in saa_auto.BOT_CACHE.values()):
            await saa_auto.refresh_bots()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"bili_group: 刷新推送账号缓存失败（{type(exc).__name__}）")


async def _ups(user) -> dict[str, dict]:
    """这个群/私聊订了谁：按 UID 合并动态和开播提醒两条订阅。"""
    ups: dict[str, dict] = {}
    for sub in await bison_config.list_subscribe(user):
        t = sub.target
        up = ups.setdefault(str(t.target), {"name": t.target_name, "dyn": None, "tags": [], "live": False, "other": []})
        if t.platform_name == DYN:
            up["dyn"] = sorted(int(c) for c in (sub.categories or []))
            up["tags"] = list(sub.tags or [])
            up["name"] = t.target_name
        elif t.platform_name == LIVE:
            up["live"] = True
        else:
            up["other"].append(t.platform_name)
    return ups


def _kinds(up: dict) -> str:
    raw = up["dyn"] or []
    # 6（直播推送）跟开播提醒重复，列出来的时候不提它，免得看着像订了两份
    dyn = [c for c in raw if c != BILI_LIVE_DYN_CAT] or raw
    if dyn == sorted(BILI_DYN_CATS) and up["live"]:
        kinds = ["全部"]
    else:
        kinds = [bili_cat_name(c) for c in dyn] + (["直播"] if up["live"] else [])
    kinds += up["other"]
    tags = f"｜标签 {'、'.join(up['tags'])}" if up["tags"] else ""
    return ("、".join(kinds) or "（没选类别）") + tags


async def _list(label: str, user, usage: str) -> str:
    ups = await _ups(user)
    if not ups:
        return f"{label} 还没订谁。\n{usage}"
    lines = [f"{label} 订了 {len(ups)} 个："]
    for idx, (uid, up) in enumerate(ups.items(), 1):
        lines.append(f"{idx}. {up['name']}（uid {uid}）：{_kinds(up)}")
    return "\n".join(lines)


async def _add(label: str, user, uids: list[str], words: list[str]) -> str:
    plan = bili_sub_cats(words)
    if isinstance(plan, str):
        return plan
    dyn_cats, live = plan
    ups = await _ups(user)
    lines: list[str] = []
    for uid in uids:
        old = ups.get(uid)
        if old and not words:
            lines.append(f"{old['name']} 早就订了：{_kinds(old)}（想改就在后面写类别）")
            continue
        name = await _target_name(uid)
        has_dyn = bool(old) and old["dyn"] is not None
        has_live = bool(old) and old["live"]
        try:
            # 已经订过的照新写的类别改：动态改类别，直播按写没写开/关
            if dyn_cats and has_dyn:
                await bison_config.update_subscribe(user, uid, name, DYN, dyn_cats, old["tags"])
            elif dyn_cats:
                await bison_config.add_subscribe(user, uid, name, DYN, dyn_cats, [])
            elif has_dyn:
                await bison_config.del_subscribe(user, uid, DYN)
            if live and not has_live:
                await bison_config.add_subscribe(user, uid, name, LIVE, LIVE_CATS, [])
            elif not live and has_live:
                await bison_config.del_subscribe(user, uid, LIVE)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"bili_group: 给 {user} 订 {uid} 失败（{type(exc).__name__}: {exc}）")
            lines.append(f"{name}（uid {uid}）没订上（{type(exc).__name__}），稍后再试")
            continue
        now = {"dyn": dyn_cats, "live": live, "tags": old["tags"] if old else [], "other": old["other"] if old else []}
        lines.append(f"{'改好' if old else '订上'} {name}（uid {uid}）：{_kinds(now)}")
    await _refresh_push_cache(user)
    return f"{label}：\n" + "\n".join(lines)


async def _del(label: str, user, uids: list[str], names: list[str]) -> str:
    ups = await _ups(user)
    lines: list[str] = []
    picked: list[str] = []
    for uid in uids:
        if uid in ups:
            picked.append(uid)
        else:
            lines.append(f"本来就没订 uid {uid}，不用删")
    for name in names:
        hit = [uid for uid, up in ups.items() if up["name"] == name] or [
            uid for uid, up in ups.items() if name in up["name"]
        ]
        if len(hit) == 1:
            picked.append(hit[0])
        elif hit:
            lines.append(f"「{name}」对上好几个：" + "、".join(f"{ups[u]['name']}（uid {u}）" for u in hit) + "，写 UID 吧")
        else:
            lines.append(f"没订过叫「{name}」的")
    for uid in dict.fromkeys(picked):
        up = ups[uid]
        try:
            if up["dyn"] is not None:
                await bison_config.del_subscribe(user, uid, DYN)
            if up["live"]:
                await bison_config.del_subscribe(user, uid, LIVE)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"bili_group: 删订阅失败（{type(exc).__name__}: {exc}）")
            lines.append(f"{up['name']} 没删掉（{type(exc).__name__}），稍后再试")
            continue
        extra = f"（{'、'.join(up['other'])} 那几条是 /添加订阅 配的，要删用 /删除订阅）" if up["other"] else ""
        lines.append(f"不再推 {up['name']}（uid {uid}）{extra}")
    return f"{label}：\n" + "\n".join(lines)


async def _run(bot: Bot, event: Event, kind: str) -> str | None:
    if not _BISON_OK or not is_our_bot(event) or not devs.is_dev(event.get_user_id()):
        return None
    cmd, usage = ("群订阅", GROUP_SUB_USAGE) if kind == "group" else ("私聊订阅", PRIVATE_SUB_USAGE)
    in_group = getattr(event, "message_type", "") == "group"
    here = str(getattr(event, "group_id", "")) if in_group else ""
    # 没写号时：/群订阅 在群里就是本群；/私聊订阅 就是发指令的人自己
    default_id = here if kind == "group" else str(event.get_user_id())
    action, oid, uids, words = parse_sub_command(event.get_plaintext(), cmd, default_id)
    if action == "usage":
        return usage
    # 群里只能配本群，免得群友看着你在群里点别的群；私聊随便
    if kind == "group" and in_group and oid != here:
        return f"群里只能配这个群；要给别的群配，私聊我。想订 UP {oid} 的话发 /群订阅 加 {oid}"
    user = _user(kind, oid)
    label = await _label(bot, kind, oid)
    if action == "list":
        return await _list(label, user, usage)
    if action == "del":
        return await _del(label, user, uids, words)
    if problem := await _unreachable(bot, kind, oid):
        return problem
    return await _add(label, user, uids, words)


@group_sub.handle()
async def _handle_group(bot: Bot, event: Event) -> None:
    if reply := await _run(bot, event, "group"):
        await group_sub.finish(MessageSegment.text(reply))


@private_sub.handle()
async def _handle_private(bot: Bot, event: Event) -> None:
    if reply := await _run(bot, event, "private"):
        await private_sub.finish(MessageSegment.text(reply))
