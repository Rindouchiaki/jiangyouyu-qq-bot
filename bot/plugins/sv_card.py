"""影之诗查卡：/卡 卡名、/卡 数据库ID，或者按职业 / 费用·攻击·血量 / 能力词条筛。

数据是本地那份 `shadowverse_cards_chs.json`（`SV_CARD_DATA` 可改），不联网。
命中多张时先给列表（ID 卡名 费用/攻击/血量），再用 /卡 <ID> 看单张的正文和进化前后卡图。
认不准就明说，让对方补个职业、费用或效果里的词，绝不硬猜。
"""

import time
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.params import CommandArg

from bot_guard import is_our_bot

import sv_data

card_cmd = on_command("卡", aliases={"卡牌"}, priority=18, block=True)

COOLDOWN_SEC = 3.0
LIST_LIMIT = 12  # 列表最多列这么多张，再多让对方加条件
_last: dict[str, float] = {}

USAGE = (
    "用法：/卡 卡名（比如 /卡 天枪深渊）、/卡 数据库ID（比如 /卡 10001110）；"
    "也可以筛：/卡 皇 5/4/4 疾驰\n"
    "职业（皇、妖、法、龙、梦、教、超、中立）、费用/攻击/血量（5 或 5/4/4，空着就是不限）、"
    "能力词条可以写几个，比如 /卡 主教 疾驰 守护。"
)
NO_HIT = "没查到「{q}」。可以说说职业、费用，或者效果里的词，我再找找。"


def _session_key(event) -> str:
    if getattr(event, "message_type", "") == "group":
        return f"group_{event.group_id}"
    return f"private_{event.get_user_id()}"


async def _send_list(cards: list[dict], total: int, head: str) -> None:
    """多张先给列表：ID 卡名 费用/攻击/血量。"""
    lines = [f"{head}："] if head else []
    shown = cards[:LIST_LIMIT]
    lines += [sv_data.line(c) for c in shown]
    if total > len(shown):
        lines.append(f"……共 {total} 张，写全一点或者加个条件再筛。")
    if len(shown) > 1 or total > 1:
        lines.append("要看单张的正文和进化前后卡图，回 /卡 <ID>。")
    await card_cmd.send("\n".join(lines))


async def _send_detail(bot: Bot, event: MessageEvent, card: dict, note: str = "") -> None:
    """一张卡：文字 + 进化前后卡图，打包成一条消息记录。"""
    from nonebot_plugin_alconna import UniMessage
    from nonebot_plugin_alconna.uniseg import CustomNode, Image, Reference, Target, Text

    text = sv_data.detail(card)
    if note:
        text = f"{note}\n{text}"
    nodes = [CustomNode(uid=str(bot.self_id), name="影之诗", content=UniMessage([Text(text)]))]
    for label, rel in (("进化前", card.get("image") or ""), ("进化后", card.get("evo_image") or "")):
        if rel and Path(rel).exists():
            nodes.append(
                CustomNode(
                    uid=str(bot.self_id),
                    name="影之诗",
                    content=UniMessage([Text(f"{label}："), Image(path=Path(rel).resolve())]),
                )
            )
    group_id = getattr(event, "group_id", None)
    target = Target(id=str(group_id or event.get_user_id()), private=group_id is None, self_id=str(bot.self_id))
    try:
        await UniMessage(Reference(nodes=nodes)).send(target=target, bot=bot)
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"sv_card: 合并转发没成（{type(exc).__name__}: {exc}），改单条发")
    image = card.get("image") or ""
    if image and Path(image).exists():
        await card_cmd.send(Message(text) + MessageSegment.image(Path(image).as_uri()))
    else:
        await card_cmd.send(text)


@card_cmd.handle()
async def _card(bot: Bot, event: MessageEvent, arg: Message = CommandArg()):
    if not is_our_bot(event):
        return
    key = _session_key(event)
    now = time.time()
    if now - _last.get(key, 0.0) < COOLDOWN_SEC:
        return
    _last[key] = now

    query = arg.extract_plain_text().strip()
    if not query:
        await card_cmd.finish(USAGE)

    # 0. 纯数字当数据库 ID：直接锁定那一张
    if query.isdigit():
        card = sv_data.by_id(query)
        if not card:
            await card_cmd.finish(f"没有 ID 是 {query} 的卡，确认一下再试。")
        await _send_detail(bot, event, card)
        return

    spec = sv_data.parse_filters(query)
    if sv_data.has_filters(spec):
        cards, total = sv_data.filter_cards(spec, LIST_LIMIT)
        label = sv_data.describe_filters(spec)
        if not cards and spec.get("names"):
            # 「皇 天枪深渊」这种：条件对不上时退回按名字找一次
            hits = sv_data.search(" ".join(spec["names"]), limit=8)
            cards = [card for _, card, _ in hits if not spec["cls"] or card["class"] in spec["cls"]]
            total = len(cards)
            label += "（名字那条条件放宽了）"
        if not cards:
            await card_cmd.finish(f"没找到符合条件的卡：{label}。条件松一点再试试？")
        if total == 1:
            await _send_detail(bot, event, cards[0], label)
            return
        await _send_list(cards, total, label)
        return

    hits = sv_data.search(query, limit=8)
    if not hits:
        await card_cmd.finish(NO_HIT.format(q=query))

    # 1. 名字完全一样：直接给这张
    exact = [card for score, card, why in hits if why == "exact"]
    if exact:
        await _send_detail(bot, event, exact[0])
        return

    # 2. 名字里含这个词的（开头的排前面）：只有一张就给详情，多张给列表
    inside = [card for score, card, why in hits if why in ("prefix", "inner")]
    if len(inside) == 1:
        await _send_detail(bot, event, inside[0])
        return
    if len(inside) > 1:
        await _send_list(inside, len(inside), f"「{query}」对上 {len(inside)} 张")
        return

    # 3. 效果文本里提到这个词：列出来（先说一共有多少张）
    skill_cards, skill_total = sv_data.skill_matches(query, limit=LIST_LIMIT)
    if skill_cards:
        if skill_total == 1:
            await _send_detail(bot, event, skill_cards[0], f"能力里提到「{query}」的卡：")
            return
        await _send_list(skill_cards, skill_total, f"能力里提到「{query}」的卡")
        return

    # 4. 只剩名字相近：够像、且比第二名明显像，才按最像的给，并说明
    best_score, best_card, _ = hits[0]
    second = hits[1][0] if len(hits) > 1 else 0
    if best_score >= 78 and (second == 0 or best_score - second >= 5):
        await _send_detail(bot, event, best_card, "名字没完全对上，按最像的这张找的：")
        return

    # 5. 认不准：把候选列出来，请对方补信息
    await _send_list([card for _, card, _ in hits], len(hits), f"不敢确定「{query}」是哪张，候选")
    await card_cmd.finish("补一句职业、几费，或者效果里怎么说？")
