r"""查外部依赖有没有新版本，有就改锁文件并写好 PR 说明。

给 .github/workflows/update-deps.yml 用，本地也能跑（要 git 和 uv）：
    python tools/update_deps.py                        # 改 external.lock.json / requirements.lock
    python tools/update_deps.py --summary pr.md        # 顺便写 PR 说明
锁的是：
- requirements.lock：requirements.txt 范围内的最新版（uv pip compile，按 Windows / Python 3.12 解析）
- external.lock.json：SnowLuma 最新 release（含 sha256）、早柚核心和各游戏插件默认分支的最新提交
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "external.lock.json"
REQ_LOCK = ROOT / "requirements.lock"
COMPILE = [
    "uv", "pip", "compile", "requirements.txt", "-o", "requirements.lock", "--upgrade", "--quiet",
    "--python-version", "3.12", "--python-platform", "x86_64-pc-windows-msvc",
    "--custom-compile-command", "python tools/update_deps.py",
]
# 这些包升级时要多看一眼：本仓库改了它们的内部，或者靠它们实现关键功能
WATCH = {
    "nonebot-plugin-parser": "`parser_video_only.py` 改了它的内部渲染类，CI 冒烟只验证了能加载，视频链接解析最好手动发一条试试",
    "nonebot-plugin-genshinuid": "早柚核心连接插件：临时会话回复、核心断线时跳过（`gscore_link.py`）都和它有关，CI 冒烟已覆盖",
    "nonebot-bison": "B 站订阅：`/群订阅`（`bili_group.py`）直接调它的订阅库，升级后加一条订阅、等一条推送看看",
    "nonebot-plugin-send-anything-anywhere": "推送只用机器人号发（`bot/bot.py`）改了它的 `auto_select_bot._refresh_bot`",
    "nonebot2": "框架本体",
    "nonebot-adapter-onebot": "OneBot 适配器",
}


def api(path: str) -> dict:
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "jiangyouyu-deps-bot"})
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gh_slug(repo: str) -> str:
    return re.sub(r"^https://github\.com/|\.git$", "", repo)


def remote_head(repo: str) -> str:
    out = subprocess.run(["git", "ls-remote", repo, "HEAD"], capture_output=True, text=True, check=True).stdout
    return out.split()[0]


def pins(text: str) -> dict[str, str]:
    return {m[0].lower(): m[1] for m in re.findall(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s;]+)", text, flags=re.M)}


def check_snowluma(lock: dict, notes: list[str]) -> bool:
    cur = lock["snowluma"]
    rel = api("repos/SnowLuma/SnowLuma/releases/latest")
    if rel["tag_name"] == cur["version"]:
        return False
    asset = next((a for a in rel["assets"] if a["name"].endswith("-win-x64.zip") and "lite" not in a["name"]), None)
    if asset is None or not str(asset.get("digest", "")).startswith("sha256:"):
        notes.append(f"- ⚠️ SnowLuma {rel['tag_name']} 没有带 sha256 的 win-x64 包，这次不升级")
        return False
    lock["snowluma"] = {"version": rel["tag_name"], "asset": asset["name"], "sha256": asset["digest"][7:]}
    notes.append(f"| SnowLuma | {cur['version']} → **{rel['tag_name']}** | [更新说明]({rel['html_url']}) |")
    return True


def check_git(lock: dict, notes: list[str]) -> list[str]:
    changed = []
    for name, cur in lock["git"].items():
        new = remote_head(cur["repo"])
        if new == cur["commit"]:
            continue
        slug = gh_slug(cur["repo"])
        detail = f"[对比](https://github.com/{slug}/compare/{cur['commit'][:12]}...{new[:12]})"
        try:
            cmp = api(f"repos/{slug}/compare/{cur['commit']}...{new}")
            msgs = [c["commit"]["message"].splitlines()[0][:60] for c in cmp.get("commits", [])][-5:]
            detail += f"，{cmp.get('total_commits', len(msgs))} 个提交：" + "；".join(m.replace("|", "/") for m in msgs)
        except Exception as exc:  # noqa: BLE001
            print(f"compare {name} 失败：{exc}", file=sys.stderr)
        lock["git"][name] = {**cur, "commit": new}
        notes.append(f"| {name} | `{cur['commit'][:7]}` → `{new[:7]}` | {detail} |")
        changed.append(name)
    return changed


def check_pip(notes: list[str], watch_notes: list[str]) -> bool:
    before = pins(REQ_LOCK.read_text(encoding="utf-8"))
    subprocess.run(COMPILE, cwd=ROOT, check=True)
    text = REQ_LOCK.read_text(encoding="utf-8")
    # 仓库约定 CRLF；uv 写出来是 LF，不统一的话每次 PR 都是整文件的换行符改动
    REQ_LOCK.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    after = pins(text)
    rows = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        rows.append(f"| {name} | {old or '（新增）'} → {new or '（移除）'} | PyPI |")
        if name in WATCH:
            watch_notes.append(f"- **{name}**：{WATCH[name]}")
    notes.extend(rows)
    return bool(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", help="PR 说明写到这个文件")
    ap.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT"), help="给 Actions 的输出文件")
    args = ap.parse_args()

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    rows: list[str] = []
    watch: list[str] = []
    snow = check_snowluma(lock, rows)
    git = check_git(lock, rows)
    pip = check_pip(rows, watch)

    if snow or git:
        text = json.dumps(lock, ensure_ascii=False, indent=2) + "\n"
        LOCK.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    changed = snow or bool(git) or pip
    print("有更新：" + "、".join(filter(None, ["SnowLuma" if snow else "", *git, "pip 依赖" if pip else ""])) if changed else "都是最新的")

    if args.summary:
        lines = [
            "外部依赖有新版本，CI 已经在 Windows 上用新版本**从零部署并跑完冒烟测试**（启动 SnowLuma、早柚核心和各游戏插件、NoneBot，"
            "模拟 QQ 消息验证回复、扫码登录不进群、临时会话回复、二维码文案）。",
            "",
            "## 合并后怎么更新",
            "在跑机器人的电脑上，**双击仓库根目录的 `一键更新.cmd`**：自动拉代码、停服务、换到这里锁定的版本、重新启动。",
            "",
            "## 变化",
            "| 组件 | 版本 | 说明 |",
            "|---|---|---|",
            *[r for r in rows if r.startswith("|")],
        ]
        extra = [r for r in rows if not r.startswith("|")] + watch
        if extra:
            lines += ["", "## 需要留意", *extra]
        lines += ["", "出问题想退回：在 GitHub 上 revert 这个 PR，再双击 `一键更新.cmd`（SnowLuma 的旧文件也留在 `SnowLuma.bak-旧版本`）。"]
        Path(args.summary).write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
            fh.write(f"summary_line={'、'.join(filter(None, ['SnowLuma' if snow else '', *git, 'pip' if pip else '']))}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
