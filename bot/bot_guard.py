"""账号守卫：所有功能只对 BOT_UIN 指定的机器人账号生效；未配置则不过滤。

其它账号（哪怕连到同一个 NoneBot）发来的事件一律忽略。
"""

from __future__ import annotations

import os

BOT_UIN = os.environ.get("BOT_UIN", "").strip()


def is_our_bot(event) -> bool:
    """事件来自的机器人账号是否是本机配置的账号。"""
    sid = str(getattr(event, "self_id", "") or "").strip()
    return (not BOT_UIN) or sid == BOT_UIN
