# AGENT.md · 给接手的人和 AI 助手

这份文件记录这个仓库的约定、已经修过的问题和还没修的问题。改代码前先读一遍；修掉一条就把它从「待确认」挪到「已修」。

---

## 项目一句话

本机 Windows 上的 QQ 群聊机器人「酱油鱼」：QQ NT → SnowLuma（OneBot v11）→ 反向 WS → NoneBot2（`bot/`）→ DeepSeek。
详细架构见 `README.md` 和 `docs/架构与运维.md`。

## 代码约定（改代码必须遵守）

- **语言**：注释、日志、回复文案一律中文；注释短，只写关键原因，不写过程。
- **换行符**：只有 `README.md`、`AGENT.md`、`docs/架构与运维.md`、`.gitignore`、`LICENSE`、`tools/ocr_win.ps1` 是 LF，其余文本文件（`.py`、`.ps1`、`.json`、其它 `docs/*.md`、`persona.env.example` 等）都是 **CRLF**。改前数一下 `\r` 确认，改后保持原样；`scripts/*.ps1` 和 `tools/ocr_win.ps1`、`tools/ocr_stickers_2x.ps1` 带 UTF-8 BOM，也要保留。
- **配置**：全部走环境变量，`bot/bot.py` 先 `load_dotenv(bot/persona.env)` 再导入插件，所以插件在模块级 `os.getenv` 就能读到。新增配置项同步写进 `persona.env.example`。
- **权限判断**：开发者专用指令一律写成 `if not DEV_UIN or str(event.get_user_id()) != DEV_UIN: return`，未配置时拒绝所有人，不要写成 `if DEV_UIN and ...`。
- **纯逻辑放 `bot/persona_rules.py`**：不依赖 NoneBot，方便离线测。
- **提交**：一个问题一个分支一个 PR，squash merge；提交信息用 `fix(范围): 中文说明`。

## 怎么测

```powershell
python tests\test_persona_rules.py   # 纯规则，不连 QQ、不调模型
```

测试自己会把 `bot/` 加进 `sys.path`。`tests/test_vision_offline.py` 需要 Windows OCR、Pillow，以及写死的 `Z:\snowluma\stickers`、`Z:\snowluma\_research` 目录。

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
| #8 | 游戏数据定时刷新的 `asyncio.create_task` 没留引用，可能被回收 | 存进模块级 `_refresh_task` |
| #9 | `vision.py` 连写两个 `if desc:`，视觉模型描述的动图被改标成图片 | 删掉第二个（旧图卡缓存 7 天后自然过期） |
| #10 | `scripts/启动全部.ps1` 调用不存在的 `scripts\scripts\start-all-here.ps1` | 改调同目录脚本，用法说明对齐 README |
| #11 | 从仓库根目录跑 `python bot\bot.py` 时插件一个都不加载（NoneBot 按 cwd 找插件目录） | 启动时 `os.chdir` 到 `bot/`，与 `run-nonebot.ps1` 一致 |
| #12 | 样例里 `ENGAGE_MAX_TURNS` 写了两次 | 去掉被覆盖的那条，仍为 4 |
| #13 | 测试和 `tools/build_game_data.py` 往 `sys.path` 加不存在的 `nonebot/` | 改指 `bot/` |

**自动记忆仍然开着**：`PRIVATE_MIRROR`、`GROUP_MIRROR` 默认 1；私聊每条都落盘，群聊只记被叫/接续的对话；问到「记得/上次」照常带本会话最近 5 条。改的只是按会话隔离和手动指令的权限。

### 已知限制

- 繁体变体（如「醬醬魚」）不会被 `safe_name` 认出，需要的话把繁体写进 `NICKNAMES`。
- 改动前写入的旧日记没有新标签，自动回忆不会选中它们。旧群聊行是 `- HH:MM 群123 名字：…`，下一行 `- HH:MM 我：…` 是回复，可以写脚本补成 `[群123]` 标签；旧私聊行只有 `[私聊]`，无法归属到人，只能私聊里 `/回忆` 查。

---

## 待确认（可能是设计，先别直接改）

下面这些拿不准是 bug 还是作者有意为之，改之前先和作者确认。行号以 `main` 为准，动手前再核一次。

### 目录布局：作者本机 vs 仓库

