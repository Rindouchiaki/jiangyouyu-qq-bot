# 酱油鱼 · 一个住在 QQ 群里的赛博鱼

「酱油鱼」是一个跑在**本机 Windows** 上的 QQ 机器人人格：底子是 [SnowLuma](https://github.com/snowluma/snowluma)
（把 QQ NT 转成 OneBot v11），脑袋是 [NoneBot2](https://nonebot.dev/) + 大模型，记忆放在白守（BaiShou）的
Markdown 日记里，眼睛是本地 OCR + 一个 2B 的视觉小模型。

它不追求「有用」：在群里说话像个普通群友，短、口语、有点脾气；被叫到才应、聊得热乎了会接话、
偶尔路过插一句嘴；被追问烦了会直接冷处理一百秒。真正被问正经事时又会正经答。

> 自用项目，跑在一台家用 PC 上，不面向公网、不做多租户。里面的 token、密码、QQ 号全部是占位符，
> 自己部署时请换成自己的。

## 它长什么样

```
QQ NT 客户端（桌面版，已登录）
      │  本机进程注入（SnowLuma 自带 hook）
      ▼
SnowLuma  ── WebUI 127.0.0.1:5099   OneBot HTTP 3000 / WS 3001
      │  反向 WebSocket（Universal 客户端）
      ▼
NoneBot2  127.0.0.1:18080/onebot/v11/ws
      ├── persona       人设 / 情绪 / 接话判定 / 模式（省话·话痨·静音·米游抽卡）
      ├── vision        图卡：表情哈希匹配 → Windows OCR → 本地视觉模型
      ├── memory        白守 Markdown 日记（/记 /回忆 /记忆）
      ├── stickers      513 张表情包（含 93 张 GIF）
      ├── GenshinUID    早柚核心连接插件：星铁/绝区零/崩坏3 查询转给核心（另起进程）
      ├── cache_cleanup 下载媒体 24h 自动清理
      └── parser        哔哩哔哩/微博/抖音/小红书…链接解析（视频直发原片）
      ▼
DeepSeek（OpenAI 兼容接口）—— 只在真要回话时才调用
```

## 功能

**说话**
- 单条 ≤20 字、口语、不带括号动作/emoji、不提 AI；求助类问题自动放宽到 80 字并给实质结论。
- 被 @ / 喊名字 / 同一个人在接续窗口内说话 → 才会开口；其余靠 10% 概率随机插话，插完就撤。
- 情绪跟随上一句：被「调教、捏、rua」会炸毛，被夸会软下来；同一句追问太多会被判定为「烦」→ 冷处理 100 秒。
- 每条回复有冷却；群聊另有每分钟总额度（默认 4 条）：用到一半停插话和配图，用到 3/4 停接续，用满才停被叫。
  私聊、被叫触发的抽卡定型文和游戏查询指令不受限。

**模式（每个群可以单独设，`/模式` 仅开发者可用）**

| 模式 | 被叫 | 接续 | 主动插话 | 同群冷却 |
|---|---|---|---|---|
| 省话（默认） | 50% | 15% | 10% | 10s |
| 话痨 | 100% | 100% | 20% | 3s |
| 静音 | 0 | 0 | **0** | — |
| 米游抽卡 | 1.8% | 0 | 10% | 60s |

静音和插话彻底分开：静音就是一句话不说；`/插话` 可以单独把插话关掉或调成任意百分比。

**看图和表情**
- 表情库用**多帧**感知哈希索引（513 张 / 736 帧）。QQ 把动图表情压成静态预览时，也能靠任意一帧认出来，
  输出 `[表情:动图｜其他｜截图选老婆]` 这种图卡，几 token 就够。
- 库外的图：Windows 自带 OCR（中文）+ 本地 Qwen3-VL-2B（llama.cpp）描述，图卡塞进上下文，一条 5–40 token。
- 有人追问「刚才那张图啥意思」时，会把最近一张图重新做成图卡补进上下文。

**其他**
- `/记`、`/回忆`、`/记忆`（仅开发者）：写/读白守库里 `Journals/` 下的 Markdown 日记；群里被叫和私聊会自动落盘，
  按群/私聊分开打标签，只在同一会话里被想起。
- 星铁 / 绝区零 / 崩坏3：抽卡记录、深渊类战绩、角色面板等，由早柚核心提供（`sr帮助`、`zzz帮助`、`bbb帮助`），
  私聊（可用群临时会话）发「扫码登录」绑定米游社账号；安装见 `docs/早柚核心接入.md`。
- 视频链接直接发原片（不渲染卡片），下载的媒体 24 小时自动清理。
- `/用量`：看当天 token 消耗与缓存命中率；`/圣经`：抽卡定型文（仅开发者）。

## 目录结构

```
bot/                 NoneBot2 源码（人格、图卡、记忆、插件）
  plugins/           各功能插件
  persona.env.example 配置样例（复制成 persona.env 再填）
scripts/             部署 / 启动 / 停止 / 自检脚本（根目录的 一键*.cmd 是双击入口）
tools/               表情库导出、OCR 等工具
tests/               离线单测 + 模拟 OneBot 客户端
config/              SnowLuma 配置样例（onebot.json / runtime.json）
docs/                调研与设计文档
gacha-texts/         抽卡定型文（每个 txt 一篇，随机挑）
stickers/index.json  表情库元数据（不含图片本体）
```

## 快速开始

前置：Windows 10/11、Git、QQ NT 桌面版。Python、uv、SnowLuma、早柚核心由脚本自动装。

```powershell
git clone https://github.com/Rindouchiaki/jiangyouyu-qq-bot.git
```

然后双击仓库根目录的 **`一键部署.cmd`**：问 API Key 和两个 QQ 号，装好全部依赖、生成配置（随机 token、只听 127.0.0.1），
接着在后台启动整套服务。之后日常用 `一键启动.cmd` / `一键停止.cmd`；GitHub 上合并了 PR（包括每天自动开的依赖更新 PR）以后双击 `一键更新.cmd`。
完整步骤（第一次登录 SnowLuma、从旧的 `Z:\snowluma` 迁移、常见问题）见 **[`docs/部署指南.md`](docs/部署指南.md)**。

命令行等价写法（脚本会按端口跳过已在跑的服务）：

```powershell
.\scripts\setup.ps1 -Start          # 部署 + 启动（= 一键部署.cmd）
.\scripts\启动全部.ps1             # QQ → 本地视觉模型 → SnowLuma → 早柚核心 → NoneBot
.\scripts\启动全部.ps1 -Status     # 只看状态
.\scripts\启动全部.ps1 -Stop       # 全停（QQ 保留）
.\scripts\verify-stack.ps1         # 全链路自检
.\scripts\update.ps1               # 拉代码 + 依赖换到锁定版本 + 重启（= 一键更新.cmd）
```

## 成本

一次普通回复约 600 输入 token / 6 输出 token，DeepSeek 前缀缓存命中率约 30%（system 提示词固定在最前面）。
图卡方案让「看图」本身几乎不花 token —— 表情 5–12 token，OCR 文字 30–42 token，无字图才走本地小模型。

## 文档

- [`docs/部署指南.md`](docs/部署指南.md)：从零部署、从旧目录迁移、日常使用和常见问题
- [`docs/SnowLuma-QQ机器人调查报告.md`](docs/SnowLuma-QQ机器人调查报告.md)：SnowLuma 是什么、怎么部署、和各家的对比
- [`docs/SnowLuma-参数与原理.md`](docs/SnowLuma-参数与原理.md)：OneBot 网络、反向 WS、token、WebUI 那些坑
- [`docs/图像与表情包最小Token方案.md`](docs/SnowLuma-图像与表情包最小Token方案.md)：图卡架构与 token 账本
- [`docs/调研-星铁绝区零与B站解析.md`](docs/调研-星铁绝区零与B站解析.md)：游戏数据源、B 站解析链路
- [`docs/SnowLuma-拓展路线评估-Docker.md`](docs/SnowLuma-拓展路线评估-Docker.md)：为什么最后没上 Docker

## 说明

- 项目基于 SnowLuma 的自托管许可使用；SnowLuma 源码可见但非 OSI 开源，商业使用需另行授权。
- 表情包来自作者自己 QQ 号的收藏，`stickers/index.json` 里只有哈希与文字标签，不含图片本体。
- 请把它当私人玩具：别拿去刷屏、别拿去骚扰别人、别用来假装真人做欺骗性的事。

MIT License © 2026 酱酱鱼
