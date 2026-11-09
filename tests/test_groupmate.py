"""群友档案的离线断言：只用标准库，不连网、不起 NoneBot。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

import groupmate  # noqa: E402


def check_profiles() -> None:
    assert groupmate.active() == "classic"
    assert groupmate.profile() == {}
    cfg = groupmate.profile("groupmate")
    assert cfg["max_chars"] == 26.0
    assert cfg["max_chars_question"] == 48.0
    assert cfg["sticker_only_called_prob"] == 0.42
    assert groupmate.profile("nope") == {}
    print("profiles ok")


def check_overrides() -> None:
    cfg = groupmate.profile("groupmate")
    assert groupmate.int_of(cfg, "max_chars", 20) == 26
    assert groupmate.int_of(cfg, "missing", 20) == 20
    assert groupmate.float_of(cfg, "sticker_only_cooldown", 900.0) == 300.0
    assert groupmate.float_of({}, "sticker_only_prob", 0.5) == 0.5
    print("overrides ok")


def check_sticker_chance() -> None:
    cfg = groupmate.profile("groupmate")
    # 被叫：概率 0.42，掷骰 0.2 触发、0.9 不触发
    assert groupmate.sticker_chance(cfg, called=True, scene=False, rng=0.2) == 0.42
    assert groupmate.sticker_chance(cfg, called=True, scene=False, rng=0.9) == 0.0
    # 没被叫但场景命中：0.45
    assert groupmate.sticker_chance(cfg, called=False, scene=True, rng=0.4) == 0.45
    assert groupmate.sticker_chance(cfg, called=False, scene=True, rng=0.6) == 0.0
    # 没被叫也没场景：不抽
    assert groupmate.sticker_chance(cfg, called=False, scene=False, rng=0.0) == 0.0
    # classic 档案：什么都不触发
    assert groupmate.sticker_chance({}, called=True, scene=True, rng=0.0) == 0.0
    print("sticker chance ok")


def check_env_switch() -> None:
    old = os.environ.get("PERSONA_PROFILE")
    try:
        os.environ["PERSONA_PROFILE"] = "GroupMate"
        assert groupmate.active() == "groupmate"
        os.environ["PERSONA_PROFILE"] = "classic"
        assert groupmate.active() == "classic"
        os.environ.pop("PERSONA_PROFILE")
        assert groupmate.active() == "classic"
    finally:
        if old is None:
            os.environ.pop("PERSONA_PROFILE", None)
        else:
            os.environ["PERSONA_PROFILE"] = old
    print("env switch ok")


def check_polish() -> None:
    assert groupmate.polish("跑一天了啊，累坏了吧。") == "跑一天了啊 累坏了吧"
    assert groupmate.polish("真的吗?!") == "真的吗"
    assert groupmate.polish("好 的") == "好 的"
    print("polish ok")


def main() -> None:
    check_profiles()
    check_overrides()
    check_sticker_chance()
    check_env_switch()
    check_polish()
    print("test_groupmate: 全部通过")


if __name__ == "__main__":
    main()
