"""装饰 B 站推送的合并转发：补正文、补动态链接。

解析插件把动态的正文画进卡片图里，`render_contents()` 只把配图/视频塞进合并转发，
所以「聊天记录」里往往只剩图片。这里在最前面补一条正文，在最后面补一条可跳转的链接。
"""

from __future__ import annotations

import re
from typing import Any

MAX_TEXT = 1200

# 视频、直播、番剧推送走「标题 + 封面 + 链接」，不交给解析插件（解析会合并视频，又慢又大）
_MEDIA_URL = re.compile(
    r"(?:bilibili\.com/video/|b23\.tv/|bilibili\.com/bangumi/|live\.bilibili\.com/)",
    re.I,
)


def is_media_url(url: str) -> bool:
    """视频/直播/番剧链接不解析，直接用 Bison 的标题封面链接。"""
    return bool(_MEDIA_URL.search(url or ""))


def _nodes_text(nodes) -> list[str]:
    from nonebot_plugin_alconna.uniseg import Text

    out: list[str] = []
    for node in nodes:
        for item in getattr(node, "content", None) or ():
            if isinstance(item, Text):
                out.append(item.text)
    return out


def decorate(
    uni: Any,
    text: str,
    url: str = "",
    uid: str = "",
    name: str = "动态转发的消息记录",
) -> Any:
    """给合并转发补正文和链接；没有合并转发、或已经补过就原样返回。"""
    body = (text or "").strip()
    link = (url or "").strip()
    if not body and not link:
        return uni
    try:
        from nonebot_plugin_alconna.uniseg import CustomNode, Reference, Text, UniMessage
    except Exception:  # noqa: BLE001  没装 alconna 就原样返回
        return uni

    def node(what: str) -> CustomNode:
        return CustomNode(uid=str(uid), name=name, content=UniMessage([Text(what)]))

    for index, seg in enumerate(uni):
        if not isinstance(seg, Reference):
            continue
        children = list(seg.children)
        if not children:
            return uni
        texts = _nodes_text(children)
        head: list[CustomNode] = []
        tail: list[CustomNode] = []
        if body and not any(body[:20] in item for item in texts):
            head.append(node(body[:MAX_TEXT]))
        if link and not any(link in item for item in texts):
            tail.append(node(f"传送门：{link}"))
        if not head and not tail:
            return uni
        uni[index] = Reference(nodes=[*head, *children, *tail])
        return uni
    return uni
