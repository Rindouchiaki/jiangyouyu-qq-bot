"""给推送的合并转发补文字节点的离线测试（不连 QQ）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

import bili_card_text as card_text  # noqa: E402


def _fabrica():
    from nonebot_plugin_alconna.uniseg import CustomNode, Reference, Text, UniMessage

    def node(text):
        return CustomNode(uid="1", name="动态转发的消息记录", content=UniMessage([Text(text)]))

    def image_node():
        from nonebot_plugin_alconna.uniseg import Image

        return CustomNode(uid="1", name="动态转发的消息记录", content=UniMessage([Image(raw=b"x")]))

    return CustomNode, Reference, Text, UniMessage, node, image_node


def main() -> int:
    CustomNode, Reference, Text, UniMessage, node, image_node = _fabrica()

    # 只有图的转发：补一条文字在最前面
    msg = UniMessage([Reference(nodes=[image_node(), image_node()])])
    out = card_text.decorate(msg, "今天的卡组", "https://www.bilibili.com/opus/1", "973264497", "动态转发的消息记录")
    ref = out[0]
    assert len(ref.children) == 4  # 正文 + 2 图 + 传送门
    assert isinstance(ref.children[0].content[0], Text)
    assert ref.children[0].content[0].text == "今天的卡组"
    assert ref.children[0].name == "动态转发的消息记录"

    # 已经有文字的转发：不要重复插
    msg = UniMessage([Reference(nodes=[node("原文"), image_node()])])
    out = card_text.decorate(msg, "原文", "", "973264497", "动态转发的消息记录")
    assert len(out[0].children) == 2

    # 没有正文 / 没有转发：原样返回
    msg = UniMessage([Reference(nodes=[image_node()])])
    assert len(card_text.decorate(msg, "   ", "", "1", "n")[0].children) == 1
    msg = UniMessage(["单纯的文字"])
    assert len(card_text.decorate(msg, "正文", "https://x/1", "1", "n")) == 1

    # 超长正文截到 1200 字
    long_text = "字" * 1300
    msg = UniMessage([Reference(nodes=[image_node()])])
    out = card_text.decorate(msg, long_text, "", "1", "n")
    assert len(out[0].children[0].content[0].text) == card_text.MAX_TEXT

    # 视频/直播/番剧链接不解析
    assert card_text.is_media_url("https://www.bilibili.com/video/BV1xx411c7mD")
    assert card_text.is_media_url("https://b23.tv/abc")
    assert card_text.is_media_url("https://live.bilibili.com/22603245")
    assert card_text.is_media_url("https://www.bilibili.com/bangumi/play/ep123")
    assert not card_text.is_media_url("https://www.bilibili.com/opus/1265310267514814464")

    print("test_bili_card_text: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
