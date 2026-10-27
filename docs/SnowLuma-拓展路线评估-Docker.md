# 后续拓展路线评估：要不要把 SnowLuma 装进 Docker？

> 评估时间：2026-10-25　|　对应现状：SnowLuma v2.2.0 已原生安装在 `Z:\snowluma\SnowLuma`（自带 Node 24，可跑，未注入）
> 本机实测：Windows 11 IoT LTSC 26100 / Ryzen 5 3600X / 16 GB（当前可用 8 GB）/ **WSL 未安装**（Hypervisor 已启用）/ 未装 Docker / QQ NT 9.9.21 已登录，9 进程占 **815 MB**

---

## 0. 结论先说

| 问题 | 答案 |
| --- | --- |
| 现在就把 SnowLuma 整体搬进 Docker？ | **不建议**。等于换成一个 Linux QQ 客户端，要重新扫码、丢掉现有登录态，性能和排查成本都上升 |
| 做拓展（插件/AI/多框架/多账号/7×24）该不该用 Docker？ | **该用，但用在"机器人框架"这一层，而且最终落在 Linux 服务器上，不是长期挂 Windows 上的 Docker Desktop** |
| 当前最优解 | **混合架构**：SnowLuma 保持原生（它必须 hook 你正在用的桌面 QQ）＋ 机器人框架跑容器；用「反向 WS + 端口只发布到 127.0.0.1」打通 |
| 什么信号出现时整体上 Docker | 见 §6 判定清单（7×24 / 多账号 / 多框架 / 要上 VPS / 要版本回滚，满足 2 条就够了） |

---

## 0.5 最终决定（2026-10-25，需求确定后）

**不装 Docker，全部原生跑。**

需求已明确：**单账号、单框架（NoneBot2）、不迁 Linux 服务器**。这直接抹掉了 Docker 在本机本来能带来的三条收益：

| Docker 的收益 | 在当前需求下是否成立 |
| --- | --- |
| 多账号各自独立 HOME | ❌ 只有一个号 |
| 多框架/多语言依赖隔离 | ❌ 只跑一个 NoneBot2（已用独立 venv 隔离） |
| 与 Linux 生产环境同构、可整体搬迁 | ❌ 不打算上服务器 |
| 崩溃自拉起 / 版本一键回滚 | ⚠️ 用 `start-all.ps1` / `stop-all.ps1` + 固定版本目录即可代替 |

代价则照旧存在：WSL2 常驻 2–3 GB、要一次重启、特权容器（`SYS_PTRACE` + `seccomp=unconfined`）、多一层 noVNC 排查链。

**结论：省掉这层。** 依赖隔离用 venv 已经解决；常驻用脚本解决；将来若真的要多号 / 上 VPS，再回来看本文 §4–§6。

> 下文的架构对比与 compose 方案**保留为备选**，不代表已采用。

---

## 1. 一个必须先厘清的事实（容易误判）

官方镜像是 **Linux QQ + Xvfb + VNC + noVNC + supervisord + SnowLuma lite** 的整包。

- 它**不会**去 hook 你 Windows 上的 `QQ.exe`——注入发生在容器内部，目标是容器里的 **Linux QQ（进程名 `qq`）**；
- 所以"Docker 化 SnowLuma"不是搬家，而是**换客户端**：新设备指纹、要 noVNC 扫码、要重新登录；
- 同一个 QQ 号**不能**两处同时在线，跑容器版就得把桌面版踢下线。

**推论**：只要你还想用这台 Windows 上已经登录的 QQ（也是你日常在用的那个号），SnowLuma 就该留在原生。

---

## 2. 拓展场景 → 各层该放哪

| 拓展方向 | 关键技术需求 | 放哪更合适 |
| --- | --- | --- |
| 写插件、调 prompt、频繁重启 | 快速迭代、看日志 | **原生**（改完重启 3 秒） |
| 接 AI（AstrBot / MaiBot） | 独立 Python 环境、模型 Key | **容器**（依赖隔离，官方有镜像） |
| 同时跑 2 个框架（NoneBot + AstrBot） | 端口/依赖不打架 | **容器 + compose 网络** |
| 多 QQ 账号 | 每号独立 HOME / 独立端口 | **容器**明显更好（`SNOWLUMA_EXTRA_QQ_HOMES`），Windows 原生多开很别扭 |
| 7×24 常驻 | 崩溃自拉起、开机自启 | **容器**（`restart: unless-stopped`）；原生要靠计划任务/NSSM，Windows 更新还会重启 |
| 版本固定 / 一键回滚 | 镜像 tag + 卷快照 | **容器** |
| 迁到 Linux VPS | 环境一致 | **容器**（官方镜像 amd64/arm64 都有） |
| 备份配置 | 就几个 json | 两边都容易；原生直接 `git` 管 `config/` 更直观 |