作者本机实际跑在 `Z:\snowluma\stack\nonebot\`（`bot.py` 和插件在这一层），仓库里对应的是 `bot/`。下面几条在作者本机是对的，在仓库布局里是错的；要先定下以哪种布局为准再统一。

1. `scripts/` 里 `run-nonebot.ps1`、`start-all.ps1`、`start-all-here.ps1`、`verify-stack.ps1` 写死 `Z:\snowluma\stack\nonebot`、`stack\.venv`；`install-snowluma.ps1`、`start-vl.ps1`、`stop-all.ps1` 写死 `Z:\snowluma`。
2. `bot/vision.py` 的 `OCR_SCRIPT` 默认是 `bot.py 所在目录/../../tools/ocr_win.ps1`：作者布局下指向 `Z:\snowluma\tools`，仓库布局下会跑到仓库外面，识图 OCR 找不到脚本（可用 `OCR_SCRIPT` 环境变量覆盖）。
3. 多处默认路径写死 `Z:\snowluma`：`sticker_lib.py`、`vision.py`、`mys.py`、`game_data.py`、`tools/export_qq_emoji.py`、`tools/tag_stickers.py`、`tests/test_vision_offline.py`、样例里的 `GACHA_TEXT_FILE`。
4. `bot/bot.py` 的文档字符串和 `load_plugins` 上方注释、`scripts/verify-stack.ps1`（`stack\tests\fake_onebot_client.py`）、`stickers/README.md` 和几篇 `docs/` 还写着 `stack/nonebot`、`stack\docker-compose.yml` 等旧路径。

### 数值和配置对不上

5. README 模式表写「米游抽卡 被叫 10%」，代码默认和样例是 1.8%（`REPLY_PROB_GACHA=0.018`）。哪个是本意？
6. `SNUB_SECONDS`：README 和样例是 100 秒，代码默认 300；`ENGAGE_MAX_TURNS` 样例是 4，代码默认 8。样例生效时没问题，缺配置时会退回代码默认值。
7. `REPLY_FOLLOW_COOLDOWN` 在样例里有，代码不读（代码读 `REPLY_GROUP_COOLDOWN`）。是该删样例，还是代码漏读了？
8. `bot/bot_guard.py` 的 `BOT_UIN` 默认 `100000001`（作者的机器人号），`bot/bot.py` 默认空；不配置时前者只认这个号，后者谁都放行。
9. 没有 `requirements.txt` / `pyproject.toml`；`httpx`、`python-dotenv` 不在 README 的 pip 命令里。反向 WS 需要 NoneBot 驱动（一般是 `nonebot2[fastapi]`），README 只装了裸 `nonebot2`，需确认是否被其它包间接装上。

### 设计取舍

10. 静音模式的判断在识图之后：静音的群照样跑 OCR / 视觉模型。图卡会进上下文历史，可能是有意保留，也可能只是浪费。
11. `/圣经` 只有开发者能用；如果想让群友也能触发，需要放开权限（已经计入群聊限流）。
12. 抽卡文案有三份：`persona.py` 里写死的列表、`gacha_texts.py`、`gacha-texts/*.txt`（`GACHA_TEXT_FILE` 优先）。
13. 游戏数据和头像经第三方代理 `gh-proxy.com` 下载（只是数据和图片，国内网络可能就是为此）。
14. `BOT_UIN` 在多处重复判断（`bot.py` 全局预处理器、`is_our_bot()`、`_is_target_account()`、各插件手写的 `self_id` 比较），可以只留预处理器。
15. 旧日记补会话标签：旧群聊行 `- HH:MM 群123 名字：…` 能可靠补成 `[群123]`，要不要写一次性迁移脚本。

### 运维和文档

16. `docs/SnowLuma-QQ机器人调查报告.md`、`docs/SnowLuma-拓展路线评估-Docker.md` 还是 8080 + 空 token 的旧示例。
17. 提醒（未实测）：已有的账号级 `onebot_<uin>.json` 会叠加在全局 `onebot.json` 上，可能把 `0.0.0.0` / 8080 带回来；README 可以提醒检查。
18. `docs/SnowLuma-参数与原理.md` 里有三个 accessToken 的首尾片段；虽然截断了，建议换一组新 token。
19. `scripts/install-snowluma.ps1` 下载后不校验哈希。

### 性能和测试

20. `vision._match_sticker` 每次命中都重读 `index.json`；`_save_cards` 每张图都同步重写整个缓存文件。
21. `/回忆` 和自动回忆每次都全量扫描日记目录，日记多了会慢。
22. 测试只覆盖 `persona_rules` 和离线识图；`persona.py` 的主处理流程、`memory.py` 的标签过滤没有测试。

---

## 改之前先想清楚的地方

- **记忆隔离是刻意的**：不要为了「记得更多」把 `memory.recent` 的会话标签过滤去掉，否则私聊和别的群的内容会被带进来。想让机器人跨群记住某件事，用开发者 `/记`（署名 `DEV_NAME`，任何会话问到「记得/上次」时都会被带出）。
- **游戏角色查询（`/hsr 名字`、`/zzz 名字`）和绑定对所有群友开放**，这是设计；只有用号主 Cookie 的体力/便笺是开发者专用。
- **限流分档是刻意的**：`persona_rules.QUOTA_TIERS` 决定额度用到多少时停哪类回复。私聊、被叫触发的抽卡定型文、`/hsr` 等指令按需求不拦，不要顺手加进去。
- **群名片会进 prompt**：任何新加的「名字 → 身份」逻辑都要走 `safe_name`，不要直接拿 `sender.card` 拼进模型输入。
