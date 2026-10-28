"""开发者名单：个人项目，直接写死在这里，不走 persona.env。

QQ 号 → (群里统一用的名字, 其它叫法...)。开发者专用指令、好感保底（persona_rules.dev_floor）、`/记` 署名都认这里；
所有名字和叫法都不许群友用作群名片冒充（persona_rules.safe_name 的保留名）。
"""

from __future__ import annotations

DEVS: dict[str, tuple[str, ...]] = {
    "289635657": ("酱酱鱼",),
    "189963059": ("小帽", "帽子", "夜雨轩烛"),
}

# 群里统一用的名字（每人一个），提示词和 /记 署名用
DEV_NAMES: tuple[str, ...] = tuple(names[0] for names in DEVS.values())
# 除统一名字外的其它叫法，提示词里告诉模型「说的是同一个人」
DEV_ALIASES: dict[str, tuple[str, ...]] = {names[0]: names[1:] for names in DEVS.values() if len(names) > 1}
# 所有名字和叫法：防冒充的保留名
RESERVED_NAMES: tuple[str, ...] = tuple(n for names in DEVS.values() for n in names)


def is_dev(uid: object) -> bool:
    return str(uid).strip() in DEVS


def only_devs(member_ids: object, bot_id: object = "") -> bool:
    """这个对话里除了机器人自己全是开发者（私聊传对方一个人，群传成员列表）：后台数据只在这种对话里给看。"""
    others = {str(m).strip() for m in member_ids} - {str(bot_id).strip(), ""}
    return bool(others) and all(m in DEVS for m in others)


def dev_name(uid: object) -> str:
    """开发者的统一名字；不是开发者返回空串。"""
    names = DEVS.get(str(uid).strip())
    return names[0] if names else ""