---

## 3. 四套架构横向对比

| | A. 全原生（现状） | B. **混合（推荐）** | C. 全 Docker on Windows | D. Linux 服务器全容器（目标态） |
| --- | --- | --- | --- | --- |
| 用的哪个 QQ | 桌面版（已登录） | 桌面版（已登录） | **容器内 Linux QQ（要重扫）** | 容器内 Linux QQ |
| 改动量 | 0 | 装 Docker Desktop + WSL2 | 同左 | 一台 Linux 机器 |
| 额外内存 | 0 | WSL2 VM ~2–3 GB | WSL2 + 容器 QQ ~3–3.5 GB | 服务器侧 ~1.5–2 GB |
| 拓展性 | 差（依赖打架） | **好** | 好 | **最好** |
| 常驻稳定性 | 差 | 好（框架层） | 好 | 最好 |
| 排查难度 | **最低** | 中 | 高（VNC + 双 QQ 语义） | 中 |
| 可迁移性 | 无 | 框架可迁 | 可迁 | **原生可迁** |
| 适合 | 现在 | **接下来 1–3 个月** | 想预演 Linux 栈 | 真正长期跑 |

**本机资源账**：桌面 QQ 已吃 815 MB，16 GB 只剩 8 GB。再叠 WSL2 VM（2–3 GB）+ 容器内 Linux QQ（300–500 MB/账号）+ 框架（200–400 MB），同时还要开 IDE/浏览器——**能跑，但不宽裕**。这也是不建议在 Windows 上同时挂"桌面 QQ + 容器 QQ"的原因：一份号只能在线一次，纯属浪费。

---

## 4. 推荐架构：混合（SnowLuma 原生 + 框架容器）

```
┌───────────── Windows 宿主 ─────────────────────────────┐
│  QQ.exe (桌面版, 已登录, 815 MB)                        │
│      ↑ ptrace 注入（同用户同权限）                      │
│  SnowLuma 原生 (node.exe, WebUI 127.0.0.1:5099)         │
│      │  OneBot 3000/3001  ← 保持只监听 127.0.0.1        │
│      │                                                  │
│      └── 反向 WS 出站 ──→ 127.0.0.1:8080 ┐             │
│                                          │ 端口发布     │
│  ┌──────────── WSL2 / Docker ────────────┼───────────┐  │
│  │  nonebot 容器  :8080 /onebot/v11/ws ←─┘           │  │
│  │  （以后可再加 astrbot、redis、postgres…）          │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**为什么用"反向 WS"而不是"正向"**（这是本方案的关键取舍）：

| | 反向 WS（SnowLuma 连框架） | 正向 WS（框架连 SnowLuma） |
| --- | --- | --- |
| SnowLuma 绑定 | 保持 `127.0.0.1` | **必须改 `0.0.0.0`**（容器/防火墙才够得着） |
| 宿主防火墙 | 不用动 | 要放行 3001 |
| 暴露面 | 零（只有框架端口发布到回环） | 3001 对局域网开放 |
| 结论 | ✅ 选它 | ❌ |

具体做法：

- 容器内框架监听 `0.0.0.0:8080`，compose 里发布成 `127.0.0.1:8080:8080`（**只到宿主回环**）；
- SnowLuma 的 `config/onebot_<uin>.json` 里加一条 `wsClients` 指向 `ws://127.0.0.1:8080/onebot/v11/ws`；
- 原生进程连宿主回环天然可达，**不需要** `host.docker.internal`。

### 4.1 NoneBot2 容器示例

`nonebot/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "nonebot2[fastapi,websockets]" nonebot-adapter-onebot
COPY bot.py .
CMD ["python", "bot.py"]
```

`nonebot/bot.py`

```python
import nonebot
from nonebot.adapters.onebot.v11 import Adapter

nonebot.init()
nonebot.get_driver().register_adapter(Adapter)
nonebot.load_plugins("plugins")
nonebot.run()
```

`docker-compose.yml`（放 `Z:\snowluma\stack\`）

```yaml
services:
  nonebot:
    build: ./nonebot
    container_name: snowluma-nonebot
    restart: unless-stopped
    environment:
      HOST: 0.0.0.0
      PORT: "8080"
      ONEBOT_ACCESS_TOKEN: ${ONEBOT_ACCESS_TOKEN:-}
    ports:
      - "127.0.0.1:8080:8080"      # 只发布到宿主回环，不对局域网开放
    volumes:
      - ./nonebot/plugins:/app/plugins
      - nonebot-data:/app/data
