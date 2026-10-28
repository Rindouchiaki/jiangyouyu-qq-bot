# 酱油鱼 · 一个住在 QQ 群里的赛博鱼

「酱油鱼」是一个跑在**本机 Windows** 上的 QQ 群聊机器人：一个二次元傲娇女孩子人设，在群里像普通群友一样聊天，
被叫到才应、偶尔冒个泡；会记得群友、看懂表情包和图片，也能查六款米哈游 / 库洛 / 鹰角游戏的抽卡、战绩和面板。

> 自用项目，跑在一台家用 PC 上，不面向公网、不做多租户。

## 怎么搭起来的

```
QQ NT 桌面版 → SnowLuma（OneBot v11）→ 反向 WS → NoneBot2（bot/）→ DeepSeek
                                                    ├── 早柚核心：游戏查询
                                                    └── 本地 OCR + 视觉小模型：看图
```

- [SnowLuma](https://github.com/snowluma/snowluma)：把 QQ NT 转成 OneBot v11
- [NoneBot2](https://nonebot.dev/) + DeepSeek：人设、聊天、记忆
- 早柚核心：原神 / 星铁 / 绝区零 / 崩坏3 / 鸣潮 / 终末地的游戏查询和每日签到
- Windows OCR + llama.cpp（Qwen3-VL-2B）：把图片和表情变成几个字的图卡

## 快速开始

前置：Windows 10/11、Git、QQ NT 桌面版。

```powershell
git clone https://github.com/Rindouchiaki/jiangyouyu-qq-bot.git
```

双击仓库根目录的 **`一键部署.cmd`**，按提示填 API Key 和机器人 QQ 号，脚本会装好依赖并在后台启动。
之后日常用 `一键启动.cmd` / `一键停止.cmd` / `一键更新.cmd`。

## 文档

- [`docs/部署指南.md`](docs/部署指南.md)：从零部署、迁移、日常使用和常见问题
- [`docs/使用手册.md`](docs/使用手册.md)：装好之后怎么用——指令、档位、好感、记忆、识图、参数
- [`docs/早柚核心接入.md`](docs/早柚核心接入.md)：游戏查询的安装、配置和群友用法
- [`docs/架构与运维.md`](docs/架构与运维.md)：端口、数据位置、排障顺序
- [`AGENTS.md`](AGENTS.md)：给接手的人和 AI 助手：代码约定、待确认的问题、设计取舍
- [`CHANGELOG.md`](CHANGELOG.md)：每个 PR 修了什么，最新的在最上面

## 说明

- 项目基于 SnowLuma 的自托管许可使用；SnowLuma 源码可见但非 OSI 开源，商业使用需另行授权。
- 表情包来自作者自己 QQ 号的收藏，`stickers/index.json` 里只有哈希与文字标签，不含图片本体。
- 请把它当私人玩具：别拿去刷屏、别拿去骚扰别人、别用来假装真人做欺骗性的事。

MIT License © 2026 酱酱鱼
