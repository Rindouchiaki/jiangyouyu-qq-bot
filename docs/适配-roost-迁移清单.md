# 现有 QQ 机器人 → dsh-roost 迁移清单

> 现状：NoneBot2 + SnowLuma（NTQQ 钩子）自建栈，代码在 `repo/`，数据在 `repo/bot/data/`，
> 运行靠 `scripts/start-all-here.ps1` + 计划任务 `JiangyouyuStack`。
> 目标：改成 dsh-roost（QQ 开放平台官方接口 + Roost 外接协议），由 DSH 提供会话、工具、记忆、人格。

## 一、一句话结论

- **能直接复用的**：人设文本、表情包（已迁完）、以撒库、影之诗卡库、SZB 卡组库、早柚核心的游戏查询接口——这些是「数据 + 纯函数」，换成 MCP 工具即可。
- **由 roost 原生替代的**：QQ 收发、会话、记忆、上下文压缩、主动搭话、冷却/配额/权限分档、语音合成、群管理、面板与备份。
- **会缩水或丢弃的**：①表情回应（官方接口没有 reaction）；②群内非 @ 消息的监听（官方 bot 只能收 @/私聊，除非群主在手机 QQ 开「接收所有消息」）；③SnowLuma 兼容层、缓存清理、watchdog 那套运维。
- **迁移量最大的是 B 站动态推送**：要重写成 roost 扩展（轮询 + `proactive:write` 投递），不再是 NoneBot 插件。

## 二、功能对照表

| # | 功能 | 现在的实现 | roost 落点 | 工作量 | 处置 |
|---|---|---|---|---|---|
| 1 | QQ 收发 / 群消息 | SnowLuma（NTQQ 钩子）+ NoneBot OneBot | Roost 框架 `roost-host/1` + 官方 API | 现成 | 替换 |
| 2 | 人设 / 语气 | `bot/persona_rules.py`（800+ 行提示词）+ `persona.env` 30 余项参数 | roost 人格四段式（性格/开场白/说话示例/世界书） | M | 改写 |
| 3 | 回复频率档位 `/模式` | `reply_modes.json` + 冷却/概率闸门 | roost 冷却/配额（按群/私聊）+ 人格措辞 | S | 改写 |
| 4 | 表情回应（👀/🎉） | `snowluma_compat.py` → `set_msg_emoji_like` | 官方 API 无 reaction | — | 丢弃 |
| 5 | 表情包库 | `stickers/` 459 张 + `index.json` + `sticker_lib.py` | `stickers/` 分类目录 + `.tags` 侧车 + `sticker_pick` | 已完成 | 复用 |
| 6 | 看图 / OCR / VLM | `bot/vision.py`（Windows OCR + llama.cpp Qwen3-VL 2B） | `read_image` + `/v1/llm.vision`；OCR 可保留成扩展工具 | S | 缩水 |
| 7 | 事件记忆 | `episodes.db`（bge-m3 向量）+ 每日整理 | roost 三层记忆（事实/日记/图谱）+ `memory_note/search` | M | 导入 |
| 8 | 知识库 `/学习` | `knowledge.db` + `/学习` `/知识库` | 记忆 + 扩展工具（可保留原库做只读检索） | M | 改造 |
| 9 | 以撒查询 `/以撒` | `isaac_wiki.db` 41MB / 3243 篇 / 7863 块 | MCP 工具 `isaac_lookup`（复用 `bot/isaac_wiki.py`） | S | 复用 |
| 10 | 影之诗 `/卡` | `sv_data.py` + `Z:\ShadowverseWB_card_data` 962MB / 982 卡 | MCP 工具 `sv_card`（列表/详情/进化图） | M | 复用 |
| 11 | SZB 卡组 `/szb` | `szb_decks.py` + 16MB 图 + 抓取脚本 | MCP 工具 `szb_deck`（按序号/职业查，发合并转发） | S | 复用 |
| 12 | B 站动态推送 | NoneBot + Bison 轮询 + 解析插件 | **扩展**：轮询 + `/v1/proactive/submit` 投递 | L | 重写 |
| 13 | B 站链接解析 | parser 插件（收到的任意链接） | 只在 @ 机器人时解析（官方 API 拿不到普通消息） | M | 缩水 |
| 14 | 游戏查询（原/铁/绝） | 早柚核心 `127.0.0.1:8765` HTTP | MCP 工具包装该 HTTP 接口 | M | 复用 |
| 15 | 主动搭话 / 自驱 | `persona.py` 主动找人 + 话题 | roost 原生 proactive / 自驱引擎 / 凌晨巩固 | 现成 | 用原生 |
| 16 | 语音 / ASR | 无 | roost TTS（sherpa/edge/GPT-SoVITS）+ 语音转写 | 现成 | 新增 |
| 17 | 群管理（禁言/踢人） | 无 | `qq_mute` / `qq_kick` / `qq_group_info` | 现成 | 新增 |
| 18 | 斜杠指令 20+ | NoneBot matcher | 自然语言 + 工具；世界书写「查卡 → sv_card」这类映射 | M | 改写 |
| 19 | 运维 | `schtasks JiangyouyuStack` + watchdog + 5 个 ps1 | DSH 常驻 + roost 面板（启动/备份/更新） | S | 简化 |
| 20 | 缓存清理 | `cache_cleanup.py`（24h 视频/图） | roost `images/` 7 天自动清；不再下载视频则不需要 | — | 丢弃 |

## 三、需要新写的扩展（MCP 工具）

