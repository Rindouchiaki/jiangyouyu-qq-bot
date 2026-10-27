# SnowLuma 参数调查与原理说明

> 调查时间：2026-10-25 21:05
> 范围：`Z:\snowluma` 下 SnowLuma v2.2.0（协议端）+ NoneBot2 2.5.0（框架层）+ persona 插件
> **本次只读调查，未修改任何文件、未重启任何服务**

---

## 一、本机实际生效参数

### 1.1 SnowLuma 全局 OneBot 配置（`SnowLuma\config\onebot.json`）

| 适配器 | 关键参数 | 值 |
| --- | --- | --- |
| `httpServers[0]` | name / host / port / path | `http-default` / `127.0.0.1` / `3000` / `/` |
| | enableWebSocket / messageFormat | `false` / `array` |
| | accessToken | `wFzfbI2…sXL8` |
| `wsServers[0]` | name / host / port / path / role | `ws-default` / `127.0.0.1` / `3001` / `/` / `Universal` |
| | accessToken | `tAgwVnib…vII` |
| `wsClients[0]` | name / url | `nonebot` / `ws://127.0.0.1:18080/onebot/v11/ws` |
| | role / reconnectIntervalMs | `Universal` / `5000` |
| | accessToken | `X0UiJMRo…aDA` |
| `httpClients` | — | 空 |
| `statusCommand` | enabled / swallow / cooldownSeconds / trigger | `true` / `false` / `5` / `#sl` |
| `historySync` | enabled | `false` |
| `notifications` | channelIds | `[]` |
| `musicSignUrl` | — | `""` |

### 1.2 账号级配置（`onebot_<uin>.json`，两份内容**完全一致**）

| 项 | 100000002（你自己的号） | 100000001（机器人号 酱油鱼） |
| --- | --- | --- |
| `mode` | `overlay` | `overlay` |
| HTTP 服务 | `127.0.0.1:3000`，token 同上 | 同左 |
| WS 服务 | `127.0.0.1:3001`，token 同上 | 同左 |
| 反向 WS | `ws://127.0.0.1:18080/…`，5000ms 重连 | 同左 |
| 实际监听结果 | ❌ `EADDRINUSE`（端口被前者占用） | ✅ 占住 3000 / 3001 |

> 两个号都渲染了同一份网络配置，这是**默认行为**（账号配置从全局基线合并）。结果是：

- 100000001 先加载 → 独占 3000 / 3001；
- 100000002 后加载 → HTTP / WS 服务端绑定失败（日志里两条 `EADDRINUSE`），但它的**反向 WS 仍然连到了 NoneBot**。

### 1.3 运行时配置（`SnowLuma\config\runtime.json`）

| 字段 | 值 |
| --- | --- |
| `webuiPort` | 5099 |
| `webuiHost` | 127.0.0.1 |
| `hookAutoLoad` | **false** |
| `webuiTls.enabled` | false |
| `trustProxy` | `""` |
| `logMaxTotalMb` / `logRetainDays` / `logPerUin` | 1024 / 7 / false |

### 1.4 配置目录里的其它文件

| 文件 | 内容 | 备注 |
| --- | --- | --- |
| `webui.json` | passwordHash / passwordSalt / `mustChangePassword:false` | 凭据，删了会重置密码 |
| `consent.json` | EULA 版本 `dcb31a7b03a0b64d`，接受于 2026-10-25T12:42:31Z | 你已经点过同意 |
| `ui.json` | 主题/配色/字号等 2.8 KB 外观设置 | 只影响 WebUI 显示 |

### 1.5 启动时注入的环境变量（`scripts\start-all.ps1`）

| 变量 | 值 | 生效条件 |
| --- | --- | --- |
| `SNOWLUMA_HOOK_AUTOLOAD` | `1` | 仅在 `-AutoLoad` 时；**优先级高于 runtime.json** |
| `SNOWLUMA_LOG_LEVEL` | `info` | 总是 |
| `SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD` | `<WEBUI_PASSWORD>` | 总是（仅首次种子生效） |

### 1.6 NoneBot 侧启动参数

| 变量 | 值 |
| --- | --- |
| `HOST` / `PORT` | `127.0.0.1` / `18080` |
| `ONEBOT_ACCESS_TOKEN` | `X0UiJMRo…aDA`（与 wsClients 成对） |
| `LOG_LEVEL` | `INFO` |

### 1.7 persona 插件参数（`stack\nonebot\persona.env`，全量 14 项）

