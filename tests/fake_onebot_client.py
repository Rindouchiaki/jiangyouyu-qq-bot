r"""模拟 SnowLuma 的反向 WebSocket 客户端，验证 NoneBot2 链路。

默认：发 "/ping" 群消息，等插件回 send_msg（验证框架链路）。
带 --at-me：把消息换成「@机器人 在吗」，用来验证 persona 插件的回复规则。

用法：
    python fake_onebot_client.py --token <TOKEN>
    python fake_onebot_client.py --token <TOKEN> --self-id 100000001 --at-me --text "在吗" --url ws://127.0.0.1:18081/onebot/v11/ws
"""

import argparse
import asyncio
import json
import time

import websockets

PRIVATE_MODE = False
DEFAULT_URL = "ws://127.0.0.1:18080/onebot/v11/ws"
GROUP_ID = 987654321
USER_ID = 10002


def make_group_event(text: str, self_id: int, at_me: bool, user_id: int = USER_ID, card: str = "路人甲", group_id: int = None, image: str = "") -> dict:
    segments = []
    if at_me:
        segments.append({"type": "at", "data": {"qq": str(self_id)}})
        segments.append({"type": "text", "data": {"text": f" {text}"}})
        raw = f"[CQ:at,qq={self_id}] {text}"
    elif text:
        segments.append({"type": "text", "data": {"text": text}})
        raw = text
    else:
        raw = ""
    if image:
        segments.append({"type": "image", "data": {"file": image}})
        raw += f"[CQ:image,file={image}]"

    return {
        "post_type": "message",
        "message_type": "private" if PRIVATE_MODE else "group",
        "sub_type": "normal",
        "time": int(time.time()),
        "self_id": self_id,
        "group_id": GROUP_ID if group_id is None else group_id,
        "user_id": user_id,
        "message_id": 1,
        "raw_message": raw,
        "font": 0,
        "message": segments,
        "sender": {
            "user_id": user_id,
            "nickname": "fake-user",
            "card": card,
            "role": "member",
        },
    }


async def run(url: str, token: str, text: str, self_id: int, at_me: bool, timeout: float, user_id: int = USER_ID, collect: int = 1, card: str = "路人甲", group_id: int | None = None, image: str = "") -> int:
    headers = {
        "X-Self-ID": str(self_id),
        "X-Client-Role": "Universal",
        "User-Agent": "OneBot/11 fake-snowluma",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with websockets.connect(
            url, additional_headers=headers, open_timeout=5, close_timeout=3
        ) as ws:
            print(f"[OK] 握手成功 -> {url} (self_id={self_id})")

            await ws.send(json.dumps({
                "post_type": "meta_event",
                "meta_event_type": "lifecycle",
                "sub_type": "connect",
                "time": int(time.time()),
                "self_id": self_id,
            }))

            event = make_group_event(text, self_id, at_me, user_id, card, group_id, image)
            print(f"[..] 发送: {event['raw_message']}")
            await ws.send(json.dumps(event, ensure_ascii=False))

            got = 0
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(), timeout=max(0.1, deadline - time.time())
                    )
                except asyncio.TimeoutError:
                    break
                if not isinstance(raw, str):
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if "action" in payload:
                    action_name = payload.get("action")
                    params = payload.get("params") or {}

                    # 解析类插件会先查群信息来渲染卡片，这里给个通用假数据并继续
                    if action_name in ("get_group_info", "get_group_member_info", "get_stranger_info"):
                        canned = {
                            "get_group_info": {
                                "group_id": GROUP_ID if group_id is None else group_id, "group_name": "测试群",
                                "member_count": 3, "max_member_count": 200,
                            },
                            "get_group_member_info": {
                                "group_id": GROUP_ID if group_id is None else group_id, "user_id": params.get("user_id", USER_ID),
                                "nickname": "fake-user", "card": "路人甲", "role": "member",
                            },
                            "get_stranger_info": {
                                "user_id": params.get("user_id", USER_ID),
                                "nickname": "fake-user",
                            },
                        }[action_name]
                        await ws.send(json.dumps({
                            "status": "ok", "retcode": 0, "data": canned,
                            "echo": payload.get("echo"),
                        }))
                        continue

                    msg = params.get("message")
                    text_out = ""
                    if isinstance(msg, list):
                        text_out = "".join(
                            str(seg.get("data", {}).get("text", ""))
                            for seg in msg
                            if isinstance(seg, dict) and seg.get("type") == "text"
                        )
                    elif isinstance(msg, str):
                        text_out = msg
                    segs = [seg.get("type") for seg in msg if isinstance(seg, dict)] if isinstance(msg, list) else []
                    print(f"[OK] 收到动作: {payload['action']}  文本={text_out!r} ({len(text_out)}字) 段={segs}")

                    # OneBot 反向 WS：应用端必须回执，否则服务端的 call_api 会一直等
                    await ws.send(json.dumps({
                        "status": "ok",
                        "retcode": 0,
                        "data": {"message_id": 900001 + got},
                        "echo": payload.get("echo"),
                    }))

                    got += 1
                    if got >= collect:
                        return 0

            print(f"[FAIL] 超时：只收到 {got}/{collect} 个动作")
            return 1
    except Exception as exc:  # noqa: BLE001 - 诊断脚本
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--token", default="")
    parser.add_argument("--text", default="/ping")
    parser.add_argument("--self-id", type=int, default=10001)
    parser.add_argument("--at-me", action="store_true")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--user-id", type=int, default=USER_ID)
    parser.add_argument("--collect", type=int, default=1, help="收几个动作后退出")
    parser.add_argument("--card", default="路人甲", help="群名片")
    parser.add_argument("--expect-reject", action="store_true")
    parser.add_argument("--private", action="store_true", help="按私聊消息发送")
    parser.add_argument("--group-id", type=int, default=None, help="群号（默认 987654321）")
    parser.add_argument("--image", default="", help="附带图片的 file:// URI")
    args = parser.parse_args()
    global PRIVATE_MODE
    PRIVATE_MODE = args.private

    code = asyncio.run(
        run(args.url, args.token, args.text, args.self_id, args.at_me, args.timeout, args.user_id, args.collect, args.card, args.group_id, args.image)
    )

    if args.expect_reject:
        print("[PASS] 错误 token 已被拒绝" if code != 0 else "[FAIL] 错误 token 竟然连上了")
        return 0 if code != 0 else 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())