| 扩展 | 提供 | 依赖 |
|---|---|---|
| `sv-card` | `sv_search(query)` / `sv_detail(id)` | `bot/sv_data.py` + 卡库 JSON + 图片索引 |
| `isaac` | `isaac_lookup(topic)` | `bot/isaac_wiki.py` + `isaac_wiki.db` |
| `szb` | `szb_query(name/id/cls)` | `bot/szb_decks.py` + `decks.json` + 图 |
| `gscore` | `game_note(uid, game)` | 早柚核心 HTTP（8765） |
| `bili-push`（扩展，非工具） | 轮询 UP 动态 → `proactive:submit` | B 站 cookie + `proactive:write` |

工具扩展只做「数据进、文字出」；发图统一让模型写 `<<image: 路径>>`，发多图用合并转发。

## 四、数据迁移

| 资产 | 现状位置 | 大小 | 目标 |
|---|---|---|---|
| 表情包 | `repo/stickers/` | 110MB（459 张） | ✅ 已迁 `~/.dsh/dsh-roost/stickers` |
| 以撒 wiki | `repo/bot/data/isaac_wiki.db` | 41MB | 随扩展走，放 `~/.dsh/dsh-roost/ext/isaac/` |
| 影之诗卡库 | `Z:\ShadowverseWB_card_data` | 962MB | 保持原位（只读），扩展里配路径 |
| SZB 卡组 | `repo/bot/data/szb_decks` | 16MB | 同上 |
| 事件记忆 | `episodes.db` | 1.1MB | 转 `memory_note` 导入（一次性脚本） |
| 知识库 | `knowledge.db` | 540KB | 同上（或只读工具） |
| 好感/关系 | `bonds.json` + `relation_graph` | 34KB | 转图谱节点/事实 |
| 人设参数 | `bot/persona.env` | 小 | 拆进 roost 人格与配置 |
| 定型文 | `gacha-texts/` | 84KB | 人格「说话示例」或工具返回 |

## 五、清空范围方案（待确认）

**保留（绝对不能删）**

- `repo/`：git 仓库本体（`main` = `7df3ab5` 之后的远端版本）+ 代码 + `docs/` + `scripts/` + `tests/`
- `repo/.git`：回滚的唯一可靠凭据（远端还有一份）

**迁移后删除（数据先备份）**

| 目录 | 现在用途 | 大小 | 处理 |
|---|---|---|---|
| `Z:\snowluma\repo\bot\data` | 记忆/卡组/索引 | ~60MB（不含 szb 16MB） | 迁移到 roost 数据目录后删 |
| `Z:\snowluma\repo\gsuid_core` | 早柚核心（含热修） | 5.6GB | 保留服务即可，仓库里可删（可重装） |
| `Z:\snowluma\repo\.venv` | Python 环境 | 385MB | 删（按需重建） |

**清空候选（三档，从小到大）**

| 档位 | 删什么 | 释放 | 回滚方式 |
|---|---|---|---|
| 保守 | `_research`、`logs`、旧 `_backup`、`DEPLOY-STATE.md` | ~900MB | 无用文件，直接删 |
| 中等（推荐） | 上面 + `SnowLuma`、`tools`（ffmpeg/llama.cpp/vl-model）、`.venv` | ~3.5GB | SnowLuma 包可从备份 zip 还原；tools 可重新下载 |
| 彻底 | 上面 + `gsuid_core` + `gacha-texts` + 根目录 `*.md` | ~9GB | 只留 `repo/` + roost 数据；游戏查询需重装早柚核心 |

## 六、备份与回滚

1. **代码**：先把本地未提交改动提交并推到远端（`github.com` 时通时断，可用 REST API 推送），再 `git bundle create roost-migration.bundle --all`。
2. **数据**：`Compress-Archive` 打包 `bot/data/{episodes,knowledge,isaac_wiki}.db`、`bonds.json`、`reply_modes.json`、`szb_decks/`、`gacha-texts/`、`persona.env` → `Z:\snowluma\_backup\roost-migration-<日期>.zip`（约 60MB）。
3. **运行环境**：SnowLuma 现成包已有备份 `_backup\SnowLuma-2.2.1-20261113`；roost 侧在面板「备份」导出 zip。
4. **回滚路径**：`git clone`(或 bundle) → 解压数据 zip 回 `bot/data` → `scripts/setup.ps1` 重建 venv → `start-all-here.ps1`；roost 侧停用插件即可回到 NoneBot 栈（两套可以并存，端口不冲突）。

## 七、执行顺序（建议）

1. 在 roost 里跑通最小闭环：一个私聊 + 一个群，@ 能回话。
2. 迁数据（表情包已完）→ 起 `sv-card` / `isaac` / `szb` / `gscore` 四个工具，逐个验证。
3. 写人格（四段式），把 `/模式` 的档位映射成 roost 冷却与配额。
4. 最后写 `bili-push` 扩展（工作量最大，放最后）。
5. 双栈并行观察 3–7 天，确认 roost 稳定后再清空本地代码。

## 八、不可迁 / 风险

- **表情回应**：官方接口没有，直接丢失。
- **群内非 @ 消息**：官方 bot 默认收不到；「接收所有消息」要群主在手机 QQ 里开，且不保证普通群可开。
- **主动消息频次**：官方接口有主动消息配额，B 站推送不能像现在这样随时发，需要合并/节流。
- **表情包**：只能发普通图片（不进对方收藏夹），>20MB 会降级成文件。
- **人设还原度**：现在的 800 行提示词搬成四段式会有损，需要按实际对话迭代。