| 键 | 值 | 作用 |
| --- | --- | --- |
| `BOT_UIN` | 100000001 | 只让这个号发言 |
| `NICKNAMES` | 酱油鱼,大肥鱼,鲸鱼娘 | 叫外号即算点名 |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容端点 |
| `LLM_MODEL` | `deepseek-chat` | 实际返回 `deepseek-flash` |
| `LLM_API_KEY` | `sk-***` | 明文存放 |
| `REPLY_MAX_CHARS` | 20 | 单条上限 |
| `HISTORY_SIZE` | 16 | 每会话上下文条数 |
| `REPLY_COOLDOWN` | 8 | 同会话冷却（秒） |
| `REPLY_CHIME_PROB` | 0.02 | 未被点名时的插话概率 |
| `REPLY_CHIME_COOLDOWN` | 180 | 两次插话最小间隔（秒） |
| `ENGAGE_TTL` | 120 | 被叫后「还在聊」时长（秒） |
| `ENGAGE_FOLLOW_WINDOW` | 45 | 别人接话的窗口（秒） |
| `ENGAGE_MAX_TURNS` | 8 | 单段对话最多来回 |
| `REPLY_PER_MIN` | 8 | 全局限流 |

---

## 二、与上游默认值对照

| 参数 | 上游默认（v2.2.0 源码） | 本机值 | 谁改的 / 原因 |
| --- | --- | --- | --- |
| OneBot HTTP 监听 | `127.0.0.1:3000` | 同 | 未改 |
| OneBot WS 监听 | `127.0.0.1:3001` | 同 | 未改 |
| 适配器 host 默认 | `127.0.0.1`（**非 Docker**） | 同 | 文档《介绍》页写 `0.0.0.0` 是错的 |
| accessToken | 启动时随机 32B base64url | 三枚固定值 | 我固定的，方便脚本与排错 |
| `wsClients` | `[]` | 一条 nonebot | 我加的，接框架 |
| `statusCommand` | enabled/5s/`#sl` | 同 | 未改 |
| `historySync` | `false` | 同 | 未改 |
| `webuiPort` / `webuiHost` | 5099 / 127.0.0.1 | 同 | 未改 |
| `hookAutoLoad` | `false` | runtime 里 false，启动时 env 设 1 | 我改的（`-AutoLoad`） |
| 日志上限/保留 | 1024 MB / 7 天 / 不分 UIN | 同 | 未改 |
| WebUI 初始密码 | 随机 16 位十六进制，仅控制台 | 固定 `<WEBUI_PASSWORD>` | 我改的（日志里密码被脱敏，随机密码会丢） |
| 官方 Docker 模板 | `0.0.0.0`、`HOOK_AUTOLOAD=1`、端口 6081/5099/3000/3001、`shm 1g`、`SYS_PTRACE` + `seccomp=unconfined` | 未采用 | 单账号不需要容器 |

---

## 三、运行时事实（可复核）

| 项 | 值 |
| --- | --- |
| 进程结构 | SnowLuma 主进程 `39988`（91 MB）→ 子进程 `37660`（141 MB，持有 3000/3001/5099）；NoneBot `17232`（61 MB） |
| 存储 | `data\<uin>\` 下 `messages.db`、`reactions.db`、`snowluma_identity.db`，合计 23.9 MB |
| 日志 | `SnowLuma\logs\snowluma-YYYY-MM-DD.log`（密码字段被脱敏，别指望从这里找回 WebUI 密码） |
| 已连接 | NoneBot 侧 `Bot 100000002 connected`、`Bot 100000001 connected`（两个号都连上了） |

---

## 四、发现的问题（只记录，未修改）

1. **双号抢端口**：两份账号配置都写 3000/3001，后启动的号永远绑不上，HTTP/WS 服务实际只有 100000001 可用。要用「按号调接口」，得给 100000002 换 3100/3101。
2. **两个号都往 NoneBot 推事件**：persona 用 `BOT_UIN` 过滤了，但 `ping` 插件没有，另一个号在群里被 `/ping` 也会回。
3. **会话键含用户 ID**：NoneBot 的 `GroupMessageEvent.get_session_id()` = `group_<群号>_<发言人QQ>`。这意味着上下文和「接续状态」都是**按人**切的，不是按群。你要求的「被叫一次后，其他人接着聊也回」，在当前实现里**不会触发**——其他人在新 key 上，没有接续状态。这是个真实的设计缺陷。
4. **`hookAutoLoad` 语义分裂**：`runtime.json` 写 false，启动脚本用环境变量设 1，最终以环境变量为准。看配置文件和看实际行为会得出不同结论。
5. **18080 是妥协值**：8080 被 Steam 的 `steamwebhelper` 调试端口占用，容器内仍按 8080 设计。
6. **明文凭据分散**：`persona.env`（LLM key）、`start-all.ps1`（OneBot token、WebUI 密码）、`DEPLOY-STATE.md`（全量）。本机无所谓，外传前要清。
7. **`data\history.json` 共用**：18081 上的测试实例和 18080 真实实例写同一个文件，测试数据会污染真实上下文。
8. **两号配置一致**：想给它们不同端口/不同协议，目前没有界面入口，只能手改 `onebot_<uin>.json`（且会被重新规范化）。

---

## 五、SnowLuma 的整体工作原理

### 5.1 分层

```
QQ 客户端（Windows: QQ.exe / Linux: qq）
   │  ptrace 注入 native addon
   ▼
