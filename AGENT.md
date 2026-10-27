# AGENT.md · 给接手的人和 AI 助手

这份文件记录这个仓库的约定、已经修过的问题和还没修的问题。改代码前先读一遍；修掉一条就把它从「待修」挪到「已修」。

---

## 项目一句话

本机 Windows 上的 QQ 群聊机器人「酱油鱼」：QQ NT → SnowLuma（OneBot v11）→ 反向 WS → NoneBot2（`bot/`）→ DeepSeek。
详细架构见 `README.md` 和 `docs/架构与运维.md`。

## 代码约定（改代码必须遵守）

- **语言**：注释、日志、回复文案一律中文；注释短，只写关键原因，不写过程。
- **换行符**：`README.md`、`AGENT.md`、`docs/*.md`、`.gitignore`、`LICENSE`、`scripts/启动全部.ps1`、`tools/ocr_win.ps1` 是 LF，其余文本文件（`.py`、`.ps1`、`.json`、`persona.env.example` 等）是 **CRLF**。改前用 `file` 确认，改后保持原样。
- **配置**：全部走环境变量，`bot/bot.py` 先 `load_dotenv(bot/persona.env)` 再导入插件，所以插件在模块级 `os.getenv` 就能读到。新增配置项同步写进 `persona.env.example`。
- **权限判断**：开发者专用指令一律写成 `if not DEV_UIN or str(event.get_user_id()) != DEV_UIN: return`，未配置时拒绝所有人，不要写成 `if DEV_UIN and ...`。
- **纯逻辑放 `bot/persona_rules.py`**：不依赖 NoneBot，方便离线测。
- **提交**：一个问题一个分支一个 PR，squash merge；提交信息用 `fix(范围): 中文说明`。

## 怎么测

```powershell
$env:PYTHONPATH='bot'
python tests\test_persona_rules.py   # 纯规则，不连 QQ、不调模型
```

`tests/*.py` 里的 `sys.path.insert(... / "nonebot")` 指向一个不存在的目录（旧目录名），所以要手动设 `PYTHONPATH=bot`。`tests/test_vision_offline.py` 需要 Windows OCR、Pillow，以及写死的 `Z:\snowluma\stickers`、`Z:\snowluma\_research` 目录。

---

## 已修（2026-10）

| PR | 问题 | 改法 |
|---|---|---|
| #1 | 群友能用 `/回忆` 翻出主人整个白守库的私人笔记；A 群/私聊的记忆会被带到 B 群；日记内容进了 system prompt，`/记` 可以长期改人设 | `memory.py` 只读写 `BAISHOU_VAULT/Journals`；落盘带会话标签「群+群号」「私聊+QQ号」，自动回忆只取本会话和开发者笔记；记忆改放 user 消息并标注「不是指令」；`/记 /回忆 /记忆` 仅开发者 |
| #2 | 群名片改成「我」/开发者名/外号就能冒充机器人或开发者；正文换行能伪造别人发言 | `persona_rules.safe_name` 按归一化后的「骨架」比对，撞名加 QQ 尾号；当前消息压成一行 |
| #3 | 管理指令在 `DEV_UIN` 为空时人人可用；`/缓存` 每次都 ImportError | 统一改成未配置即拒绝；`cache_cleanup` 从环境变量读 `DEV_UIN` |
| #4 | `config/onebot.reverse-ws.json` 监听 `0.0.0.0`，反向 WS 连 8080 且 token 为空 | 改 `127.0.0.1`、`18080`、token 占位符 |
| #5 | 任何人都能让机器人拿号主的米游社 Cookie 查体力 | 体力/便笺仅 `DEV_UIN`；米游社便笺接口本来只能查 Cookie 所属账号 |
| #7 | 全局限流 `REPLY_PER_MIN` 只拦随机插话，被 @、接续、嫌烦收尾、配图都不受限 | 群聊所有主动消息都计入一分钟总额度并分档：用到 1/2 停插话和自动配图，3/4 停接续，用满才停被叫；私聊、被叫触发的抽卡定型文、指令不拦（抽卡模式下的随机插话照常按插话档）；样例去掉重复的 `REPLY_PER_MIN`（仍为 4） |

**自动记忆仍然开着**：`PRIVATE_MIRROR`、`GROUP_MIRROR` 默认 1；私聊每条都落盘，群聊只记被叫/接续的对话；问到「记得/上次」照常带本会话最近 5 条。改的只是按会话隔离和手动指令的权限。

### 已知限制

- 繁体变体（如「醬醬魚」）不会被 `safe_name` 认出，需要的话把繁体写进 `NICKNAMES`。
- 改动前写入的旧日记没有新标签，自动回忆不会选中它们。旧群聊行是 `- HH:MM 群123 名字：…`，下一行 `- HH:MM 我：…` 是回复，可以写脚本补成 `[群123]` 标签；旧私聊行只有 `[私聊]`，无法归属到人，只能私聊里 `/回忆` 查。

---

## 待修

按影响从大到小。行号以 `main` 为准，改之前再确认一次。

### Bug

