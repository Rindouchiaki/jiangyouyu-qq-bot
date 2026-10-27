"""早柚核心扫码登录的拦截判断：纯函数，不依赖 NoneBot，方便单测。"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

# 核心二维码消息的固定开头（gsuid_core/utils/cookie_manager/qrlogin.py）；升级核心后要核对，改了文案群内拦截就失效
QR_CAPTION = "请使用米游社扫描下方二维码登录"
_BLANKS = " \t\r\n　 "


def command_text(texts: Iterable[str]) -> str:
    """按核心的方式拼指令：各文本段 strip 后直接相连，再去掉所有空白。

    核心会把「扫码 [表情] 登录」拼成「扫码登录」，只看 get_plaintext() 会漏。
    """
    joined = "".join((t or "").strip() for t in texts)
    return "".join(ch for ch in joined if ch not in _BLANKS)


def is_login_command(texts: Iterable[str]) -> bool:
    return "扫码登" in command_text(texts)


def is_group_send(api: str, data: dict[str, Any]) -> bool:
    """这次 API 调用是不是发往群；口径和 OneBot v11 适配器一致。"""
    if api in ("send_group_msg", "send_group_forward_msg"):
        return True
    if api in ("send_msg", "send_forward_msg"):
        # 群临时会话是 message_type=private 带 group_id，不算群
        mt = data.get("message_type")
        return mt == "group" or (mt is None and bool(data.get("group_id")))
    return False


def iter_segments(obj: Any) -> Iterator[tuple[str, dict]]:
    """把 API 数据里的消息拍平成 (type, data)：兼容 Message / MessageSegment / dict / list / 转发节点。"""
    if obj is None:
        return
    if isinstance(obj, str):
        yield "text", {"text": obj}
        if "[CQ:image" in obj:
            yield "image", {}
        return
    if isinstance(obj, dict):
        if "type" in obj and "data" in obj:
            seg_type, seg_data = str(obj["type"]), obj.get("data") or {}
            yield seg_type, seg_data
            if seg_type == "node":
                yield from iter_segments(seg_data.get("content"))
            return
        for key in ("message", "messages", "content"):
            if key in obj:
                yield from iter_segments(obj[key])
        return
    seg_type, seg_data = getattr(obj, "type", None), getattr(obj, "data", None)
    if isinstance(seg_type, str) and isinstance(seg_data, dict):
        yield seg_type, seg_data
        if seg_type == "node":
            yield from iter_segments(seg_data.get("content"))
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from iter_segments(item)


def scan_send(data: dict[str, Any]) -> tuple[bool, bool]:
    """(带核心二维码文案, 带图片)。只看文本段，不去序列化整张 base64 图。"""
    caption = image = False
    for seg_type, seg_data in iter_segments({k: data[k] for k in ("message", "messages") if k in data}):
        if seg_type == "text" and QR_CAPTION in str(seg_data.get("text", "")):
            caption = True
        elif seg_type == "image":
            image = True
    return caption, image
