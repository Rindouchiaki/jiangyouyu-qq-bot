"""gscore_guard 的离线校验：二维码不进群的几条判断。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

from gscore_guard import (  # noqa: E402
    QR_CAPTION,
    command_text,
    is_group_send,
    is_login_command,
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
    print("PASS  scan_send：转发节点里的二维码文案和图片都能找到")

    print("\n结果: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