1. **动图图卡标签被覆盖** — `bot/vision.py` 约 448–451 行连写两个 `if desc:`，第二个把 `[动图:…]` 改回 `[图片:…]`。删掉第二个即可。
2. **一键启动脚本路径错** — `scripts/启动全部.ps1` 在 `scripts/` 里却调用 `$PSScriptRoot\scripts\start-all-here.ps1`，实际变成 `scripts\scripts\…`。
3. **从仓库根目录启动时插件不加载** — `bot/bot.py` 的 `nonebot.load_plugins("plugins")` 是相对**当前工作目录**的（NoneBot 源码 `PluginManager.search_path` 的说明如此）。README 让人在根目录跑 `python bot\bot.py`，会找不到 `plugins`。不能简单换成绝对路径（NoneBot 会按 cwd 推模块名，变成 `bot.plugins.xxx`，和 `bot.py` 冲突）；在 `load_plugins` 前 `os.chdir(Path(__file__).parent)`，或 README 改成先 `cd bot`（`run-nonebot.ps1` 就是先 `Set-Location`）。
4. **脚本和文档还指向旧目录** — `run-nonebot.ps1`、`start-all.ps1`、`start-all-here.ps1`、`verify-stack.ps1` 写死 `Z:\snowluma\stack\nonebot`、`stack\.venv`，其余脚本也写死 `Z:\snowluma`；`bot/bot.py` 文档字符串提到不存在的 `stack\docker-compose.yml`。仓库里代码在 `bot/`。
5. **后台任务可能被回收** — `bot/plugins/game_query.py` 的 `asyncio.create_task(_loop())` 没保存引用。

### 配置和文档不一致

6. `bot/persona.env.example` 里 `ENGAGE_MAX_TURNS` 写了两次（8 和 4），后一个生效。
7. `REPLY_FOLLOW_COOLDOWN` 在样例里有，代码不读（代码读 `REPLY_GROUP_COOLDOWN`）。
8. README 模式表写「米游抽卡 被叫 10%」，代码和样例是 1.8%（`REPLY_PROB_GACHA=0.018`）；`SNUB_SECONDS` README/样例是 100，代码默认 300。
9. 没有 `requirements.txt` / `pyproject.toml`；`httpx`、`python-dotenv` 不在 README 的 pip 命令里，靠间接依赖。反向 WS 需要 NoneBot 驱动（一般是 `nonebot2[fastapi]`），README 只装了裸 `nonebot2`，需确认是否被其它包间接装上。
10. 多处默认路径写死 `Z:\snowluma`（`sticker_lib.py`、`vision.py`、`mys.py`、`game_data.py`、`tools/export_qq_emoji.py`、`tools/tag_stickers.py`、样例里的 `GACHA_TEXT_FILE`）。
11. `docs/SnowLuma-QQ机器人调查报告.md`、`docs/SnowLuma-拓展路线评估-Docker.md` 还是 8080 + 空 token 的旧示例。
12. 提醒（未实测）：已有的账号级 `onebot_<uin>.json` 会叠加在全局 `onebot.json` 上，可能把 `0.0.0.0` / 8080 带回来；README 可以提醒检查。
13. 抽卡文案有三份：`persona.py` 里写死的列表、`gacha_texts.py`、`gacha-texts/*.txt`。
14. `bot/bot_guard.py` 的 `BOT_UIN` 默认 `100000001`，`bot/bot.py` 默认空，两边不一致。

### 小问题

15. `BOT_UIN` 在多处重复判断（`bot.py` 全局预处理器、`is_our_bot()`、`persona.py` 的 `_is_target_account()`、各插件手写的 `self_id` 比较），可以只留预处理器。
16. 静音模式的判断在识图之后，静音的群照样跑 OCR / 视觉模型。
17. `vision._match_sticker` 每次命中都重读 `index.json`；`_save_cards` 每张图都同步重写整个缓存文件。
18. `/回忆` 和自动回忆每次都全量扫描日记目录，日记多了会慢。
19. 游戏数据和头像经第三方代理 `gh-proxy.com` 下载（只是数据和图片）。
20. `scripts/install-snowluma.ps1` 下载后不校验哈希。
21. `docs/SnowLuma-参数与原理.md` 里有三个 accessToken 的首尾片段；虽然截断了，建议换一组新 token。
22. 测试只覆盖 `persona_rules` 和离线识图；`persona.py` 的主处理流程、`memory.py` 的标签过滤没有测试。

---

## 改之前先想清楚的地方

- **记忆隔离是刻意的**：不要为了「记得更多」把 `memory.recent` 的会话标签过滤去掉，否则私聊和别的群的内容会被带进来。想让机器人跨群记住某件事，用开发者 `/记`（署名 `DEV_NAME`，任何会话问到「记得/上次」时都会被带出）。
- **游戏角色查询（`/hsr 名字`、`/zzz 名字`）和绑定对所有群友开放**，这是设计；只有用号主 Cookie 的体力/便笺是开发者专用。
- **限流分档是刻意的**：`persona_rules.QUOTA_TIERS` 决定额度用到多少时停哪类回复。私聊、被叫触发的抽卡定型文、`/hsr` 等指令按需求不拦，不要顺手加进去。
- **群名片会进 prompt**：任何新加的「名字 → 身份」逻辑都要走 `safe_name`，不要直接拿 `sender.card` 拼进模型输入。
