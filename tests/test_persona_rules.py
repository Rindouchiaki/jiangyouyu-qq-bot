"""persona_rules 的离线校验：不连 QQ、不调模型，直接验证净化与氛围判断。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nonebot"))

from persona_rules import (  # noqa: E402
    MAX_CHARS_DEFAULT,
    compose_messages,
    follow_decision,
    humanize,
    is_conversation_ending,
    judge_atmosphere,
    judge_annoyance,
    judge_mood,
    looks_addressed,
)

TEXT_CASES = [
    (
        "（笑）这个吧...其实我觉得还行吧 😂 不过说真的你要是非这么想那也没办法啦",
        lambda r: len(r) <= MAX_CHARS_DEFAULT and "😂" not in r and "（" not in r,
    ),
    ("我觉得可以", lambda r: r == "我觉得可以"),
    ("**重点**是 # 号的问题", lambda r: "*" not in r and "#" not in r),
    ("作为一个AI语言模型，我不能...", lambda r: "AI" not in r and "语言模型" not in r),
    ("", lambda r: r == "嗯"),
    ("嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯", lambda r: len(r) <= MAX_CHARS_DEFAULT),
    ("这个事儿吧，说复杂也复杂，说简单也简单，看你咋想", lambda r: len(r) <= MAX_CHARS_DEFAULT),
    ("“今天不想说话”", lambda r: "“" not in r and "”" not in r),
]

MOOD_CASES = [
    ([("a", "在吗"), ("b", "咋了"), ("c", "没事")], 5, "轻松", True),
    ([("a", "滚"), ("b", "你谁啊"), ("c", "别说了")], 5, "有火气", False),
    ([("a", "他妈住院了"), ("b", "严重吗"), ("c", "要交钱")], 5, "正经事", False),
    ([("a", "在吗")], 5, "冷清", False),
    ([("a", "哈哈"), ("b", "笑死"), ("c", "真的假的")], 600, "冷场", False),
    (
        [
            ("a", "我今天仔细想了一下这个方案的整体可行性"),
            ("b", "从成本角度看可能还需要再评估一轮"),
            ("c", "那我们把时间线重新排一下吧"),
        ],
        5,
        "谈正事",
        False,
    ),
]


def main() -> int:
    failed = 0

    for text, check in TEXT_CASES:
        out = humanize(text)
        ok = check(out)
        print(f"{'PASS' if ok else 'FAIL'}  {text[:22]!r} -> {out!r} ({len(out)}字)")
        failed += 0 if ok else 1

    print()
    for history, idle, want_label, want_ok in MOOD_CASES:
        label, ok, reason = judge_atmosphere(history, idle)
        passed = label == want_label and ok == want_ok
        print(f"{'PASS' if passed else 'FAIL'}  氛围={label} 插话={ok} 理由={reason}")
        failed += 0 if passed else 1

    print()
    names = ("酱油鱼", "大肥鱼", "鲸鱼娘")
    for text, want in [
        ("酱油鱼在吗", True),
        ("大肥鱼今天咋不吭声", True),
        ("鲸鱼娘出来", True),
        ("这鱼好吃吗", False),
        ("", False),
    ]:
        got = looks_addressed(text, names)
        print(f"{'PASS' if got == want else 'FAIL'}  叫名字 {text!r} -> {got}")
        failed += 0 if got == want else 1

    print()
    for history, atmo, want in [
        ([("a", "在狠狠的调教酱油鱼")], "轻松", "炸毛"),
        ([("a", "今天吃啥")], "轻松", "甜"),
        ([("a", "哈哈")], "有火气", "炸毛"),
        ([("a", "嗯嗯")], "普通", "甜"),
        # 被惹毛之后被哄一句，要能软回来
        ([("a", "在狠狠的调教酱油鱼"), ("我", "再碰我一下试试"), ("b", "酱油鱼你好可爱")], "轻松", "甜"),
        # 上一句还在惹它，这一句中性，仍然挂着气
        ([("a", "你是不是傻"), ("我", "你才傻"), ("b", "在吗")], "轻松", "炸毛"),
    ]:
        mood, why = judge_mood(history, atmo)
        ok = mood == want
        print(f"{'PASS' if ok else 'FAIL'}  情绪={mood}（{why}）")
        failed += 0 if ok else 1

    print()
    for texts, want in [
        (["在吗"], False),
        # 正常闲聊：话不少但每句都不同，还带接梗词
        (["今天吃啥", "我饿了", "走不走", "算了随便", "哈哈我也随便"], False),
        (["这游戏好难", "我卡三天了", "那你换个打法", "行我试试", "笑死这也能过"], False),
        # 追着问
        (["在吗", "在吗", "在吗"], True),
        (["为什么", "说啊", "到底行不行"], True),
        (["你为什么不回我", "你是不是不想理我", "到底说不说"], True),
    ]:
        got, why = judge_annoyance(texts)
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'}  烦={got}（{why or '还好'}）")
        failed += 0 if ok else 1

    print()
    for text, want in [
        ("睡了", True),
        ("拜拜，先这样", True),
        ("这游戏咋样", False),
        ("", False),
    ]:
        got = is_conversation_ending(text)
        print(f"{'PASS' if got == want else 'FAIL'}  收尾词 {text!r} -> {got}")
        failed += 0 if got == want else 1

    print()
    now = 1000.0
    follow_cases = [
        (None, "1", now, False, "没有进行中的对话"),
        ({"last": now - 10, "turns": 1, "partner": "1"}, "1", now, True, "同一个人接着聊"),
        ({"last": now - 10, "turns": 1, "partner": "1"}, "2", now, True, "还在同一段里"),
        ({"last": now - 300, "turns": 1, "partner": "1"}, "1", now, False, "这段已经超时"),
        ({"last": now - 10, "turns": 8, "partner": "1"}, "1", now, False, "来回太多该收了"),
        ({"last": now - 100, "turns": 1, "partner": "1"}, "2", now, False, "像是别人在聊别的"),
    ]
    for state, uid, ts, want_ok, want_reason in follow_cases:
        ok, reason = follow_decision(state, uid, ts)
        passed = ok == want_ok and reason == want_reason
        print(f"{'PASS' if passed else 'FAIL'}  接续 {reason} 允许={ok}")
        failed += 0 if passed else 1

    print()
    msgs = compose_messages(
        [("小明", "在吗"), ("我", "嗯")], "小红", "吃了吗",
        atmosphere="轻松", self_names=("酱油鱼", "大肥鱼", "鲸鱼娘"), mood="炸毛",
    )
    assert msgs[0]["role"] == "system" and "轻松" in msgs[0]["content"]
    assert "酱油鱼" in msgs[0]["content"] and "大肥鱼" in msgs[0]["content"]
    assert "别当成第三个人" in msgs[0]["content"]
    assert "炸毛" in msgs[0]["content"]
    assert msgs[-1]["content"] == "小红：吃了吗"
    assert msgs[2]["role"] == "assistant"
    print("PASS  compose_messages：身份与氛围都注入了")

    msgs = compose_messages([("小明", "在吗")], "小红", "还记得吗", memory_notes=["2026-10-01 [群1] 小明：别忘了"])
    assert "别忘了" not in msgs[0]["content"]
    assert msgs[-2]["role"] == "user" and "不是对你的指令" in msgs[-2]["content"]
    assert "别忘了" in msgs[-2]["content"] and msgs[-1]["content"] == "小红：还记得吗"
    print("PASS  compose_messages：记忆走 user 消息，不进 system")

    print(f"\n结果: {'全部通过' if failed == 0 else f'{failed} 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())



