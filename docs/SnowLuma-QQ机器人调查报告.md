# SnowLuma 配置 QQ 机器人 · 调查报告

> 调查时间：2026-10-25　|　对象版本：SnowLuma v2.2.0（2026-10-24 发布）
> 本机环境：Windows 11 IoT LTSC 26100，已安装 NTQQ `9.9.21.38711`（`C:\Program Files\Tencent\QQNT\QQ.exe`，当前正在运行 9 个进程），未安装 Node.js，未安装 Docker
> 依据：官方文档（snowluma.github.io）、GitHub 仓库源码（`main` @ 3bd74ac）、GitHub API 实测数据

---

## 0. 一句话结论

**SnowLuma 是「协议端」，不是机器人本体。** 它把已登录的 QQ 客户端 hook 住，转成 OneBot v11 接口；真正的"机器人"（回复逻辑、AI、插件）要另外跑一个框架（NoneBot2 / AstrBot / MaiBot / Koishi）去连它。

对你这台机器的最短路径：

```
C:\Program Files\Tencent\QQNT\QQ.exe（已装、已登录）
        ↓ SnowLuma win-x64 完整版（自带 Node，解压即用，无需装 Node/Docker）
   WebUI :5099  +  OneBot HTTP :3000  +  OneBot WS :3001
        ↓ 反向 WebSocket 或 HTTP
NoneBot2 / AstrBot / MaiBot（真正的机器人）
```

⚠️ 先看第 8 节：SnowLuma 是**源码可见、非 OSI 开源**许可，且属于第三方注入方案，有账号风险。

---

## 1. SnowLuma 是什么

| 项 | 内容 |
| --- | --- |
| 自我定位 | Next Remote Protocol Framework（面向 NTQQ 的「远程协议框架」） |
| 实现语言 | TypeScript / Node.js |
| 原理 | native addon 用 **ptrace 级注入**把 hook 打进正在运行的 QQ 进程，解析其内部数据包 |
| 对外协议 | **OneBot v11**：HTTP API 服务端、WebSocket 服务端、反向 WebSocket 客户端、HTTP 事件上报，可任意组合 |
| 附加能力 | 内置 WebUI、TypeScript SDK（`@snowluma/sdk`）、MCP 服务（`@snowluma/mcp`）、多账号、SQLite 消息存储 |
| 仓库数据 | 2,477 stars，247 open issues→当前 6 个 open issue，持续高频更新（2026-10-25 仍有提交） |
| 版本节奏 | v2.0.0（Node 24 基线、原生接口异步化）→ v2.2.0，几乎每天/每周发版 |
| 项目状态 | 官方自述**早期开发阶段**，接口、配置结构、发行布局都可能变 |

### 生态位（重要）

- 它与 **NapCatQQ / LLBot(原 LLOneBot)** 是同类竞品：都靠 hook NTQQ 出 OneBot。
- NapCatQQ 的 README 里**直接推荐了 SnowLuma**：「可以试试更新更好用的 SnowLuma 作为 NapCat Gui 替代品」——说明二者关系近似"同作者思路的下一代"（SnowLuma 鸣谢里同时提到 LagrangeV2 的协议定义和 NapCatQQ 的实现思路）。
- 它**不是** NoneBot2/Koishi 那种"机器人框架"，不写插件、不做对话逻辑。

### OneBot 动作覆盖面（比标准 v11 更宽）

