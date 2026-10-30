"""影之诗查卡：/卡 卡名（也能直接发卡名之前先 /卡）。

数据是本地那份 `shadowverse_cards_chs.json`（`SV_CARD_DATA` 可改），不联网；
查不到就说没查到，不编。
"""

import time
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

from bot_guard import is_our_bot

import sv_data

card_cmd = on_command("卡", aliases={"卡牌"}, priority=18, block=True)

COOLDOWN_SEC = 3.0
_last: dict[str, float] = {}


def _session_key(event) -> str:
    if getattr(event, "message_type", "") == "group":
        return f"group_{event.group_id}"
    return f"private_{event.get_user_id()}"


@card_cmd.handle()
async def _card(event):
    if not is_our_bot(event):
        return
    key = _session_key(event)
    now = time.time()
    if now - _last.get(key, 0.0) < COOLDOWN_SEC:
        return
    _last[key] = now

    query = event.get_plaintext().strip()
    if not query:
        await card_cmd.finish("用法：/卡 卡名，比如 /卡 天枪深渊")
    hits = sv_data.find(query, limit=8)
    if not hits:
        await card_cmd.finish(f"没查到「{query}」这张卡，名字可能不太对")

    if len(hits) > 1:
        exact = [c for c in hits if c["name"] == query]
        if not exact:
            lines = "、".join(f"{c['name']}（{c['cost']}费 {c['atk']}/{c['life']}）" for c in hits[:5])
            await card_cmd.finish(f"叫「{query}」的有好几张：{lines}\n把名字写全一点我再查")

    card = hits[0]
    text = sv_data.brief(card)
    image = card.get("image") or ""
    if image and Path(image).exists():
        try:
            await card_cmd.send(Message(text) + MessageSegment.image(Path(image).as_uri()))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"sv_card: 卡图没发出去 {type(exc).__name__}: {exc}")
    await card_cmd.finish(text)
