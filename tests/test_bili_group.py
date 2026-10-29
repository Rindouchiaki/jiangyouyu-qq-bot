"""`/群订阅`、`/私聊订阅` 参数解析的离线测试（不连 QQ、不查订阅库）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

import persona_rules as pr  # noqa: E402


def main() -> int:
    ok = True
    parse = pr.parse_sub_command

    # 私聊里 /群订阅 必须写群号
    assert parse("/群订阅") == ("usage", "", [], [])
    assert parse("") == ("usage", "", [], [])
    assert parse("/群订阅 1234") == ("usage", "", [], [])  # 群号太短，不认
    assert parse("/群订阅 加 946974") == ("usage", "", [], [])
    assert parse("/群订阅 913506590") == ("list", "913506590", [], [])
    assert parse("群订阅 913506590 看") == ("list", "913506590", [], [])
    assert parse("/群订阅 913506590 加 946974") == ("add", "913506590", ["946974"], [])
    assert parse("/群订阅 913506590 添加 946974 视频 专栏文章") == ("add", "913506590", ["946974"], ["视频", "专栏文章"])
    assert parse("/群订阅 913506590 删 946974") == ("del", "913506590", ["946974"], [])
    assert parse("/群订阅 913506590 取关 绝区零") == ("del", "913506590", [], ["绝区零"])
    assert parse("/群订阅 913506590 加") == ("usage", "913506590", [], [])
    assert parse("/群订阅 913506590 加 视频") == ("usage", "913506590", [], [])  # 没写 UP
    assert parse("/群订阅 913506590 随便说说") == ("usage", "", [], [])
    # 一次订好几个，链接、UID: 写法都认，重复的去掉
    assert parse(
        "/群订阅 913506590 加 https://space.bilibili.com/1636034895?spm_id_from=333 UID:946974 946974 直播"
    ) == ("add", "913506590", ["1636034895", "946974"], ["直播"])

    # 群里不写群号 → 按本群算；写了本群群号也认
    g = "913506590"
    assert parse("/群订阅", "群订阅", g) == ("list", g, [], [])
    assert parse("/群订阅 913506590", "群订阅", g) == ("list", g, [], [])
    assert parse("/群订阅 913506590 加 946974", "群订阅", g) == ("add", g, ["946974"], [])
    assert parse("/群订阅 加 946974", "群订阅", g) == ("add", g, ["946974"], [])
    assert parse("/群订阅 删 946974", "群订阅", g) == ("del", g, ["946974"], [])
    assert parse("/群订阅 加 1636034895", "群订阅", g) == ("add", g, ["1636034895"], [])
    # 只写一个别的号：当成别的群，由指令那边提示「群里只能配这个群」
    assert parse("/群订阅 1636034895", "群订阅", g) == ("list", "1636034895", [], [])

    # /私聊订阅：不写 QQ 号就是自己
    me = "289635657"
    assert parse("/私聊订阅", "私聊订阅", me) == ("list", me, [], [])
    assert parse("/私聊订阅 加 946974 视频", "私聊订阅", me) == ("add", me, ["946974"], ["视频"])
    assert parse("/私聊订阅 189963059 加 946974", "私聊订阅", me) == ("add", "189963059", ["946974"], [])
    assert parse("/私聊订阅 189963059", "私聊订阅", me) == ("list", "189963059", [], [])

    assert pr.bili_uid("946974") == "946974"
    assert pr.bili_uid("uid：946974") == "946974"
    assert pr.bili_uid("space.bilibili.com/946974/dynamic") == "946974"
    assert pr.bili_uid("绝区零") == ""

    # 类别：不写 / 全部 = 动态 1~5 + 开播；直播单独走开播提醒
    assert pr.bili_sub_cats([]) == ([1, 2, 3, 4, 5], True)
    assert pr.bili_sub_cats(["全部"]) == ([1, 2, 3, 4, 5], True)
    assert pr.bili_sub_cats(["视频", "专栏"]) == ([2, 3], False)
    assert pr.bili_sub_cats(["直播"]) == ([], True)
    assert isinstance(pr.bili_sub_cats(["番剧"]), str)

    assert pr.bili_cat_name(3) == "视频"
    assert pr.bili_cat_name(6) == "直播推送"
    assert pr.bili_cat_name(9) == "9"

    texts = ["今天发了个图\n来源: B站 绝区零 的转发\n\n详情: https://t.bilibili.com/123", ""]
    assert pr.bili_notice(texts) == "【绝区零】更新了新动态！\n传送门：https://t.bilibili.com/123"
    assert pr.bili_notice(["来源: B站 绝区零"]) == ""  # 没有详情链接不发通知
    assert pr.bili_notice(["详情: https://t.bilibili.com/1"]).startswith("【B站】")

    assert pr.bili_shot_url("1066") == "https://t.bilibili.com/1066"
    assert pr.bili_shot_url(None) == "" and pr.bili_shot_url("") == ""

    assert pr.compact_desc("一行\n\n两行  三行") == "一行 两行 三行"
    assert pr.compact_desc("啊" * 80, 10) == "啊" * 10 + "…"

    assert pr.is_bili_command("/群订阅 913506590")
    assert pr.is_bili_command("/群订阅")
    assert pr.is_bili_command("/私聊订阅 加 946974")
    assert not pr.is_bili_command("群订阅 913506590")
    assert not pr.is_bili_command("/群订阅栏")  # 整词，不能吞掉后面的字
    # 「/订阅」不是 Bison 的指令，人设不该让它
    assert not pr.is_bili_command("/订阅 xxx")

    print("PASS  /群订阅、/私聊订阅 参数解析与指令识别")
    print("结果:", "全部通过" if ok else "有失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