源码 `packages/onebot/src/actions/` 显示除标准动作外还有扩展：空间说说（`qzone/*`）、群相册（`group-album/*`）、群文件（`group-file/*`）、流式上传/下载（`stream/*`）、系统表情（`sys-face/*`）、群精华/公告等。文档 API 目录：[snowluma.github.io/zh/docs/api](https://snowluma.github.io/zh/docs/api)。

---

## 2. 部署方式怎么选

| 你的环境 | 推荐 | 难度 | 说明 |
| --- | --- | --- | --- |
| **Windows 本机（= 你这台）** | **win-x64 完整版 zip** | 低 | 自带 Node，解压双击 `launcher.bat`；直接注入本机 QQ |
| Linux 服务器 | **官方 Docker 镜像** | 低（官方最推荐） | 镜像内含 Linux QQ + Xvfb + VNC + noVNC + supervisord |
| Windows 但想隔离 | Docker Desktop / WSL2 | 中 | 跑的是 **Linux QQ**，不是本机 QQ |
| 已有 Node 24 | win-x64 **lite** 包 | 低 | 体积小很多 |
| 只有安卓手机 | Termux + proot | 很高（实验性） | 注入可能不可用，不建议 |

**本机结论：用 win-x64 完整版 zip。** 原因：本机没有 Node（lite 包要先装 Node 24），也没有 Docker（Docker 路线要装 Docker Desktop 且跑的是 Linux QQ，还要重新扫码登录，多一层 VNC）。

> 发行包实际资产名（GitHub API 实测）：`SnowLuma-v2.2.0-win-x64.zip` / `SnowLuma-v2.2.0-win-x64-lite.zip` / `SnowLuma-v2.2.0-linux-x64.tar.gz` / `-linux-arm64` / `-lite`。
> ⚠️ **文档写的是 Windows `.tar.gz`，但实际资产是 `.zip`**——别照着文档去找 tar.gz。

---

## 3. 部署实录（Windows 本机，照着做）

### 3.1 下载解压

1. 打开 [Releases](https://github.com/SnowLuma/SnowLuma/releases)，选最新 `win-x64.zip`（**不要** `-lite`）。
2. 解压到固定目录，例如 `C:\SnowLuma\`（解压后根目录应有 `index.mjs`、`launcher.bat`、`webui/`、`native/`、`release.json`）。
3. 仓库里附带了一键脚本可自动完成这一步：`scripts\install-snowluma.ps1`（见第 9 节）。

### 3.2 启动

- 双击 `launcher.bat`（本质是 `node ./index.mjs` + `pause`，方便看日志）；
- 或命令行：`cd C:\SnowLuma` → `node .\index.mjs`。

### 3.3 找 WebUI 首次密码（含首次登录的 EULA 关卡）

- 浏览器开 `http://127.0.0.1:5099/`；
- 密码在**首次启动的控制台/日志**里，实测输出形如：

  ```
  ★ WebUI 初始登录凭据 / Initial WebUI Credentials ★
  initial credentials: user=admin password=<16 位随机串>
  ```
- **只在全新数据目录首次启动时打印一次**，之后不再生成，记下来；
- ⚠️ **首次进 WebUI 会先要求同意 EULA / PRIVACY**（日志：`awaiting EULA/PRIVACY consent before the panel unlocks`），同意后才进入面板——文档没提这一步；
- ⚠️ 初始密码带 `mustChangePassword: true`：**跳过改密的话，下次启动会重新生成随机密码**（旧的作废）。

### 3.4 注入与登录

- SnowLuma 默认 `hookAutoLoad` 会持续探测 `QQ.exe`，发现就注入（先被动观察），扫码登录成功后自动切工作模式；
- **先后顺序无所谓**：先开 QQ 或先开 SnowLuma 都行；
- 登录**只支持扫码**，没有 CLI 登录（Windows 本机直接看 QQ 窗口扫码即可，不需要 VNC）；
- ⚠️ SnowLuma 必须和 QQ 用**同一个 Windows 用户、同样的权限级别**运行，否则注入失败（一个管理员一个非管理员也会失败）。

#### 首次启动实测记录（2026-10-25，本机，`SNOWLUMA_HOOK_AUTOLOAD=0` 被动启动）

启动 20 秒后实际生成：

```
Z:\snowluma\SnowLuma\
├─ config\runtime.json   # 207 B，字段与第 4.2 节完全一致（webuiHost=127.0.0.1 实测确认）
├─ config\webui.json     # 324 B，⚠️ 文档未提及：passwordHash / passwordSalt / mustChangePassword / generatedAt
└─ logs\snowluma-2026-10-25.log
```

监听端口实测：**只有 `127.0.0.1:5099`**。`3000` / `3001` 在没有任何 QQ 账号被 hook + 登录之前**不会监听**——`onebot.json` / `onebot_<uin>.json` 也要等账号载入后才生成。

> 所以「机器人连不上 3000/3001」的第一排查项不是端口或 token，而是：**账号到底有没有被注入并登录成功**。

> `config/webui.json` 是 WebUI 凭据文件，删掉会让密码重置；备份/迁移数据目录时要一起带走。

### 3.5 端口一览

| 端口 | 用途 | 默认监听 |
| --- | --- | --- |
| 5099 | WebUI 管理界面 | 127.0.0.1（Docker 镜像内为 0.0.0.0） |
| 3000 | OneBot v11 HTTP API | 127.0.0.1（Docker 为 0.0.0.0） |
| 3001 | OneBot v11 WebSocket | 127.0.0.1（Docker 为 0.0.0.0） |
| 6081 | noVNC 远程桌面（**仅 Docker**） | 0.0.0.0 |
| 5900 | 原生 VNC（**仅 Docker 内部**，官方模板不映射） | — |

> ❗**默认监听地址的坑**：源码 `packages/onebot/src/config.ts` 的 `makeDefaultOneBotConfig()` 里写的是 `host: '127.0.0.1'`，而文档《介绍》页的表格写 `0.0.0.0:3000`。真实情况是：**非 Docker 安装默认只监听回环**，Docker 镜像入口脚本会改成 `0.0.0.0`。所以要局域网/容器互访，必须自己把 `host` 改成 `0.0.0.0` 或写对 IP。

### 3.6 Docker 路线（若以后搬到服务器）

```yaml
services:
  snowluma:
    image: motricseven7/snowluma:latest
    container_name: snowluma
    restart: unless-stopped
    shm_size: 1gb                      # QQ 是 Chromium，默认 /dev/shm 太小会崩
    cap_add: [SYS_PTRACE]              # 必需：ptrace 注入
    security_opt: ["seccomp=unconfined"] # 必需：默认 seccomp 会拦注入
    environment:
      SNOWLUMA_WEBUI_HOST: 0.0.0.0
      SNOWLUMA_WEBUI_PORT: 5099
      SNOWLUMA_HOOK_AUTOLOAD: 1
      SNOWLUMA_LOG_LEVEL: info
      TZ: Asia/Shanghai
    ports:
      - "6081:6081"   # noVNC 扫码
      - "5099:5099"   # WebUI
      - "3000:3000"   # OneBot HTTP
      - "3001:3001"   # OneBot WS
    volumes:
      - qq-gateway-data:/app/data           # SnowLuma 配置/缓存
      - qq-client-config:/app/.config       # QQ 客户端配置
      - qq-client-data:/app/.local/share    # QQ 登录态
volumes:
  qq-gateway-data: { name: qq-gateway-data }
  qq-client-config: { name: qq-client-config }
  qq-client-data: { name: qq-client-data }
```

- 远程桌面密码（noVNC）：不设 `VNC_PASSWD` 时首次启动随机生成，**只在日志打印一次**：
  `docker logs snowluma 2>&1 | grep -E "远程桌面密码:|remote desktop password:" | tail -n 1`
- 多账号：Linux QQ 单实例锁在 `$HOME/.config/QQ/SingletonLock`，必须给每个账号**独立 HOME** + `SNOWLUMA_EXTRA_QQ_HOMES=/app/qq-acct2,/app/qq-acct3`；
- 升级：`docker compose pull && docker compose up -d`，**别删那三个卷**（删了就丢登录态和配置）；
- 国内拉不动镜像：`docker pull docker.1ms.run/motricseven7/snowluma:latest` 再 `docker tag`。

---

## 4. 配置文件详解（源码核对版）

所有配置都是 JSON，位于**工作目录**下的 `config/`（即发行包解压目录里的 `config/`）：

| 文件 | 作用 |
| --- | --- |
| `config/onebot.json` | 全局默认 OneBot 配置（所有账号的基线） |
| `config/onebot_<uin>.json` | 单账号覆盖，按 QQ 号一份；缺失或没 token 时自动写入规范化默认值 |
| `config/runtime.json` | 进程级运行时设置（WebUI 端口/绑定地址/TLS/日志等），**不分账号** |

### 4.1 `onebot.json` 完整结构

```json
{
  "networks": {
    "httpServers": [
      {
        "name": "http-default",
        "enabled": true,
        "host": "127.0.0.1",
        "port": 3000,
        "path": "/",
        "enableWebSocket": false,
        "accessToken": "<32 字节随机 base64url，自动生成>",
        "messageFormat": "array",
        "reportSelfMessage": false
      }
    ],
    "httpClients": [],
    "wsServers": [
      {
        "name": "ws-default",
        "enabled": true,
        "host": "127.0.0.1",
        "port": 3001,
        "path": "/",
        "role": "Universal",
        "accessToken": "<自动生成>",
        "messageFormat": "array",
        "reportSelfMessage": false
      }
    ],
    "wsClients": []
  },
  "statusCommand": { "enabled": true, "swallow": false, "cooldownSeconds": 5, "trigger": "#sl" },
  "historySync": { "enabled": false },
  "notifications": { "channelIds": [] },
  "musicSignUrl": ""
}
```

**字段说明**

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 必填 | 同类型数组内唯一；热重载按 `(类型, name)` 定位 |
| `enabled` | bool | true | false = 保留配置但不启动 |
| `accessToken` | string | **自动生成** | `Authorization: Bearer <token>` 或 `?access_token=` |
| `messageFormat` | `array`/`string` | array | 事件里 `message` 是段数组还是 CQ 字符串 |
| `reportSelfMessage` | bool | false | 是否接收 `post_type=message_sent`（自己发的消息） |
| `host` | string | `127.0.0.1` | 监听地址；局域网/容器互访改 `0.0.0.0` |
| `port` | number | 3000 / 3001 | 监听端口 |
| `path` | string | `/` | API 前缀 / WS 路径（不能带 `?` `#`） |
| `role` | `Api`/`Event`/`Universal` | Universal | **大写驼峰**，旧的小写写法已废弃 |
| `url`（clients） | string | 必填 | 反向 WS 地址 / HTTP 上报地址 |
| `reconnectIntervalMs`（wsClients） | number | 5000 | 最小被规范化为 1000 |
| `timeoutMs`（httpClients） | number | 5000 | 上报超时 |
| `musicSignUrl` | string | `""` | 自定义音乐卡片签名服务，空=禁用 |
| `statusCommand` | object | 见上 | 群内 `#sl` 查状态；`swallow`=吞掉该消息不外发 |
| `historySync.enabled` | bool | false | 历史消息同步 |

**鉴权细节**：默认 token 是 `randomBytes(32).toString('base64url')`，HTTP 与 WS **各自独立**；轮换 token 后对方框架要同步改。

### 4.2 `runtime.json` 全字段（⚠️ 文档只列了 2 个，实际 8 个）

```json
{
  "webuiPort": 5099,
  "webuiHost": "127.0.0.1",
  "hookAutoLoad": false,
  "webuiTls": { "enabled": false },
  "trustProxy": "",
  "logMaxTotalMb": 1024,
  "logRetainDays": 7,
  "logPerUin": false
}
```

| 字段 | 默认 | 说明 | 文档是否提及 |
| --- | --- | --- | --- |
| `webuiPort` | 5099 | WebUI 端口，越界回退到 5099 | ✅ |
| `hookAutoLoad` | false | 是否自动注入新发现的 QQ 进程（Docker 镜像默认 true） | ✅ |
| `webuiHost` | `127.0.0.1` | WebUI 绑定地址，改 `0.0.0.0` 才能跨机访问 | ❌ 未文档化 |
| `webuiTls.enabled` | false | 开 HTTPS，证书放 `config/cert.pem` + `config/key.pem` | ❌ |
| `trustProxy` | `""` | 反代信任策略（`""`=不信任任何代理） | ❌ |
| `logMaxTotalMb` | 1024 | 日志总容量上限 | ❌ |
| `logRetainDays` | 7 | 日志按天保留，0=禁用 | ❌ |
| `logPerUin` | false | 额外按 UIN 分目录复制日志 | ❌ |

> 绑定地址/TLS 属监听级配置，**改完必须重启**（不是热重载）。

### 4.3 环境变量（优先级高于 JSON）

| 变量 | 作用 |
| --- | --- |
| `SNOWLUMA_HOOK_AUTOLOAD` | `1/true` 强制开自动注入，`0/false` 关闭 |
| `SNOWLUMA_LOG_LEVEL` | `error`/`warn`/`info`/`debug` |
| `SNOWLUMA_WEBUI_PORT` / `SNOWLUMA_WEBUI_HOST` | 覆盖 WebUI 端口/绑定 |
| `SNOWLUMA_WEBUI_TLS` | `1` 强制开 TLS |
| `SNOWLUMA_WEBUI_TRUST_PROXY` | 反代信任策略 |
| `SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD` | **初始管理员密码种子**（≥8 位），免去翻日志找随机密码 |
| `SNOWLUMA_ONEBOT_HTTP_PORT` / `SNOWLUMA_ONEBOT_WS_PORT` | 覆盖默认监听口（仅作用于 `http-default`/`ws-default`，且**不写盘**） |
| `SNOWLUMA_LOG_MAX_TOTAL_MB` / `SNOWLUMA_LOG_RETAIN_DAYS` / `SNOWLUMA_LOG_PER_UIN` | 日志策略 |
| `SNOWLUMA_VERBOSE_WARMUP` | `1` 输出更详细的好友/群/成员预热日志 |
| `SNOWLUMA_DEV_MODE` / `SNOWLUMA_DEV_WEBUI` | 开发模式（放宽 WebUI 鉴权，**别在生产开**） |
| `SNOWLUMA_EXTRA_QQ_HOMES` / `SNOWLUMA_QQ_FLAGS` / `SNOWLUMA_SCREEN` / `VNC_PASSWD` / `SNOWLUMA_UID` / `SNOWLUMA_GID` / `TZ` | Docker 专用（多开账号、QQ 启动参数、Xvfb 分辨率、VNC 密码、属主、时区） |

---

## 5. 把机器人框架接上来（核心步骤）

先记住方向：**SnowLuma 只是"管道"**，框架负责收事件、发动作。

### 5.1 三种拓扑

| 拓扑 | 谁连谁 | 适合 | SnowLuma 侧配置 |
| --- | --- | --- | --- |
| **正向 WS** | 框架 → SnowLuma | MaiBot、自写客户端、多数"客户端型"框架 | 用默认 `wsServers`（3001），框架填 `ws://127.0.0.1:3001/` |
| **正向 HTTP** | 框架 → SnowLuma | 只需调动作，不需要事件流 | 用默认 `httpServers`（3000），框架 POST 到 `http://127.0.0.1:3000/` |
| **反向 WS** | SnowLuma → 框架 | **NoneBot2、AstrBot**（它们自己起 WS 服务） | 在 `wsClients` 里加一条对方的 URL |
| **HTTP 上报** | SnowLuma → 框架 | 轻量 webhook 式接入 | 在 `httpClients` 里填对方接收地址 |

### 5.2 框架对照表

| 框架 | 方向 | 对方入口 | 备注 |
| --- | --- | --- | --- |
| **NoneBot2** | 反向 WS | `ws://127.0.0.1:8080/onebot/v11/ws` | Python，插件生态最大；路径以 NoneBot 配置为准 |
| **AstrBot** | 反向 WS | `ws://127.0.0.1:6199/ws` | 自带 LLM/多平台，43k stars；也可用其 OneBot v11 适配器 |
| **MaiBot** | 正向 | 连 SnowLuma `ws://127.0.0.1:3001/` | 它的 NapCat/SnowLuma 适配器是**客户端** |
| **Koishi** | 反向或正向 | 取决于 adapter-onebot 配置 | `@koishijs/plugin-adapter-onebot` |
| **Yunzai / TRSS** | 正向 WS | `ws://127.0.0.1:3001/` | 老牌云崽系，OneBot 11 |
| **自写** | 任意 | — | 见 5.4 |

> 容器里跑框架时：用**服务名**（如 `ws://snowluma:3001/`），**不要** `127.0.0.1`（那是容器自己的回环）。

### 5.3 具体配置示例

**A. NoneBot2（反向 WS）**

1. SnowLuma 的 `config/onebot_<uin>.json` 增加：

```json
"wsClients": [
  {
    "name": "nonebot",
    "enabled": true,
    "url": "ws://127.0.0.1:8080/onebot/v11/ws",
    "role": "Universal",
    "reconnectIntervalMs": 5000,
    "accessToken": "",
    "messageFormat": "array",
    "reportSelfMessage": false
  }
]
```

2. NoneBot2 侧 `.env`：

```dotenv
DRIVER=~fastapi+~httpx+~websockets
ONEBOT_ACCESS_TOKEN=
HOST=127.0.0.1
PORT=8080
```

3. 装适配器：`pip install nonebot2 nonebot-adapter-onebot`，`bot.py` 里 `nonebot.load_plugin("nonebot.adapters.onebot.v11")`。

**B. AstrBot（反向 WS）**

AstrBot → 平台 → 新增 `QQ 个人号(OneBot v11 / aiocqhttp)`，WS 服务监听 `6199`，路径 `/ws`；然后在 SnowLuma 的 `wsClients` 填 `ws://127.0.0.1:6199/ws`（同一台机器）。

**C. MaiBot（正向）**

MaiBot 配置里适配器选 NapCat/SnowLuma，host `127.0.0.1`、port `3001`、token 填 SnowLuma 的 WS accessToken；SnowLuma 侧什么都不用改（默认已开 3001）。

### 5.4 自写客户端（最小可跑）

**调动作（HTTP）**

```bash
curl -s -X POST http://127.0.0.1:3000/ \
  -H "Authorization: Bearer <HTTP_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"action":"get_login_info","params":{},"echo":"1"}'
```

```python
import requests
BASE = "http://127.0.0.1:3000/"
H = {"Authorization": "Bearer <TOKEN>"}
def call(action, **params):
    r = requests.post(BASE, json={"action": action, "params": params, "echo": action}, headers=H, timeout=10)
    return r.json()

print(call("get_login_info"))
call("send_group_msg", group_id=123456789, message=[{"type": "text", "data": {"text": "hi"}}])
```

**收事件（反向 WS 或正向 WS）**

```python
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:3001/",
                                  additional_headers={"Authorization": "Bearer <WS_TOKEN>"}) as ws:
        async for raw in ws:
            ev = json.loads(raw)
            if ev.get("post_type") == "message" and ev.get("message_type") == "group":
                print(ev["group_id"], ev["raw_message"])
asyncio.run(main())
```

**SDK 方式**：`npm i @snowluma/sdk`，类型完备（还有 `onBotStatus` 等钩子）。文档：[sdk](https://snowluma.github.io/zh/docs/sdk)。

### 5.5 事件与对接细节（容易踩的）

- **账号上下线**：推送 `notice_type: bot_status`，`sub_type` 为 `online` / `offline`；被踢下线是 `bot_offline`；**进程退出不发 offline**。
- **`message_id` 是带符号 32 位整数，负数合法**——别用 `int` 无符号解析，也别改符号规则。
- `historySync` 默认关闭；消息历史存 SQLite，属持久数据，别当缓存清。
- 多账号：每个 UIN 一份 `onebot_<uin>.json`，**默认都想占 3000/3001，第二个账号必须换端口**或用反向 WS 指向不同框架入口。

### 5.6 MCP 接入（让 AI 客户端直接操作 QQ）

```json
{
  "mcpServers": {
    "snowluma": {
      "command": "npx",
      "args": ["-y", "@snowluma/mcp"],
      "env": {
        "SNOWLUMA_MCP_ENDPOINT": "http://127.0.0.1:3000/",
        "SNOWLUMA_MCP_TOKEN": "<HTTP_TOKEN>"
      }
    }
  }
}
```

- 三种模式：`docs`（只查目录）/ `read`（只读动作 + 事件订阅）/ `write`（写动作、流式传输、后台任务，需 `SNOWLUMA_MCP_MODE=write`）；
- 需要 Node `^24.22.1 || >=26.12.1`；
- 管理口 5099 **不能**代替 OneBot 口 3000。

---

## 6. 横向对比：SnowLuma 与"其他项目"

### 6.1 协议端（把 QQ 变成 OneBot 的那一层）

| 项目 | 原理 | 协议 | 平台 | 生态/活跃度 | 许可 | 适合 |
| --- | --- | --- | --- | --- | --- | --- |
| **SnowLuma** | 注入 NTQQ + 原生 hook | OneBot v11（含大量扩展动作） | Win / Linux(Docker) | 2.5k★，日更 | ⚠️ 源码可见**非商业** | 想用新东西、要 WebUI/SDK/MCP、非商业自用 |
| **NapCatQQ** | 注入 NTQQ | OneBot 11（+ 部分扩展） | Win / Linux / Docker | **11.5k★，事实标准** | 开源 | 要生态最全、教程最多、最稳 |
| **LLBot（原 LLOneBot）** | 注入 NTQQ | **OneBot 11 + Satori + Milky** | Win / Linux / Docker | 3.7k★，改名后转向多协议 | 开源 | 想试 Satori/Milky 新协议 |
| **Lagrange.Core** | **纯协议实现**，不需要 QQ 客户端 | OneBot 11（OneBot 实现见 Lagrange.OneBot） | 全平台（C#/.NET） | 3.0k★，更新放缓 | 开源 | 无 GUI 服务器、不想开 QQ 客户端；但需自备**签名服务**，风控风险更高 |
| **官方 QQ 机器人** | 腾讯官方开放平台 | 官方 API v2 | 云 | 需主体认证、审核 | 官方 | 合规优先、可接受功能受限（[bot.q.qq.com](https://bot.q.qq.com/wiki/)） |

**一句话选型：**
- 要**最稳、教程最多** → NapCatQQ；
- 要**新、带 WebUI/SDK/MCP、扩展动作多** → SnowLuma（但接受非商业许可 + 早期项目风险）；
- 要**多协议**（Satori/Milky）→ LLBot；
- 要**不开 QQ 客户端**、能搞定签名 → Lagrange；
- 要**完全合规不封号** → 官方机器人（功能受限，需申请）。

> 协议趋势：OneBot v11 仍是事实标准；**Milky**（NTQQRev 出品，HTTP/WS 的新一代接口标准，强类型、覆盖更多 QQ 特性）与 **Satori** 正在被 LLBot 等协议端同时支持。SnowLuma 目前只做 OneBot v11。

### 6.2 应用端（机器人框架）

| 框架 | 语言 | 规模 | 特点 | 接 SnowLuma |
| --- | --- | --- | --- | --- |
| **AstrBot** | Python | 43k★ | 多平台 + LLM + 管理面板，开箱即用 | 反向 WS `/ws` |
| **NoneBot2** | Python | 7.8k★ | 插件生态最大、异步、类型友好 | 反向 WS `/onebot/v11/ws` |
| **Koishi** | TypeScript | 6.3k★ | 插件市场丰富、跨平台 | adapter-onebot |
| **MaiBot** | Python | 6.5k★ | 拟人化 LLM 数字生命 | 正向连 3001 |
| **Yunzai/TRSS** | Node | 老牌 | 国内 QQ 群管理插件多 | 正向 WS |

**推荐组合（你这台 Windows）**：
- 想省事、要 AI 对话 → **SnowLuma + AstrBot**；
- 想深度定制、写插件 → **SnowLuma + NoneBot2**；
- 想先跑通验证管道 → 第 5.4 节的 Python 脚本。

---

## 7. 这里最容易踩的坑（已核对源码/资产）

1. **Windows 包是 `.zip`，文档写 `.tar.gz`** —— 找错文件。
2. **Node 版本说法不一致**：`package.json` 的 `engines` 是 `^24.22.1 || >=26.12.1`，文档说「≥22 / 推荐 24」。稳妥做法：用 **完整版 zip（自带 Node）**，别踩版本坑。
3. **默认只监听 `127.0.0.1`**（源码为准），文档《介绍》表写 `0.0.0.0` —— 跨机/容器连不上先查这里。
4. **`runtime.json` 有 8 个字段，文档只写 2 个** —— `webuiHost`、`webuiTls`、`trustProxy`、日志三项都未文档化。
5. **初始密码只打印一次**，且只在"全新数据目录"首次启动时；复用旧目录就再也看不到，只能改 `SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD` 或清数据目录。
6. **必须同用户、同权限运行** SnowLuma 与 QQ，否则注入失败。
7. **多账号必须换端口或独立 HOME**（Linux 单实例锁 / Windows 多开 HOME）。
8. **升级镜像/重装可能换设备指纹** → 需要重新扫码；别删数据卷。
9. **不要把 5099/3000/3001/6081 裸暴露公网** —— 这些口等于"完全控制你的 QQ"。远程访问走反代 + 鉴权或内网穿透 + 鉴权。
10. **QQ 版本兼容**：`compat/qq.json` 由客户端启动时从 GitHub 拉取，`knownBadVersions` 里的版本会被拒绝注入。QQ 自动升级到未知新版本时，hook 可能失效——先看 WebUI 提示。你本机是 `9.9.21.38711`，不在已知坏版本里（manifest 当前 `knownGoodVersions`/`knownBadVersions` 均为空，`allowUnknown=true`）。
11. **3000/3001 要等账号上线才监听**（实测）：没 hook 上账号时只有 5099 开着，别误判成"端口没起来"。
12. **`config/webui.json` 是隐藏凭据文件**（文档未写）：`passwordHash` + `passwordSalt` + `mustChangePassword`，备份/迁移别漏。
13. **`launcher.bat` 里的 `node` 靠 cmd 的"当前目录优先"命中自带的 `node.exe`**：必须**在解压目录内**启动（双击 `launcher.bat` 即可）。从别的目录调 `launcher.bat`、或用 `Start-Process` 指定了别的 `WorkingDirectory`，都会报 `'node' 不是内部或外部命令`。稳妥写法：`.\node.exe .\index.mjs`（显式用自带运行时）。

---

## 8. 风险与合规（务必看）

- **许可**：SnowLuma 是**源码可见、非 OSI 开源**许可。允许查看、学习、**非商业自托管**、私下修改；**商业使用、公开发布修改版/衍生版需书面授权**（联系 `motricseven@foxmail.com`）。随附原生附加组件是专有组件。
- **合规**：第三方项目与腾讯/QQ 无隶属关系；注入客户端属于非官方手段，**存在账号被风控/封禁的风险**，也涉及《QQ 用户协议》。项目自述"仅供学习与技术研究，使用风险自负"。
- **安全**：为了注入，Docker 需要 `SYS_PTRACE` + `seccomp=unconfined`；Windows 需要与 QQ 同权限。**只在你信任的机器上跑**。
- **稳定性**：官方标注早期开发，接口/配置/发行布局都可能变；生产请**固定 tag**，升级前读 CHANGELOG。

---

## 9. 本机落地清单（今天可完成）

本报告附带 4 个可直接用的文件（都在 `Z:\snowluma\` 下）：

| 文件 | 用途 |
| --- | --- |
| `scripts\install-snowluma.ps1` | 自动下载最新 win-x64 完整版 zip 并解压到 `Z:\snowluma\SnowLuma` |
| `config-examples\onebot.native.json` | 本机正向模式配置模板（HTTP 3000 + WS 3001，回环） |
| `config-examples\onebot.reverse-ws.json` | 反向 WS 模板（给 NoneBot2/AstrBot） |
| `config-examples\runtime.json` | 运行时配置模板（含未文档化字段） |
| `scripts\smoke-test-onebot.ps1` | 冒烟测试：校验 token 并调 `get_login_info` / `get_status` |
| `SnowLuma-拓展路线评估-Docker.md` | **后续拓展要不要上 Docker 的评估**（结论：混合架构，SnowLuma 原生 + 框架容器） |
| `stack\docker-compose.yml` + `stack\nonebot\` | 杂交方案的可运行骨架：NoneBot2 容器（`127.0.0.1:8080` 反向 WS） |
| `SnowLuma\` | **已实测安装好**的 v2.2.0 win-x64 完整版（自带 Node v24.22.1，41 MB 包解压后约 100 MB） |

执行顺序：

```powershell
# 1) ✅ 已完成：v2.2.0 win-x64 已解压到 Z:\snowluma\SnowLuma（自带 node v24.22.1）
#    需要重装/升级时再跑：
#    powershell -ExecutionPolicy Bypass -File Z:\snowluma\scripts\install-snowluma.ps1

# 2) 启动（会弹控制台，首次启动记下"临时密码"；首次进 WebUI 还要同意 EULA）
cd Z:\snowluma\SnowLuma
.\launcher.bat

# 3) 浏览器打开 WebUI，登录后确认 QQ 已注入、账号在线
#    http://127.0.0.1:5099/
#    在"网络适配器"里复制 HTTP / WS 的 accessToken

# 4) 冒烟测试
powershell -ExecutionPolicy Bypass -File Z:\snowluma\scripts\smoke-test-onebot.ps1 -Token "<HTTP_TOKEN>"
```

**我无法替你完成的一步**：扫码登录（必须在 QQ 窗口里用手机 QQ 扫）。注入、配置、接口验证都可以脚本化。

**下一步建议**：先只跑 SnowLuma + 冒烟测试，确认 `get_login_info` 能返回你的 QQ 号；然后再决定接 NoneBot2（写插件）还是 AstrBot（要 AI）。要我直接按某个框架把配置写全、并把框架也拉起来，告诉我选哪个即可。

---

## 10. 参考资料

**SnowLuma**
- 仓库：<https://github.com/SnowLuma/SnowLuma>
- 文档：<https://snowluma.github.io/zh/docs/guide/introduction> ｜ [部署](https://snowluma.github.io/zh/docs/guide/deploy) ｜ [对接机器人](https://snowluma.github.io/zh/docs/guide/connect-bot) ｜ [配置参考](https://snowluma.github.io/zh/docs/guide/configuration) ｜ [排障](https://snowluma.github.io/zh/docs/guide/faq) ｜ [API](https://snowluma.github.io/zh/docs/api) ｜ [MCP](https://snowluma.github.io/zh/docs/mcp)
- 发行包：<https://github.com/SnowLuma/SnowLuma/releases>

**同类/相关**
- NapCatQQ：<https://github.com/NapNeko/NapCatQQ> ｜ 文档 <https://napneko.github.io/>
- LLBot（原 LLOneBot）：<https://github.com/LLOneBot/LLOneBot> ｜ 文档 <https://luckylillia.com>
- Lagrange.Core：<https://github.com/LagrangeDev/Lagrange.Core>
- Milky 协议：<https://milky.ntqqrev.org/>
- AstrBot：<https://github.com/AstrBotDevs/AstrBot>
- NoneBot2：<https://github.com/nonebot/nonebot2>
- Koishi：<https://github.com/koishijs/koishi>
- MaiBot：<https://github.com/MaiM-with-u/MaiBot>
- 官方 QQ 机器人：<https://bot.q.qq.com/wiki/>
- OneBot 11 标准：<https://github.com/botuniverse/onebot-11>