[bridge]  进程发现 → 账号识别（读登录库拿 UIN）→ Hook 会话生命周期
   │  原始数据包
   ▼
[protocol]  包编解码 → 好友/群/成员/消息事件 → 身份映射（uin、群号、消息 id）
   │  内部类型化事件
   ▼
[onebot]  事件转 OneBot v11 → 动作校验与分发 → 消息/媒体存储（SQLite）
   │
   ▼
[network]  HTTP 服务端 / WS 服务端 / 反向 WS / HTTP 上报
   │
   ▼
机器人框架（NoneBot2 / AstrBot / MaiBot），或 SDK、MCP
```

### 5.2 关键机制

- **注入而非登录**：不碰 QQ 协议号，靠 hook 正在运行的客户端，所以能看到真实会话、不需要签名服务器；代价是绑平台、绑版本、有风控风险。
- **两段式激活**：注入后先「被动观察」，等扫码登录完成、识别到 UIN，才切「工作模式」并拉起该账号的 OneBot 实例。
- **账号即实例**：一个 UIN 一个 `OneBotInstance`，独立配置、独立存储、独立网络适配器。所以多号必然要面对端口/配置冲突（见问题 1）。
- **动作与事件对称**：事件（message / notice / request / meta_event）往下游推；动作（send_msg、get_group_list…）由下游调用，鉴权走 `Authorization: Bearer` 或 `?access_token=`。
- **持久化**：消息、回应、身份映射都进 SQLite（`data\<uin>\*.db`），不是内存缓存，所以不能当临时数据删。
- **管理与扩展口**：WebUI（5099）管进程/配置/日志/调试；`@snowluma/sdk` 写类型化客户端；`@snowluma/mcp` 让 AI 客户端直接调动作。

### 5.3 它不做什么

不做对话、不做插件、不做业务逻辑——只做「把 QQ 变成标准接口」这一层。所有人设、AI、回复策略都在下游（也就是 `plugins\persona.py`）。

---

## 六、后续怎么拓展

| 目标 | 做法 | 要不要动 SnowLuma |
| --- | --- | --- |
| 加功能（签到/管理/查询） | 写 NoneBot 插件，放 `stack\nonebot\plugins\` | 不用 |
| 调人设/AI | 改 `persona.env` 或换 `LLM_BASE_URL`（本地模型也走 OpenAI 兼容） | 不用 |
| 程序化控制 | `npm i @snowluma/sdk`，类型化调动作、订阅事件 | 不用 |
| 让 AI 客户端直接操作 QQ | MCP：`npx -y @snowluma/mcp`，`read` / `write` 模式 | 不用 |
| 群管理、空间、相册、流式上传 | OneBot 扩展动作（`qzone/*`、`group-album/*`、`stream/*`） | 不用 |
| 多账号分治 | 每号独立端口（如 3100/3101）+ 每号独立 NoneBot 实例或按 `self_id` 分流 | 改配置 |
| 外部系统通知 | 订阅 `notice_type: bot_status`，或 WebUI 的 webhook/邮件 | 不用 |
| 上服务器 7×24 | Linux + 官方 Docker（镜像含 Linux QQ），迁 `config\` 后重新扫码 | 换部署形态 |
| 性能 | 降 `SNOWLUMA_LOG_LEVEL`、关 `historySync`、按需关适配器 | 改配置 |

**原则**：能不改 SnowLuma 就别改——它是「源码可见但非 OSI 开源」的第三方项目，改内核等于自己维护一个分支；所有业务扩展放在 NoneBot 侧，升级 SnowLuma 时只要保证 OneBot 接口不变即可。

---

## 七、如果要修（等你点头，本次不动）

| 优先级 | 事项 | 影响面 |
| --- | --- | --- |
| 高 | 会话键改群级（`group_<群号>`），让「其他人接话」真正生效 | 只动 persona 插件 |
| 高 | 100000002 换 3100/3101，消除 `EADDRINUSE` | 只动它那份账号配置 |
| 中 | `ping` 插件也按 `BOT_UIN` 过滤 | 只动 ping |
| 中 | 测试实例用独立 `data` 目录 | 动测试脚本 |
| 低 | 凭据外置到单一文件并按需注入 | 动启动脚本 |
