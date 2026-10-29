"""在私聊里给指定群配置 B 站订阅（走 Bison 的配置接口）。

Bison 自带的 /添加订阅 只认当前会话，群里想给别的群配就得 @ 她、还挺吵；这个指令让开发者私聊直接点名群号，
写入的是同一份订阅库，Bison 的调度会通过它的 add/delete hook 立刻同步。
"""

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Event, Message
from nonebot.log import logger

import devs
from bot_guard import is_our_bot
from persona_rules import GROUP_SUB_USAGE, parse_group_sub

try:  # Bison 没装或加载失败时整条指令静默不注册
    import httpx
    from nonebot_bison.config import config as bison_config
    from nonebot_bison.platform import platform_manager
    from nonebot_bison.config.db_config import SubscribeDupException
    from nonebot_plugin_saa import TargetQQGroup

    _BISON_OK = True
except Exception as exc:  # noqa: BLE001
    _BISON_OK = False
    logger.warning(f"bili_group: Bison 不可用，/群订阅 不注册（{type(exc).__name__}: {exc}）")

bili_group = on_command("群订阅", priority=19, block=True)

CATS = {1: "一般动态", 2: "专栏文章", 3: "视频", 4: "纯文字", 5: "转发", 6: "直播推送"}


def _usage() -> str:
    return GROUP_SUB_USAGE


def _cat_ids(words: list[str]) -> list[int] | str:
    """把「视频」「专栏文章」这类词换成 Bison 的类别号；写「全部」就是 1~6。"""
    if not words:
        return [1]
    if any(w in ("全部", "所有", "全选") for w in words):
        return [1, 2, 3, 4, 5, 6]
    ids: list[int] = []
    for word in words:
        hit = [cid for cid, name in CATS.items() if word == name or word in name]
        if not hit:
            return f"没听懂「{word}」是哪个类别；能写的是：" + "、".join(CATS.values()) + "（或不写=一般动态）"
        ids.extend(hit)
    return sorted(set(ids))


async def _target_name(target: str) -> str:
    """问 B 站要 UP 的名字；要不到就先用 UID 顶上。"""
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            name = await platform_manager["bilibili"].get_target_name(client, target)
        if name:
            return name
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"bili_group: Bison 取 UP 名字失败 {target}（{type(exc).__name__}）")
    try:  # Bison 那边可能只回「uid 2」，直接问一下名片接口
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/card",
                params={"mid": target},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
            )
            data = resp.json()
        name = ((data.get("data") or {}).get("card") or {}).get("name")
        if name:
            return str(name)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"bili_group: 名片接口取名字失败 {target}（{type(exc).__name__}）")
    return f"UID{target}"


async def _group_label(bot: Bot, group_id: str) -> str:
    try:
        info = await bot.get_group_info(group_id=int(group_id), no_cache=False)
        name = info.get("group_name") or ""
        return f"{group_id}（{name}）" if name else group_id
    except Exception:  # noqa: BLE001
        return group_id


async def _list_subs(bot: Bot, group_id: str) -> str:
    user = TargetQQGroup(group_id=int(group_id))
    subs = await bison_config.list_subscribe(user)
    if not subs:
        return f"{await _group_label(bot, group_id)} 还没订谁。\n{_usage()}"
    lines = [f"{await _group_label(bot, group_id)} 订了 {len(subs)} 个："]
    for idx, sub in enumerate(subs, 1):
        cats = "、".join(CATS.get(int(c), str(c)) for c in (sub.categories or []))
        tags = f"｜标签 {'、'.join(sub.tags)}" if sub.tags else ""
        lines.append(f"{idx}. {sub.target.target_name}（uid {sub.target.target}）{cats}{tags}")
    return "\n".join(lines)


async def _add_sub(bot: Bot, group_id: str, target_text: str, cat_words: list[str]) -> str:
    cats = _cat_ids(cat_words)
    if isinstance(cats, str):
        return cats
    try:
        target = await platform_manager["bilibili"].parse_target(target_text)
    except Exception:  # noqa: BLE001
        return "没认出这个 UP：写纯数字 UID、UID:946974 或 https://space.bilibili.com/946974"
    name = await _target_name(target)
    try:
        await bison_config.add_subscribe(
            TargetQQGroup(group_id=int(group_id)), target, name, "bilibili", cats, []
        )
    except SubscribeDupException:
        return f"{await _group_label(bot, group_id)} 已经订过 {name} 了。"
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"bili_group: 给群 {group_id} 加订阅失败（{type(exc).__name__}: {exc}）")
        return f"没订上（{type(exc).__name__}），稍后再试。"
    cat_text = "、".join(CATS[c] for c in cats)
    return f"给 {await _group_label(bot, group_id)} 订上 {name}（uid {target}）：{cat_text}。"


async def _del_sub(bot: Bot, group_id: str, target_text: str) -> str:
    try:
        target = await platform_manager["bilibili"].parse_target(target_text)
    except Exception:  # noqa: BLE001
        return "要删的话写 UID 或主页链接。"
    try:
        await bison_config.del_subscribe(TargetQQGroup(group_id=int(group_id)), target, "bilibili")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"bili_group: 删订阅失败（{type(exc).__name__}: {exc}）")
        return f"没删掉（{type(exc).__name__}），稍后再试。"
    return f"{await _group_label(bot, group_id)} 取消订阅 uid {target}。"


@bili_group.handle()
async def _handle(bot: Bot, event: Event) -> None:
    if not _BISON_OK:
        return
    if not is_our_bot(event):
        return
    if not devs.is_dev(event.get_user_id()):
        return

    text = event.get_plaintext()
    in_group = getattr(event, "message_type", "") == "group"
    # 群里没写群号就按本群算：/群订阅 → 看本群订了谁，/群订阅 加 946974 → 给本群订
    now_group = str(getattr(event, "group_id", "")) if in_group else ""
    action, group_id, target, cat_words = parse_group_sub(text, default_group=now_group)
    if action == "usage" or not group_id:
        await bili_group.finish(Message(_usage()))

    # 群里只能配本群，免得群友看着你在群里点别的群；私聊随便
    if in_group and str(getattr(event, "group_id", "")) != group_id:
        await bili_group.finish("群里只能配这个群；要给别的群配，私聊我。")

    if action == "list":
        await bili_group.finish(Message(await _list_subs(bot, group_id)))
    if action == "add":
        await bili_group.finish(Message(await _add_sub(bot, group_id, target, cat_words)))
    if action == "del":
        await bili_group.finish(Message(await _del_sub(bot, group_id, target)))
    await bili_group.finish(Message(_usage()))
