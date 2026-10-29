"""`/群订阅` 参数解析的离线测试（不连 QQ、不查订阅库）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

import persona_rules as pr  # noqa: E402


def main() -> int:
    ok = True

    assert pr.parse_group_sub("/群订阅") == ("usage", "", "", [])
    assert pr.parse_group_sub("") == ("usage", "", "", [])
    assert pr.parse_group_sub("/群订阅 1234") == ("usage", "", "", [])  # 群号太短，不认
    assert pr.parse_group_sub("/群订阅 913506590") == ("list", "913506590", "", [])
    assert pr.parse_group_sub("群订阅 913506590") == ("list", "913506590", "", [])
    assert pr.parse_group_sub("/群订阅 913506590 加 946974") == ("add", "913506590", "946974", [])
    assert pr.parse_group_sub("/群订阅 913506590 添加 946974 视频 专栏文章") == (
        "add",
        "913506590",
        "946974",
        ["视频", "专栏文章"],
    )
    assert pr.parse_group_sub("/群订阅 913506590 删 946974") == ("del", "913506590", "946974", [])
    assert pr.parse_group_sub("/群订阅 913506590 取关 946974") == ("del", "913506590", "946974", [])
    assert pr.parse_group_sub("/群订阅 913506590 加") == ("usage", "913506590", "", [])
    assert pr.parse_group_sub("/群订阅 913506590 随便说说") == ("usage", "913506590", "", [])

    # 群里不写群号 → 按本群算；私聊不写群号 → 还是提示用法
    assert pr.parse_group_sub("/群订阅", "913506590") == ("list", "913506590", "", [])
    assert pr.parse_group_sub("/群订阅 加 946974", "913506590") == ("add", "913506590", "946974", [])
    assert pr.parse_group_sub("/群订阅 删 946974", "913506590") == ("del", "913506590", "946974", [])
    assert pr.parse_group_sub("/群订阅 加 946974") == ("usage", "", "", [])

    assert pr.is_bili_command("/群订阅 913506590")
    assert pr.is_bili_command("/群订阅")
    assert not pr.is_bili_command("群订阅 913506590")
    assert not pr.is_bili_command("/群订阅栏")  # 整词，不能吞掉后面的字

    print("PASS  /群订阅 参数解析与指令识别")
    print("结果:", "全部通过" if ok else "有失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
