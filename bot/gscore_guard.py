"""早柚核心各游戏登录的拦截判断：纯函数，不依赖 NoneBot，方便单测。"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

# 核心二维码消息的固定开头（gsuid_core/utils/cookie_manager/qrlogin.py）
QR_CAPTION = "请使用米游社扫描下方二维码登录"
# 发往群的消息带这些就当成登录二维码 / 登录链接拦下。都是插件里写死的文案，升级核心或插件后要核对
# （tests/smoke_stack.py --core-dir 会逐个去源码里找）：
LOGIN_MARKERS = (
    QR_CAPTION,
    "/waves/i/",  # 鸣潮 XutheringWavesUID：登录 / 邮箱登录 / 抽卡登录的网页链接（login.py 的 send_login）
    "请用浏览器扫描获取地址",  # 鸣潮开了 WavesQRLogin 时，链接换成二维码的文案
    "请使用森空岛APP扫码登录",  # 终末地 EndUID：森空岛扫码登录（end_bind/__init__.py）
    "/end/i/",  # 终末地配了 EndLoginUrl 时的手机号登录网页链接（end_bind/web_login.py）
    "请用浏览器扫描打开，完成手机号登录",  # 同上，开了 EndQRLogin 时链接换成二维码的文案
)
# 带前缀的登录指令：前缀 -> 前缀后面接的登录词（照各插件 xxx_login / end_bind 里注册的指令抄）
_END_LOGIN = ("扫码登录", "扫码登陆", "扫码登入", "扫码登龙", "扫码login", "扫码dl",
              "登录", "登陆", "登入", "登龙", "login", "dl")
PREFIXED_LOGIN = {
    "ww": ("登录", "登陆", "登入", "登龙", "login", "dl", "邮箱登录", "国际服登录",
           "抽卡登录", "抽卡登陆", "抽卡登入", "云鸣潮登", "云登录", "云登陆", "云登入"),
    "zmd": _END_LOGIN,
    "end": _END_LOGIN,
}
# 会贴出或显示账号凭据的指令：群里也不转给核心，私聊提醒到私聊里发（终末地的「我的cred」只给主人，但会发在问的地方）
_END_PRIVATE = ("绑定", "bind", "我的cred", "查看cred", "获取cred", "我的token", "查看token", "获取token", "获取tk")
PREFIXED_PRIVATE = {
    "ww": ("添加ck", "添加token", "获取ck", "获取token"),
    "zmd": _END_PRIVATE,
    "end": _END_PRIVATE,
}
# 私聊提醒里让对方发的指令：鸣潮的网页登录链接指向本机核心，手机打不开，提示用短信验证码登录
LOGIN_HINTS = {
    "": "扫码登录",
    "ww": "ww登录 手机号,验证码",
    "zmd": "zmd扫码登录",
    "end": "end扫码登录",
}
_BLANKS = " \t\r\n　 "


def command_text(texts: Iterable[str]) -> str:
    """按核心的方式拼指令：各文本段 strip 后直接相连，再去掉所有空白。

    核心会把「扫码 [表情] 登录」拼成「扫码登录」，只看 get_plaintext() 会漏。
    """
    joined = "".join((t or "").strip() for t in texts)
    return "".join(ch for ch in joined if ch not in _BLANKS)


# 核心各插件的常用指令：整句就是这么几个字时，是玩家在发指令，人设别接话
# （带前缀的由 person 插件里的 GAME_CMD_PREFIXES 挡掉，这里补的是不带前缀也被核心认的写法）
BARE_CORE = (
    "绑定", "绑定uid", "绑定设备", "设备登录", "设备登陆", "绑定ck", "添加ck", "删除ck", "我的ck", "我的token",
    "刷新面板", "刷新抽卡记录", "抽卡记录", "签到", "全部签到", "帮助", "面板", "体力", "更新",
)
# 米游社报错里写着「请进行[绑定设备]」，但那是要在核心私聊贴设备 JSON 的指令，照着一句「绑定设备」发没反应
CONFUSING_HINT = {
    "绑定设备": (
        "绑定设备是米游社设备验证，要带 core 前缀贴设备 JSON：core绑定设备 {...}；"
        "只绑游戏 UID 用 zzz绑定uid（星铁 sr绑定uid、原神 gs绑定uid）"
    ),
}


def bare_core_command(texts: Iterable[str]) -> str | None:
    """整句就是一条核心指令（不带前缀的写法）就原样返回，否则 None。"""
    cmd = command_text(texts).lower()
    return cmd if cmd in BARE_CORE else None


def confusing_hint(texts: Iterable[str]) -> str | None:
    """照着核心报错里的错词发的指令，给一句正确说法的提示。"""
    return CONFUSING_HINT.get(command_text(texts).lower())


def _private_cmd(cmd: str) -> str | None:
    """只在私聊用的凭据指令（ww添加token、zmd我的cred 等）原样返回「前缀+指令词」，不是返回 None。"""
    for prefix, words in PREFIXED_PRIVATE.items():
        if cmd.startswith(prefix):
            word = next((w for w in words if cmd[len(prefix):].startswith(w)), None)
            if word:
                return prefix + word
    return None


def login_kind(texts: Iterable[str]) -> str | None:
    """登录或凭据指令就返回它属于哪个前缀（核心自带的扫码登录是 ""），不是返回 None。"""
    cmd = command_text(texts).lower()
    for prefix, words in PREFIXED_LOGIN.items():
        if cmd.startswith(prefix) and cmd[len(prefix):].startswith(words):
            return prefix
    private = _private_cmd(cmd)
    if private:
        return next(p for p in PREFIXED_PRIVATE if private.startswith(p))
    return "" if "扫码登" in cmd else None


def is_login_command(texts: Iterable[str]) -> bool:
    return login_kind(texts) is not None


def login_hint(texts: Iterable[str]) -> str | None:
    """群里发了登录指令时，私聊提醒对方改发的那条指令；不是登录指令返回 None。

    比拦截严：核心自带的扫码登录要整句就是「扫码登录」，「我不会扫码登录」这种聊天不提醒、也不挡人设。
    """
    cmd = command_text(texts).lower()
    kind = login_kind(texts)
    if kind is None or (kind == "" and cmd not in ("扫码登录", "扫码登陆")):
        return None
    if kind and not cmd[len(kind):].startswith(PREFIXED_LOGIN.get(kind, ())):
        # 凭据指令：让对方到私聊发同一条，不回显后面的内容（可能就是凭据）
        return _private_cmd(cmd)
    return LOGIN_HINTS.get(kind, LOGIN_HINTS[""])


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
    """(带登录二维码 / 链接文案, 带图片)。只看文本段，不去序列化整张 base64 图。"""
    caption = image = False
    for seg_type, seg_data in iter_segments({k: data[k] for k in ("message", "messages") if k in data}):
        if seg_type == "text" and any(m in str(seg_data.get("text", "")) for m in LOGIN_MARKERS):
            caption = True
        elif seg_type == "image":
            image = True
    return caption, image
