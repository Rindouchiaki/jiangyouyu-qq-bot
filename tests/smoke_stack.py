r"""整套冒烟测试：模拟 SnowLuma 连上 NoneBot，发几条消息看机器人怎么回。

不登录 QQ、不调大模型（--start-bot 时用 LLM_MOCK）。CI 和依赖自动更新都跑它，本地也能跑：
    .venv\Scripts\python tests\smoke_stack.py --start-bot            # 自己起一个 NoneBot（不连核心）
    .venv\Scripts\python tests\smoke_stack.py --core                 # 连已经在跑的整套（启动全部.ps1 起的）

检查：/ping、@ 机器人有回复、群里「扫码登录」不往群里发东西；
加 --core 再查：每个游戏插件回帮助图（external.lock.json 里的 help）、临时会话里扫码登录和各插件自己的登录指令的回复都回到临时会话、gscore_guard 认的登录文案都还在源码里。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
from gscore_guard import LOGIN_MARKERS, QR_CAPTION  # noqa: E402

GROUP = 987654321


def env_file() -> dict[str, str]:
    try:
        from dotenv import dotenv_values

        return {k: v or "" for k, v in dotenv_values(ROOT / "bot" / "persona.env").items()}
    except Exception:  # noqa: BLE001
        return {}


class Client:
    """一个假的 SnowLuma：发事件，收机器人调用的 API 并回执。"""

    def __init__(self, url: str, token: str, self_id: int) -> None:
        self.url, self.token, self.self_id = url, token, self_id
        self.ws = None
        self.msg_id = int(time.time()) % 100000 * 1000
        # 测试群的成员：默认有普通群友；测后台指令时换成「全是开发者」
        self.members = [self_id, 10002, 10003]

    async def __aenter__(self) -> "Client":
        headers = {"X-Self-ID": str(self.self_id), "X-Client-Role": "Universal"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.ws = await websockets.connect(self.url, additional_headers=headers, max_size=None, open_timeout=10)
        await self.ws.send(json.dumps({"post_type": "meta_event", "meta_event_type": "lifecycle",
                                       "sub_type": "connect", "time": int(time.time()), "self_id": self.self_id}))
        return self

    async def __aexit__(self, *exc) -> None:
        await self.ws.close()

    async def send(self, text: str, *, user: int = 10002, private: bool = False, temp: bool = False, at: bool = False) -> None:
        if self.ws is None:
            raise RuntimeError("没连上")
        segs = ([{"type": "at", "data": {"qq": str(self.self_id)}}] if at else []) + [{"type": "text", "data": {"text": text}}]
        self.msg_id += 1
        ev = {"post_type": "message", "time": int(time.time()), "self_id": self.self_id, "user_id": user,
              "message_id": self.msg_id, "raw_message": text, "font": 0, "message": segs,
              "sender": {"user_id": user, "nickname": "smoke", "card": "路人甲", "role": "member"}}
        if private:
            ev.update(message_type="private", sub_type="group" if temp else "friend")
            if temp:
                ev["sender"]["group_id"] = GROUP
        else:
            ev.update(message_type="group", sub_type="normal", group_id=GROUP)
        await self.ws.send(json.dumps(ev, ensure_ascii=False))

    async def collect(self, seconds: float, until=None) -> list[dict]:
        """收 seconds 秒内机器人发的消息；until(动作列表) 为真就提前结束。"""
        got: list[dict] = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=deadline - time.time())
            except asyncio.TimeoutError:
                break
            p = json.loads(raw)
            if "action" not in p:
                continue
            params = p.get("params") or {}
            data: dict = {"message_id": 1}
            if p["action"] == "get_group_info":
                data = {"group_id": GROUP, "group_name": "冒烟测试群", "member_count": 3, "max_member_count": 200}
            elif p["action"] in ("get_group_member_info", "get_stranger_info"):
                data = {"user_id": params.get("user_id"), "nickname": "smoke", "card": "", "role": "member"}
            elif p["action"] == "get_group_member_list":
                data = [{"user_id": uid, "nickname": "smoke", "card": "", "role": "member"} for uid in self.members]
            elif p["action"] == "get_group_list":
                data = [{"group_id": GROUP, "group_name": "冒烟测试群", "member_count": len(self.members)}]
            await self.ws.send(json.dumps({"status": "ok", "retcode": 0, "data": data, "echo": p.get("echo")}))
            if p["action"].startswith("send_"):
                got.append({"action": p["action"], **params})
                if until and until(got):
                    break
        return got


def text_of(act: dict) -> str:
    msg = act.get("message", act.get("messages"))
    if isinstance(msg, str):
        return msg
    return json.dumps(msg, ensure_ascii=False)


def is_group(act: dict) -> bool:
    if act["action"] in ("send_group_msg", "send_group_forward_msg"):
        return True
    return act["action"] in ("send_msg", "send_forward_msg") and act.get("message_type") == "group"


def has_image(act: dict) -> bool:
    return '"image"' in text_of(act) or "[CQ:image" in text_of(act)


FAILED: list[str] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + (f"：{detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def plugins_to_check(core_dir: str) -> list[dict]:
    """锁文件里的游戏插件（带 name / help / login）；给了核心目录就只查实际装了的。"""
    lock = json.loads((ROOT / "external.lock.json").read_text(encoding="utf-8"))
    out = []
    for name, item in lock["git"].items():
        if not item.get("help"):
            continue
        if core_dir and not (Path(core_dir) / "gsuid_core" / "plugins" / name).is_dir():
            print(f"SKIP  {name} 没装")
            continue
        out.append({"name": name, **item})
    return out


def wait_port(port: int, seconds: float) -> bool:
    import socket

    deadline = time.time() + seconds
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(1)
    return False


async def run(args, token: str, self_id: int) -> None:
    url = f"ws://127.0.0.1:{args.port}/onebot/v11/ws"
    async with Client(url, token, self_id) as c:
        await c.send("/ping")
        got = await c.collect(15, lambda g: g)
        check(any("pong" in text_of(a) for a in got), "/ping 回 pong", str(got))

        if args.mock:
            await c.send("在吗", at=True, user=10003)
            got = await c.collect(20, lambda g: g)
            check(bool(got) and is_group(got[0]), "@ 机器人有回复", str(got))
            await c.collect(4)  # 一次回复可能拆成几条，等发完再测下一项

            # 私聊连着拆三条发：等说完一起回一次（mock 回复最多拆 3 条），不是一条一回
            start = time.time()
            for part in ("我跟你说", "今天抽卡", "又歪了"):
                await c.send(part, user=10007, private=True)
                await asyncio.sleep(0.4)
            got = await c.collect(20, lambda g: g)
            got += await c.collect(4)
            first = time.time() - start
            check(bool(got) and all(a.get("user_id") == 10007 for a in got), "私聊连发几条有回复", str(got))
            check(len(got) <= 3, "私聊连发几条合成一批回，不是一条一回", f"{len(got)} 条：{got}")
            check(first >= 2, "不秒回：等对方说完再回", f"{first:.1f}s")

            # 后台数据只在全是开发者的对话里给看，而且是先人设说两句再给资料
            dev = 289635657
            await c.send("/小本本", user=dev)
            got = await c.collect(6)
            check(not got, "有普通群友的群里，开发者的 /小本本 也不理", str(got))
            c.members = [c.self_id, dev, 189963059]
            await c.send(f"/关系图 {GROUP}", user=dev)
            got = await c.collect(20, lambda g: any(has_image(a) for a in g))
            got += await c.collect(3)
            check(any(has_image(a) for a in got) and len(got) >= 3, "开发者内部群里 /关系图：人设说话 + 图 + 文字资料", str(got)[:300])
            await c.send("/小本本 10007", user=dev)
            got = await c.collect(6)
            check(len(got) == 1 and "不给翻" in str(got), "内部群里 /小本本 也不给翻日记，只提示删除 / 清空", str(got))
            c.members = [c.self_id, 10002, 10003]
            await c.send("/用量", user=10002, private=True)
            got = await c.collect(5)
            check(not got, "路人私聊 /用量 不理", str(got))
            await c.send("/用量", user=dev, private=True)
            got = await c.collect(15, lambda g: len(g) >= 2)
            check(len(got) >= 2, "开发者私聊 /用量：人设说话 + 数据", str(got))
        else:
            print("SKIP  @ 机器人有回复（persona.env 没开 LLM_MOCK=1，不调真模型）")

        await c.send("扫码登录", user=10004)
        got = await c.collect(6)
        check(not any(is_group(a) for a in got), "群里「扫码登录」不往群里发东西", str(got))
        check(any(a["action"] == "send_private_msg" for a in got), "群里「扫码登录」私聊提醒本人", str(got))

        if not args.core:
            return

        # 每个装了的游戏插件发一次帮助，要回图；核心第一次启动要装依赖、下资源，第一个多等一会儿
        wait = args.core_wait
        plugins = plugins_to_check(args.core_dir)
        for name, help_cmd in ((p["name"], p["help"]) for p in plugins):
            deadline = time.time() + wait
            got = []
            while time.time() < deadline and not got:
                await c.send(help_cmd, user=10005)
                got = await c.collect(30, lambda g: any(has_image(a) for a in g))
                got = [a for a in got if has_image(a)]
            check(bool(got), f"早柚核心回 {help_cmd}（{name}）", f"{wait:.0f} 秒内没回图")
            wait = min(wait, 180)

        await c.send("sr绑定uid 100000001", user=10006, private=True, temp=True)
        bound = await c.collect(30, lambda g: g)
        await c.send("扫码登录", user=10006, private=True, temp=True)
        got = await c.collect(40, lambda g: any(QR_CAPTION in text_of(a) for a in g) and any(has_image(a) for a in g))
        replies = bound + got
        check(bool(got), "临时会话里扫码登录有回复", str(replies))
        check(all(not is_group(a) and a.get("user_id") == 10006 and a.get("group_id") == GROUP for a in replies),
              "核心的回复都回到临时会话（带来源群号）", str(replies))
        if not any(QR_CAPTION in text_of(a) for a in got):
            print("NOTE  没拿到二维码（米游社接口可能连不上），只验证了回复的去向")

        await c.send("扫码 登录", user=10006)
        got = await c.collect(8)
        check(not any(is_group(a) for a in got), "群里带空格的「扫码 登录」也不进群", str(got))

        # 插件自己的登录指令（鸣潮 ww登录 等）：群里不进群、私聊提醒；临时会话里的回复回到临时会话
        for i, p in enumerate(x for x in plugins if x.get("login")):
            cmd, user = p["login"], 10100 + i * 2
            await c.send(cmd, user=user)
            got = await c.collect(8)
            check(not any(is_group(a) for a in got), f"群里「{cmd}」不往群里发东西", str(got))
            check(any(a["action"] == "send_private_msg" and a.get("user_id") == user for a in got),
                  f"群里「{cmd}」私聊提醒本人", str(got))
            await c.send(cmd, user=user + 1, private=True, temp=True)
            got = await c.collect(30, lambda g: g)
            check(bool(got) and all(not is_group(a) and a.get("user_id") == user + 1 and a.get("group_id") == GROUP
                                    for a in got), f"临时会话里「{cmd}」的回复回到临时会话", str(got))

    if args.core_dir:
        # 群内拦截靠插件里写死的登录文案 / 链接认，插件升级改了文案就失效：逐个去源码里找
        sources = [f.read_text(encoding="utf-8", errors="ignore") for f in Path(args.core_dir).glob("gsuid_core/**/*.py")]
        for marker in LOGIN_MARKERS:
            check(any(marker in t for t in sources), f"登录文案「{marker}」还在核心或插件源码里",
                  "gscore_guard.LOGIN_MARKERS 要跟着改")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-bot", action="store_true", help="自己起一个 NoneBot（LLM_MOCK，临时数据目录）")
    ap.add_argument("--core", action="store_true", help="也检查早柚核心")
    ap.add_argument("--core-dir", default="", help="核心目录，用来核对二维码文案")
    ap.add_argument("--core-wait", type=float, default=300)
    ap.add_argument("--port", type=int, default=18080)
    args = ap.parse_args()

    conf = env_file()
    proc = None
    log = None
    if args.start_bot:
        token, self_id = "smoke-token", 100000001
        tmp = Path(tempfile.mkdtemp(prefix="smoke_"))
        env = dict(os.environ, BOT_UIN=str(self_id), LLM_MOCK="1", REPLY_PROB_CALLED="1",
                   ONEBOT_ACCESS_TOKEN=token, PERSONA_DATA_DIR=str(tmp / "data"), BAISHOU_VAULT=str(tmp / "vault"),
                   LOCALSTORE_DATA_DIR=str(tmp / "localstore"),
                   HOST="127.0.0.1", PORT=str(args.port), PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                   GSUID_CORE_REPEAT="true")
        log = open(tmp / "nonebot.log", "wb")
        proc = subprocess.Popen([sys.executable, str(ROOT / "bot" / "bot.py")], env=env, stdout=log, stderr=subprocess.STDOUT)
        if not wait_port(args.port, 180):
            proc.kill()
            print((tmp / "nonebot.log").read_text(encoding="utf-8", errors="replace")[-3000:])
            print("FAIL  NoneBot 180 秒内没起来")
            return 1
    else:
        token = conf.get("ONEBOT_ACCESS_TOKEN", "")
        self_id = int(conf.get("BOT_UIN") or 100000001)
        if not wait_port(args.port, 120):
            print(f"FAIL  {args.port} 没在监听，先启动整套")
            return 1
    # 被叫回复要 LLM_MOCK + 被叫概率 1 才稳定；连真栈时按 persona.env 判断
    args.mock = args.start_bot or (conf.get("LLM_MOCK") == "1" and conf.get("REPLY_PROB_CALLED") == "1")

    try:
        asyncio.run(run(args, token, self_id))
    finally:
        if proc:
            proc.kill()
            proc.wait()
            log.close()
            if FAILED:
                print(Path(log.name).read_text(encoding="utf-8", errors="replace")[-3000:])

    print("\n结果: " + ("全部通过" if not FAILED else f"{len(FAILED)} 项失败"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
