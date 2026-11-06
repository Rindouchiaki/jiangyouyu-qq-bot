"""影之诗查卡：/卡 卡名，或者按职业 / 费用·攻击·血量 / 能力词条筛。

数据是本地那份 `shadowverse_cards_chs.json`（`SV_CARD_DATA` 可改），不联网。
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
MAX_LIST = 4  # 一条消息记录里最多放几张卡
_last: dict[str, float] = {}

USAGE = (
    "用法：/卡 卡名，比如 /卡 天枪深渊；也可以筛：/卡 皇 5/4/4 疾驰\n"
    "职业（皇、妖、法、龙、梦、教、超、中立）、费用/攻击/血量（5 或 5/4/4，没写的空着）、"
    "能力词条可以写几个，比如 /卡 主教 疾驰 守护。"
)
NO_HIT = "没查到「{q}」。可以说说职业、费用，或者效果里的词，我再找找。"


def _session_key(event) -> str:
    if getattr(event, "message_type", "") == "group":
        return f"group_{event.group_id}"
    return f"private_{event.get_user_id()}"


def _card_text(card: dict) -> str:
    return sv_data.detail(card)


async def _send_card(card: dict, note: str = "") -> None:
    """一张卡：文字 + 卡图，发在一条消息里。"""
    text = _card_text(card)
    if note:
        text = f"{note}\n{text}"
    image = card.get("image") or ""
    if image and Path(image).exists():
        try:
            await card_cmd.send(Message(text) + MessageSegment.image(Path(image).as_uri()))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"sv_card: 卡图没发出去 {type(exc).__name__}: {exc}")
    await card_cmd.send(text)


async def _send_forward(bot: Bot, event: MessageEvent, head: str, cards: list[dict]) -> bool:
    """多张卡打包成一条「聊天记录」：每张卡一个文字节点 + 一个卡图节点。"""
    from nonebot_plugin_alconna import UniMessage
    from nonebot_plugin_alconna.uniseg import CustomNode, Image, Reference, Target, Text

    nodes = [CustomNode(uid=str(bot.self_id), name="影之诗", content=UniMessage([Text(head)]))]
    for card in cards:
        nodes.append(
            CustomNode(uid=str(bot.self_id), name="影之诗", content=UniMessage([Text(_card_text(card))]))
        )
        image = card.get("image") or ""
        if image and Path(image).exists():
            nodes.append(
                CustomNode(
                    uid=str(bot.self_id),
                    name="影之诗",
                    content=UniMessage([Image(path=Path(image).resolve())]),
                )
            )
    group_id = getattr(event, "group_id", None)
    target = Target(id=str(group_id or event.get_user_id()), private=group_id is None, self_id=str(bot.self_id))
    await UniMessage(Reference(nodes=nodes)).send(target=target, bot=bot)
    return True


async def _send_many(bot: Bot, event: MessageEvent, head: str, cards: list[dict]) -> None:
    try:
        if await _send_forward(bot, event, head, cards):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"sv_card: 合并转发没成（{type(exc).__name__}: {exc}），改逐条发")
    for card in cards:
        await _send_card(card)


def _names(cards: list[dict], limit: int = 8) -> str:
    return "、".join(c["name"] for c in cards[:limit])


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

    spec = sv_data.parse_filters(query)
    if sv_data.has_filters(spec):
        cards, total = sv_data.filter_cards(spec, MAX_LIST)
        label = sv_data.describe_filters(spec)
        if not cards and spec.get("names"):
            # 「皇 天枪深渊」这种：条件对不上时退回按名字找一次
            hits = sv_data.search(" ".join(spec["names"]), limit=8)
            cards = [card for _, card, _ in hits if not spec["cls"] or card["class"] in spec["cls"]]
            total = len(cards)
            cards = cards[:MAX_LIST]
            label += "（名字那条条件放宽了）"
        if not cards:
            await card_cmd.finish(f"没找到符合条件的卡：{label}。条件松一点再试试？")
        head = f"{label} 共 {total} 张"
        if total > len(cards):
            head += "，先看这几张"
        if len(cards) == 1:
            await _send_card(cards[0], head + "：")
            return
        await _send_many(bot, event, head + "：", cards)
        return

    hits = sv_data.search(query, limit=8)
    if not hits:
        await card_cmd.finish(NO_HIT.format(q=query))

    # 1. 名字完全一样：直接给这张
    exact = [card for score, card, _ in hits if score >= sv_data.SCORE_EXACT]
    if exact:
        await _send_card(exact[0])
        return

    # 2. 名字里含这个词的（开头的排前面）
    inside = [(score, card) for score, card, why in hits if why in ("prefix", "inner")]
    if len(inside) == 1:
        await _send_card(inside[0][1])
        return
    if 2 <= len(inside) <= MAX_LIST:
        await _send_many(bot, event, f"「{query}」对上这几张（{len(inside)} 张）：", [card for _, card in inside])
        return
    if len(inside) > MAX_LIST:
        await card_cmd.finish(
            f"叫「{query}」的有 {len(inside)} 张以上：{_names([c for _, c in inside])}\n"
            "说清楚是哪张，或者补个职业、费用？"
        )

    # 3. 效果文本里提到这个词：把这些卡一并给出来（先说一共有多少张）
    skill_cards, skill_total = sv_data.skill_matches(query, limit=MAX_LIST)
    if skill_cards:
        head = f"能力里提到「{query}」的卡"
        head += f"有 {skill_total} 张，先给这几张：" if skill_total > len(skill_cards) else f"（{skill_total} 张）："
        await _send_many(bot, event, head, skill_cards)
        return

    # 4. 只剩名字相近：够像、且比第二名明显像，才按最像的给，并说明
    best_score, best_card, _ = hits[0]
    second = hits[1][0] if len(hits) > 1 else 0
    if best_score >= 78 and (second == 0 or best_score - second >= 5):
        await _send_card(best_card, "名字没完全对上，按最像的这张找的：")
        return

    # 5. 认不准：把候选念一遍，请对方补信息
    await card_cmd.finish(
        f"不敢确定「{query}」是哪张，像的这几张：{_names([c for _, c, _ in hits])}\n"
        "补一句职业、几费，或者效果里怎么说？"
    )