volumes:
  nonebot-data:
```

SnowLuma 侧 `config/onebot_<uin>.json`：

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

### 4.2 AstrBot 容器

官方镜像 `soulter/astrbot`（见其 README 的 Docker Deployment），同样把它的 WS 端口发布到 `127.0.0.1:6199`，SnowLuma 侧 `wsClients` 填 `ws://127.0.0.1:6199/ws`。

---

## 5. 如果你还是想"全 Docker"

那就在 Windows 上用 Docker Desktop（需先 `wsl --install` 并重启），把官方的 compose 直接跑起来：

- 优点：和将来 Linux 服务器**完全同构**，一次配置走天下；镜像已含 `node` 的 `cap_sys_ptrace`，不用改宿主 sysctl；
- 代价：① 要放弃桌面 QQ 的登录态并重新扫码；② 日常多一层 VNC；③ 内存多 3 GB 左右；④ 调试链路变长（容器日志 + WebUI + QQ 日志）。
- 如果你选这条，**桌面 QQ 就别再登同一个号**，否则互相踢。

---

## 6. 什么时候该整体上 Docker（判定清单）

满足 ≥2 条就该动手：

1. 要让机器人在**你注销/重启/Windows 更新后自动回来**；
2. 要跑 **2 个以上 QQ 账号**；
3. 要同时跑 **2 个以上框架/语言环境**（比如 NoneBot + AstrBot + 一个 Node 服务）；
4. 已经有/即将有 **Linux VPS**；
5. 需要**版本固定 + 一键回滚**（`docker compose pull` 就能回退 tag）；
6. 要交付给别人复现（compose 比"我机器上能跑"可靠）。

**但注意**：第 1/2 条一旦成立，正确答案通常是**直接上 Linux 服务器 + Docker**，而不是长期在 Windows 上挂 Docker Desktop。Windows 只适合当开发机。

---

## 7. 迁移路径（低风险，不返工）

| 阶段 | 做什么 | 产出 |
| --- | --- | --- |
| **现在（1）** | SnowLuma 原生跑通；把 `config/*.json` 纳入 git（token 用占位符/环境变量，别提交真 token） | 可复现的配置基线 |
| **2（1–3 个月）** | 框架 Docker 化；写 `stack/docker-compose.yml` + `.env`；反向 WS 打通 | 混合架构，日常开发在容器里 |
| **3** | 买/用 Linux VPS，把同一份 compose 搬过去；迁移 `config/onebot*.json`、`runtime.json`、`webui.json`；重新扫码 | 7×24 生产 |
| **4（可选）** | Windows 保留为调试环境（独立测试号） | 双环境 |

阶段 3 的迁移成本之所以低，是因为 SnowLuma 的配置就是几个 JSON 文件 + 三个数据卷语义；**不要把登录态当成可迁移资产**（换机/重建容器常要重扫）。

---

## 8. 成本与风险清单

| 项 | 说明 |
| --- | --- |
| Docker Desktop 授权 | 个人/小企业（<250 人且 <$10M 营收）免费，否则需订阅；纯 Linux 服务器用 Docker Engine 无此问题 |
| WSL2 开销 | VM 常驻吃 2–3 GB；`vmmem` 不会主动还内存，需配 `.wslconfig` 限制 |
| 磁盘 | WSL2 镜像 + 镜像层，10 GB 起步 |
| 容器 QQ | 每个账号 300–500 MB；noVNC 扫码；升级可能换设备指纹 → 重扫 |
| 特权 | SnowLuma 容器需要 `SYS_PTRACE` + `seccomp=unconfined`；在 WSL2 VM 内爆炸半径小于宿主原生，但仍是特权容器——只跑可信镜像 |
| 端口 | 一律只发布到 `127.0.0.1`；5099/6081/3000/3001 绝不裸奔公网 |
| 许可 | SnowLuma 非商业许可；商业用途需授权（详见主报告 §8） |

---

## 9. 一句话建议

**别现在整体搬 Docker。** 先用「SnowLuma 原生 + 框架容器 + 反向 WS」这套混合形态做拓展：开发快、不暴露端口、依赖互不打架；等出现 7×24 / 多账号 / 要上 VPS 的硬需求，直接把同一份 compose 搬到 Linux 服务器跑全容器——那时 Docker 才是收益最大、成本最低的形态，而不是在 Windows 上为了"用上 Docker"多养一个 3 GB 的虚拟机。

---

## 附：与主报告的关系

- 部署与配置细节见：`SnowLuma-QQ机器人调查报告.md`（§3 部署、§4 配置、§5 对接框架）
- 本文只回答"后续拓展该不该容器化、怎么容器化"。
