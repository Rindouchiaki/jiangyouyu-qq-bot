"""gscore_guard 的离线校验：二维码不进群的几条判断。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

from gscore_guard import (  # noqa: E402
    QR_CAPTION,
    bare_core_command,
    has_credential,
    command_text,
    confusing_hint,
    is_group_send,
    is_login_command,
    login_hint,
    login_kind,
    scan_send,
)


class Seg:
    """模拟 MessageSegment：只有 type / data 两个属性。"""

    def __init__(self, type_: str, data: dict) -> None:
        self.type = type_
        self.data = data


def main() -> int:
    # 核心把各文本段 strip 后相连：空格、全角空格、中间夹表情都还是「扫码登录」
    assert command_text(["扫码 ", " 登录"]) == "扫码登录"
    assert is_login_command(["扫码", "登录"]) and is_login_command(["扫码　登陆"])
    assert is_login_command(["core扫码登录"]) and not is_login_command(["扫码枪坏了"])
    print("PASS  is_login_command：按核心的拼法认登录指令")

    # 鸣潮：ww 前缀 + 登录词（网页 / 短信 / 邮箱 / 抽卡登录）都算；ww 的别的指令不算
    for cmd in ("ww登录", "WW 登陆", "ww登录 13800000000,123456", "wwdl", "ww邮箱登录", "ww抽卡登录", "ww云登录"):
        assert login_kind([cmd]) == "ww", cmd
    assert login_kind(["ww帮助"]) is None and login_kind(["www登录"]) is None
    assert login_hint(["ww 登录"]) == "ww登录 手机号,验证码" and login_hint(["扫码", "登录"]) == "扫码登录"
    # 提醒比拦截严：聊天里提到扫码登录不提醒（但群里照样不转给核心）
    assert login_hint(["我不会扫码登录"]) is None and is_login_command(["我不会扫码登录"])
    print("PASS  login_kind / login_hint：带前缀的登录指令和私聊提醒")

    # 终末地：zmd / end 前缀的扫码登录和登录都算，提示到私聊发扫码登录
    for cmd in ("zmd扫码登录", "END 扫码登陆", "zmd登录", "enddl"):
        assert login_kind([cmd]) in ("zmd", "end"), cmd
    assert login_hint(["zmd登录"]) == "zmd扫码登录" and login_hint(["end扫码登录"]) == "end扫码登录"
    assert login_kind(["zmd帮助"]) is None and login_kind(["ending"]) is None
    # 凭据指令：群里不转给核心，提醒原样到私聊发，不带后面的凭据
    assert login_hint(["zmd绑定 abcdef0123456789abcdef0123456789"]) == "zmd绑定"
    assert login_hint(["zmd我的cred"]) == "zmd我的cred" and login_hint(["ww添加token xxx,yyy"]) == "ww添加token"
    assert is_login_command(["end查看token"]) and login_kind(["ww绑定 123456789"]) is None
    print("PASS  终末地登录、凭据指令只在私聊")

    assert is_group_send("send_group_msg", {}) and is_group_send("send_group_forward_msg", {})
    assert is_group_send("send_msg", {"message_type": "group", "group_id": 1})
    assert is_group_send("send_msg", {"group_id": 1, "user_id": 2})
    assert not is_group_send("send_msg", {"message_type": "private", "group_id": 1, "user_id": 2})
    assert not is_group_send("send_private_msg", {"group_id": 1, "user_id": 2})
    print("PASS  is_group_send：群临时会话不算群")

    node = {"type": "node", "data": {"content": [Seg("text", {"text": QR_CAPTION + "："}), Seg("image", {"file": "base64://x"})]}}
    assert scan_send({"messages": [node]}) == (True, True)
    assert scan_send({"message": [Seg("image", {"file": "base64://x"})]}) == (False, True)
    assert scan_send({"message": "二维码登录教程"}) == (False, False)
    assert scan_send({"message": "[CQ:image,file=base64://x]"}) == (False, True)
    assert scan_send({"message": [Seg("text", {"text": "随便聊聊"})]}) == (False, False)
    link = "[鸣潮] 您的id为【10002】 http://localhost:8765/waves/i/abcDEF123 3分钟内有效"
    assert scan_send({"message": [Seg("text", {"text": link})]}) == (True, False)
    assert scan_send({"messages": [{"type": "node", "data": {"content": [Seg("text", {"text": "请用浏览器扫描获取地址"})]}}]})[0]
    skland = "「终末地」 请使用森空岛APP扫码登录，二维码有效时间为2分钟。"
    assert scan_send({"message": [Seg("text", {"text": skland}), Seg("image", {"file": "base64://x"})]}) == (True, True)
    print("PASS  scan_send：转发节点里的二维码文案和图片、鸣潮登录链接都能找到")

    # 不带前缀的核心指令：人设别接话；「绑定设备」是设备验证，照一句发没反应，给正确说法
    assert bare_core_command(["绑定设备"]) == "绑定设备" and bare_core_command(["签到"]) == "签到"
    assert bare_core_command(["设备登录"]) == "设备登录" and bare_core_command(["体力 "]) == "体力"
    assert bare_core_command(["今天天气不错"]) is None
    assert bare_core_command(["绑定设备 123"]) is None  # 带参数就不管，交给人设/核心
    _hint = confusing_hint(["绑定设备"])
    assert _hint is not None and "core绑定设备" in _hint and "zzz绑定uid" in _hint
    assert confusing_hint(["zzz绑定设备"]) is None and confusing_hint(["绑定uid"]) is None
    print("PASS  bare_core_command / confusing_hint：人设不抢核心指令")

    # 凭据：core添加、core / mys 绑定设备、直接贴的 Cookie 和设备 JSON 都不能进日记和模型
    assert has_credential(["core添加 stuid=1;stoken=v2_x;mid=abc"]) and has_credential(["CORE 添加", "ck"])
    assert has_credential(["/core绑定设备 {\"deviceId\": \"x\"}"]) and has_credential(["mys绑定设备 {}"])
    assert has_credential(["mys设备登录 {}"]) and has_credential(["ltuid=1; cookie_token=abc"])
    assert has_credential(['{"deviceFingerprint": "x", "oaid": "y"}'])
    assert not has_credential(["今天抽到了"]) and not has_credential(["mys上签到了吗"]) and not has_credential([""])
    print("PASS  has_credential：Cookie / 设备信息不进人设")

    print("\n结果: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
