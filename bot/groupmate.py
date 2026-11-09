"""群像档案：把「像普通群友」的一组回复参数收在一处，用 `PERSONA_PROFILE` 切换。

原参数都在 `bot/persona.env` 里（classic 档案，保持原行为）。`groupmate` 只是覆盖几个数字，
不改任何提示词和流程；出问题把 `PERSONA_PROFILE` 删掉或写回 `classic`，重启即回到原样。

依据（2026-11-08 23:05 ~ 11-09 08:43，群 532193003，另一个机器人 3265642025 的 21 条主动发言）：

- 文字 8 条，长度 4–16 字，平均 11 字，没有标点，用空格断句；
- 图片 10 条（占 48%），全是只发一张图，不带文字；
- 引用+@ 只在「回答某一个人的问题」时出现（1 条）；
- 其余全是没人叫它就自己插话，间隔从几分钟到半小时不等。

所以这里的三条调整：文字更短、被叫也可能只回一张图、图片回应不再只限「有明显场景」。
"""

from __future__ import annotations

import os
import random

PROFILES: dict[str, dict[str, float]] = {
    # 原本的行为，不覆盖任何参数
    "classic": {},
    # 更像群友：话更短、被叫也能只甩一张图
    "groupmate": {
        "max_chars": 14.0,
        "max_chars_question": 32.0,
        "sticker_only_prob": 0.5,
        "sticker_only_cooldown": 300.0,
        "sticker_only_called_prob": 0.35,
    },
}

DEFAULT = "classic"


def active() -> str:
    """当前档案名；没设就是 classic。"""
    name = (os.getenv("PERSONA_PROFILE") or DEFAULT).strip().lower()
    return name if name in PROFILES else DEFAULT


def profile(name: str | None = None) -> dict[str, float]:
    """取档案的覆盖值，未知档案返回空字典（等同 classic）。"""
    return dict(PROFILES.get((name or active()).strip().lower(), {}))


def int_of(cfg: dict[str, float], key: str, fallback: int) -> int:
    value = cfg.get(key)
    return fallback if value is None else int(value)


def float_of(cfg: dict[str, float], key: str, fallback: float) -> float:
    value = cfg.get(key)
    return fallback if value is None else float(value)


def sticker_chance(cfg: dict[str, float], *, called: bool, scene: bool, rng: float | None = None) -> float:
    """这一次只回一张表情的概率；0 表示不抽。"""
    roll = random.random() if rng is None else rng
    if called:
        chance = float_of(cfg, "sticker_only_called_prob", 0.0)
    elif scene:
        chance = float_of(cfg, "sticker_only_prob", 0.0)
    else:
        chance = 0.0
    return chance if roll < chance else 0.0
