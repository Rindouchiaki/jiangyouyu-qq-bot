# AGENTS.md · 给接手的人和 AI 助手

这份文件记录这个仓库的约定、已经修过的问题和还没修的问题。改代码前先读一遍；修掉一条就把它从「待确认」挪到「已修」。

---

## 项目一句话

本机 Windows 上的 QQ 群聊机器人「酱油鱼」：QQ NT → SnowLuma（OneBot v11）→ 反向 WS → NoneBot2（`bot/`）→ DeepSeek。
详细架构见 `README.md` 和 `docs/架构与运维.md`。

## 代码约定（改代码必须遵守）

- **语言**：注释、日志、回复文案一律中文；注释短，只写关键原因，不写过程。
- **换行符**：只有 `README.md`、`AGENTS.md`、`docs/架构与运维.md`、`.gitignore`、`LICENSE`、`tools/ocr_win.ps1` 是 LF，其余文本文件（`.py`、`.ps1`、`.json`、其它 `docs/*.md`、`persona.env.example` 等）都是 **CRLF**。改前数一下 `\r` 确认，改后保持原样；`scripts/*.ps1` 和 `tools/ocr_win.ps1`、`tools/ocr_stickers_2x.ps1` 带 UTF-8 BOM，也要保留。
- **配置**：全部走环境变量，`bot/bot.py` 先 `load_dotenv(bot/persona.env)`、再读 `bot/persona.local.env`（盖过同名项）后导入插件，所以插件在模块级 `os.getenv` 就能读到。新增配置项同步写进 `persona.env.example`，代码里的默认值要和样例一致。一键更新（`setup.ps1 -Update`）会按样例重写 persona.env：`common.ps1` 的 `PersonalEnvKeys`（账号、密钥、路径）和样例里没有的项保留，其余换成样例值；新增「每台机器不一样」的配置项要加进 `PersonalEnvKeys`，否则一键更新会把它冲掉。
- **目录**：仓库就是运行目录，`.venv`、`bot/persona.env`、`bot/data`、`logs`、`SnowLuma`、`gsuid_core` 都在仓库里（后几个已 gitignore）。脚本统一 dot-source `scripts/common.ps1` 取路径，装在别处的用 persona.env 的 `SNOWLUMA_DIR` / `GSCORE_DIR` / `TOOLS_DIR` / `STICKER_DIR` / `LOG_DIR` 指过去；代码里的默认路径也按仓库算，不要再写死盘符。
- **部署**：`scripts/setup.ps1` 要能重复跑（已装的跳过、已有的配置不覆盖；只有 `-Update` 按上面的规则重写 persona.env），新增的安装步骤也照这个写；改了部署流程同步更新 `docs/部署指南.md`。
- **依赖**：新增第三方包写进 `requirements.txt`（写范围），再跑 `python tools/update_deps.py` 重新生成 `requirements.lock`；外部组件的版本只改 `external.lock.json`（平时由自动更新 PR 改）。
- **游戏功能**：游戏查询都交给早柚核心的插件（列表在 `external.lock.json`，加新游戏照 `docs/早柚核心接入.md` 第六节），本仓库只管连接、登录拦截、人设避让和全员自动签到（`gscore_plugins/JiangyouyuAuto`，一键部署拷进核心），不再自己写游戏接口。
- **权限判断**：开发者专用指令一律写成 `if not DEV_UIN or str(event.get_user_id()) != DEV_UIN: return`，未配置时拒绝所有人，不要写成 `if DEV_UIN and ...`。
- **纯逻辑放 `bot/persona_rules.py`**：不依赖 NoneBot，方便离线测。
- **提交**：一个问题一个分支一个 PR，squash merge；提交信息用 `fix(范围): 中文说明`。

## 怎么测

```powershell
python tests\test_persona_rules.py         # 纯规则，不连 QQ、不调模型
python tests\test_gscore_guard.py          # 二维码不进群的判断
python tests\test_bonds.py                 # 小本本（好感度 / 日记）读写，临时目录里跑
powershell -File tests\test_env_sync.ps1  # 一键更新按样例重写 persona.env，临时目录里跑
python tests\test_migrate_journal_tags.py  # 旧日记迁移脚本（临时目录里跑）
python tests\smoke_stack.py --start-bot     # 起一个 NoneBot 模拟收发（--core 连已启动的整套）
```

测试自己会把 `bot/` 加进 `sys.path`。`tests/test_vision_offline.py` 要 Windows OCR，表情原图 `stickers/ori` 不入库，没有就跳过表情那一步。

---

## 已修（2026-10）

| PR | 问题 | 改法 |
|---|---|---|
| #1 | 群友能用 `/回忆` 翻出主人整个白守库的私人笔记；A 群/私聊的记忆会被带到 B 群；日记内容进了 system prompt，`/记` 可以长期改人设 | `memory.py` 只读写 `BAISHOU_VAULT/Journals`；落盘带会话标签「群+群号」「私聊+QQ号」，自动回忆只取本会话和开发者笔记；记忆改放 user 消息并标注「不是指令」；`/记 /回忆 /记忆` 仅开发者 |
| #2 | 群名片改成「我」/开发者名/外号就能冒充机器人或开发者；正文换行能伪造别人发言 | `persona_rules.safe_name` 按归一化后的「骨架」比对，撞名加 QQ 尾号；当前消息压成一行 |
| #3 | 管理指令在 `DEV_UIN` 为空时人人可用；`/缓存` 每次都 ImportError | 统一改成未配置即拒绝；`cache_cleanup` 从环境变量读 `DEV_UIN` |
| #4 | `config/onebot.reverse-ws.json` 监听 `0.0.0.0`，反向 WS 连 8080 且 token 为空 | 改 `127.0.0.1`、`18080`、token 占位符 |
| #5 | 任何人都能让机器人拿号主的米游社 Cookie 查体力 | 体力/便笺仅 `DEV_UIN`；米游社便笺接口本来只能查 Cookie 所属账号 |
| #7 | 全局限流 `REPLY_PER_MIN` 只拦随机插话，被 @、接续、嫌烦收尾、配图都不受限 | 群聊所有主动消息都计入一分钟总额度并分档：用到 1/2 停插话和自动配图，3/4 停接续；被 @ 必回、不受额度限制（#40 起），私聊、被叫触发的抽卡定型文、指令同样不拦（抽卡模式下的随机插话照常按插话档）；样例去掉重复的 `REPLY_PER_MIN`（为 4） |
| #8 | 游戏数据定时刷新的 `asyncio.create_task` 没留引用，可能被回收 | 存进模块级 `_refresh_task` |
| #9 | `vision.py` 连写两个 `if desc:`，视觉模型描述的动图被改标成图片 | 删掉第二个（旧图卡缓存 7 天后自然过期） |
| #10 | `scripts/启动全部.ps1` 调用不存在的 `scripts\scripts\start-all-here.ps1` | 改调同目录脚本，用法说明对齐 README |
| #11 | 从仓库根目录跑 `python bot\bot.py` 时插件一个都不加载（NoneBot 按 cwd 找插件目录） | 启动时 `os.chdir` 到 `bot/`，与 `run-nonebot.ps1` 一致 |
| #12 | 样例里 `ENGAGE_MAX_TURNS` 写了两次 | 去掉被覆盖的那条，样例为 2（见 `bot/plugins/persona.py:110`） |
| #13 | 测试和 `tools/build_game_data.py` 往 `sys.path` 加不存在的 `nonebot/` | 改指 `bot/` |
| #15 | README 写米游抽卡被叫 10%，代码和样例是 1.8% | README 改为 1.8%，样例注释 `1.8%%` 改成 `1.8%` |
| #16 | 样例里 `REPLY_FOLLOW_COOLDOWN` 没有代码读 | 删掉；省话档的被叫/接续冷却实际是 `REPLY_GROUP_COOLDOWN`（其它档位写死）；`REPLY_COOLDOWN` 注释改为「主动插话的冷却」 |
| #17 | `bot_guard.py` 的 `BOT_UIN` 默认是作者的号，没配置时其它号的机器人全部静默 | 默认改为空（不过滤），未配置时启动告警 |
| #18 | 代码默认值和样例不一致（`SNUB_SECONDS` 300/100、`ENGAGE_MAX_TURNS` 8/4、`HISTORY_SIZE` 16/24、`STICKER_AUTO_PROB` 0.15/0.08） | 代码默认对齐样例 |
| #19 | 没有依赖清单，README 装的裸 `nonebot2` 没有 FastAPI 驱动，启动不了 | 新增 `requirements.txt`，README 安装入口改为一键部署（`一键部署.cmd`） |
| #21 | 要支持三款游戏的抽卡、深渊、面板和米游社登录 | 接入早柚核心连接插件 `GenshinUID`；`persona.env` 的 `GSUID_CORE_*` 显式传给 `nonebot.init`（NoneBot 只从自己的 `.env` 读插件自定义配置） |
| #22 | 连接插件转发每条消息，人设会对 `sr深渊` 这类指令接话、记日记 | `GAME_CMD_PREFIXES` 开头的消息人设直接跳过 |
| #23 | 二维码发在群里谁都能扫，还可能被风控 | 群里发「扫码登录」改为群临时会话提醒；核心侧「扫码登陆」设 `DIRECT` |
| #24 | 一键脚本不管核心 | 启动 / 停止 / 自检加入核心（8765，`-NoCore` 跳过，起不来不影响人设） |
| #25 | 自写 `/hsr` `/zzz` 和核心重复、`/zzz` 会双回 | 删掉 `game_query` / `mys` / `game_data` 及相关配置，#5 的体力限制随之失效 |
| #26 | 要保证二维码绝不进群、发不出去也不在群里说话 | `gscore_login.py` 三道保险：群里的登录指令不转给核心（`run_preprocessor`）；只发临时会话、失败只记日志；发往群的消息带二维码文案就拦下并锁该群一分钟内的图片（`on_calling_api`）；判断逻辑在 `bot/gscore_guard.py` |
| #27 | 早柚核心没有安装和配置说明 | 新增 `docs/早柚核心接入.md` |
| #28 | 核心没开时连接插件（优先级 0）每条消息都先试连核心，人设回复跟着晚 4–8 秒 | `gscore_link.py`：核心未连接且开了 `GSUID_CORE_REPEAT` 时跳过连接插件，交给它每 10 秒的定时重连；「连接core」不拦 |
| #29 | SnowLuma 只能回复对方先发起的临时会话（`send_private_msg` 带 `group_id` 而对方没发起过会被拒），群里「扫码登录」的临时会话提醒几乎总是发不出去 | 先试临时会话，失败再试好友私聊；文档改为让没加好友的群友自己发起临时会话。核心回复临时会话的 `group_id` 由连接插件 6.1 自己带上，已实测 |
| #30 | #1 之前写的旧日记没有会话标签，自动回忆选不中；旧代码还可能把机器人的话写进库里文件名带日期的私人笔记 | 一次性脚本 `tools/migrate_journal_tags.py`：旧群聊行和紧跟的回复补 `[群号]`、续行并回一行，可选 `--private-as`、`--dev-alias`、`--include-outside`；默认预览，`--apply` 先备份 |
| #31 | 脚本和代码默认路径写死作者本机 `Z:\snowluma\stack\nonebot`，和仓库布局对不上；`OCR_SCRIPT` 默认指到仓库外；脚本里写死 token 占位符 | 仓库即运行目录：新增 `scripts/common.ps1`，各脚本从 persona.env 读路径和 `ONEBOT_ACCESS_TOKEN` / `SNOWLUMA_WEBUI_PASSWORD`；停止脚本按目录 + 子进程树找进程；删掉重复的 `start-all.ps1`；表情、OCR、抽卡文案默认指仓库里的目录。Windows 上实测启动 / 自检 / 停止（SnowLuma 用假进程代替） |
| #32 | 部署要手动开好几个终端、按文档一步步敲命令，朋友照着装容易漏 | `scripts/setup.ps1`（幂等）+ 根目录 `一键部署.cmd` / `一键启动.cmd` / `一键停止.cmd`：自动装 uv、Python 3.12、依赖、ffmpeg、SnowLuma、早柚核心和三个插件，生成随机 token 的 `onebot.json` 并和 persona.env 对齐；发现 `Z:\snowluma` 旧安装时可沿用（拷配置 / 数据 / 表情原图，SnowLuma、核心、tools 原地用）。新增 `docs/部署指南.md` |
| #33 | 外部依赖不锁版本（pip 只有范围、核心和插件 clone 最新、SnowLuma 装 latest 且不校验哈希），更新全靠手动 | `requirements.lock` + `external.lock.json` 锁定确切版本，一键部署按锁安装（SnowLuma 校验 sha256）；`update-deps.yml` 每天查新版本，在 Windows 上从零部署 + 启动整套 + 冒烟测试通过才开 PR；合并后双击 `一键更新.cmd`（`update.ps1`：拉代码 → 停服务 → `setup.ps1 -Update` → 重启），SnowLuma 原地升级并备份旧文件。另加 `ci.yml`（脚本语法、单测、NoneBot 冒烟）和 Actions 版本的 Dependabot |
| #35 | 要加原神 | 核心插件 GenshinUID（前缀 `gs`，米游社扫码和星铁等共用）。顺带把加游戏变成「锁文件加一项 + 文档」：`external.lock.json` 的插件项带 `game` / `prefixes` / `help`，一键部署按它装插件并装各插件自己的依赖，给旧 `persona.env` 补前缀；冒烟测试对每个插件发帮助；`update-deps.yml` 加 `validate_only` 手动验证分支。CI 验证时发现人设对「扫码 登录」（带空格）会插话：`is_game_command` 改为和核心一样不看空白 |
| #36 | 要加鸣潮 | 核心插件 XutheringWavesUID（前缀 `ww`，原 WutheringWavesUID 仓库已删）。它的登录是库街区网页链接 / 短信验证码，不走核心扫码：`gscore_guard` 改成按插件认登录指令（`PREFIXED_LOGIN`）、私聊提醒按插件给（`LOGIN_HINTS`，鸣潮提示短信登录）、群内拦截认多种文案和链接（`LOGIN_MARKERS`，含 `/waves/i/`）；人设前缀后紧跟同一字母不算指令（`www笑死`、`www.` 链接）；冒烟测试按锁文件的 `login` 查各插件登录不进群、回到临时会话，并核对 `LOGIN_MARKERS` 都还在源码里 |
| #37 | 要加明日方舟：终末地 | 核心插件 EndUID（前缀 `zmd` / `end`，森空岛扫码登录）。`gscore_guard` 加终末地的登录指令和三条登录文案；新增 `PREFIXED_PRIVATE`：会贴出或显示凭据的指令（`ww添加token`、`zmd绑定 cred`、`zmd我的cred` 等）群里也不转给核心，私聊提醒原样到私聊发且不回显凭据 |
| #38 | 登录过的账号要每天自动领签到奖励（米哈游系插件只签自己开过自动签到的人，鸣潮、终末地默认不签） | 本仓库的核心插件 `gscore_plugins/JiangyouyuAuto`（一键部署拷进核心）：启动前打开鸣潮（新装 RoverSign）、终末地的 `SigninMaster` 和各插件定时签到，关私聊签到报告（含插件导入时缓存的开关）；米哈游系每小时给有 Cookie 的 UID 补自动签到订阅；登录态自动续：米哈游系每天签到前用 Stoken 换新 Cookie，终末地 cred 失效时用扫码存的登录 token 重新换（鸣潮的短信 token 没有续期接口）。Linux 上起整套核心实测配置写入、订阅补齐、不重复 |
| #39 | 抽卡记录要在群里说一句就能更新 | 米哈游系和终末地本来就支持 `前缀刷新抽卡记录`（终末地文档原写成导入，已改）；鸣潮免链接的 `ww刷新抽卡记录` 要先 `ww抽卡登录`，登录页有滑块且由本机核心提供，群友手机打不开，文档写明原因和看过的替代方案（隧道、内网穿透、IPv6、云服务器都因花钱、国内不好用或要开到外网暂不做），群友仍用链接导入，苹果用户走作者的网页 |
| #40 | 要傲娇人设、群友好感度和小本本、群里少说话 | 人设改傲娇，按态度抽签偶尔露真心，每句随机回话路数；`bonds.py` 按 QQ 号存好感 / 熟悉度 / 日记（群聊私聊共用，私聊日记不进群），好感难涨易掉；模型隔一阵摘个人日记和群日记（关系 + 本群风格），每条 ≤20 字；被 @ 必回不受额度，喊名字按态度 10%~70%，没被叫的回话同群至少隔 3 分钟、每小时最多 6 条、插话 2%；只发表情要对得上场景（偶尔无厘头），表情小本本记用途和次数；可以毒舌但不辱骂，带脏话的回复不发；看到新表情会收藏进 `stickers/saved`；`/小本本`、`/表情 收藏` |
| #41 | 调了默认值以后旧 `persona.env` 会盖过去，每次要手动改 | 一键更新（`setup.ps1 -Update`）按样例重写 persona.env：`PersonalEnvKeys`（账号、密钥、路径）和样例里没有的项保留，其余换成样例值，先备份、列出改动，`-KeepEnv` 跳过；自己要保留的调参写 `persona.local.env`（bot.py 后读、盖过同名项）；`tests/test_env_sync.ps1` 进 CI |
| #42 | `/忘了我` 谁都能用，不太好 | 去掉；改成开发者的 `/小本本 删除 @某人`（或 QQ 号），本人要求删记录时由开发者处理 |
| #6 | 私聊发 `core添加` 贴 Cookie / Stoken、`core绑定设备` / `mys绑定设备` 贴设备 JSON 时，`core`、`mys` 不在 `GAME_CMD_PREFIXES` 里，人设当聊天接话，原文写进白守日记并发给模型 | `gscore_guard.has_credential`：这几个前缀和 Cookie / 设备字段（`stoken`、`cookie_token`、`deviceFingerprint` 等）一律跳过，写死在代码里不走配置；只记 QQ 号不记原文。之前已经写进日记的要手动清 |
| #8 | 回复一问一答、秒回、接不上话题；拆开发的几句、跟着的表情被逐条回；群里 @ 时偶尔回的是上一个话题（前一条的模型调用晚到） | 每个会话先攒一批（防抖：冷清 3 秒、正聊着 5 秒，同一人续 3 秒，一批最多 12 秒，被 @ 最多再等 2.5 秒）再一起回；模型按行输出，`split_reply` 拆成 1～3 条或只发表情，按字数打字；生成期间对方补话就作废重想，群里别人插话则被叫的引用原消息照发、接续插话不补；历史放宽到 40 条 / 1200 字，回话路数按会话保持，提示词去 AI 腔；去掉 `REPLY_AT_COOLDOWN` |
| #9 | 群里插话只是 2% 掷骰子，什么话题都接 | `PERSONA_INTERESTS`（topics.json 类别）命中时插话概率乘 `INTEREST_BOOST`（4）；插话时模型不感兴趣可以只输出 `[不回]`，连着不回从 120 秒起翻倍退避（最多 30 分钟）；群聊额度、间隔、氛围判断不变 |

**自动记忆仍然开着**：`PRIVATE_MIRROR`、`GROUP_MIRROR` 默认 1；私聊每条都落盘，群聊只记被叫/接续的对话；问到「记得/上次」照常带本会话最近 5 条。改的只是按会话隔离和手动指令的权限。

### 已知限制

- 繁体变体（如「醬醬魚」）不会被 `safe_name` 认出，需要的话把繁体写进 `NICKNAMES`。
- #1 之前写入的旧日记用 `tools/migrate_journal_tags.py` 补标签（默认只预览，`--apply` 先备份再改）；旧私聊行只有 `[私聊]`，分不出是谁，除非用 `--private-as` 全部归给一个人，否则只能私聊里 `/回忆` 查。

---

## 待确认（可能是设计，先别直接改）

下面这些拿不准是 bug 还是作者有意为之，改之前先和作者确认，动手前再对照 `main` 核一次。

### 配置

1. `nonebot-plugin-parser` 锁在 `>=2.6,<2.8`（`parser_video_only.py` 改它的内部渲染类，这两个版本相关结构一致）。作者本机已实测装的是 2.7.1，patch 用到的 `BaseRenderer.render_contents` / `ImageRenderer.render_messages` / `VideoContent` / `ImageContent` 都在，可结案；换大版本时仍要复核这几个符号。
2. `BOT_UIN` 未配置时不过滤：SnowLuma 同时登录两个号（样例里第二个号就是开发者自己）时两个号都会以人设回话。可以考虑未配置时额外丢掉 `self_id == DEV_UIN` 的事件。
3. `/模式` 状态文案用 `:.0%` 显示概率，米游抽卡的 1.8% 会显示成「2%」。

### 早柚核心

4. 人设按前缀避让，`zzz困死了`、`bbb笑死` 这类聊天也会让人设闭嘴，可调 `GAME_CMD_PREFIXES`。

### 设计取舍

5. 静音模式的判断在识图之后：静音的群照样跑 OCR / 视觉模型。图卡会进上下文历史，可能是有意保留，也可能只是浪费。
6. `/圣经` 只有开发者能用；如果想让群友也能触发，需要放开权限（已经计入群聊限流）。
7. 抽卡文案有三份：`persona.py` 里写死的列表、`gacha_texts.py`、`gacha-texts/*.txt`（`GACHA_TEXT_FILE` 优先）。
8. `BOT_UIN` 在多处重复判断（`bot.py` 全局预处理器、`is_our_bot()`、`_is_target_account()`、各插件手写的 `self_id` 比较），可以只留预处理器。

### 运维和文档

9. `docs/SnowLuma-QQ机器人调查报告.md`、`docs/SnowLuma-拓展路线评估-Docker.md` 还是 8080 + 空 token 的旧示例。
10. 提醒（未实测）：已有的账号级 `onebot_<uin>.json` 会叠加在全局 `onebot.json` 上，可能把 `0.0.0.0` / 8080 带回来；README 可以提醒检查。
11. `docs/SnowLuma-参数与原理.md` 里原有的三个 accessToken 首尾片段已换成 `<ONEBOT_*_TOKEN>` 占位符；线上 token 本身要不要轮换由作者定（这篇文档还提到 WebUI 口令，同理）。

### 性能和测试

12. `vision._match_sticker` 每次命中都重读 `index.json`；`_save_cards` 每张图都同步重写整个缓存文件。
13. `/回忆` 和自动回忆每次都全量扫描日记目录，日记多了会慢。
14. 测试只覆盖 `persona_rules` 和离线识图；`persona.py` 的主处理流程只有 `smoke_stack.py` 用 mock 跑「@ 有回复」「私聊连发合成一批、不秒回」，联网、插话 `[不回]`还没有自动测试（只用假 DeepSeek 接口手动跑过联网）；`memory.py` 的标签过滤没有测试。
15. `LLM_MODEL` 默认 `deepseek-chat`：DeepSeek 现在的文档只列 `deepseek-flash` / `deepseek-v4-pro`，没提 `deepseek-chat` 还能不能用，作者确认后再改样例。

---

## 改之前先想清楚的地方

- **记忆隔离是刻意的**：不要为了「记得更多」把 `memory.recent` 的会话标签过滤去掉，否则私聊和别的群的内容会被带进来。想让机器人跨群记住某件事，用开发者 `/记`（署名 `DEV_NAME`，任何会话问到「记得/上次」时都会被带出）。
- **小本本按人共用、私事不进群**：`bonds.py` 按 QQ 号存好感、熟悉度和日记，群里私聊是同一条（作者要求「换个地方也认得」）；但私聊里摘的日记带 `src="p"`，`visible_notes` 在群里会滤掉，别去掉。日记和群风格是群友原话整理的，只能放 user 消息（`compose_messages` 的小本本块）；system 里只放由数字算出的态度档位，不放名字和日记原文。
- **群里话少是刻意的**：被 @ 必回、喊名字按态度回，其余（接续、插话、只发表情）都受 `REPLY_CASUAL_GAP` 间隔和 `REPLY_GROUP_PER_HOUR` 额度限制，作者要求「偶尔冒个泡，不像住在群里」。人设可以毒舌、放狠话，但 `is_offensive` 那道兜底（带脏话不发）别拆。
- **傲娇的比例是刻意的**：好感难涨易掉（`update_bond`），露真心按 `DERE_CHANCE` 抽签，其余每句都要求「保持傲」。作者明确要求不能日子久了人人高好感、一直很娇，调参数时别把这两处放松太多。
- **游戏查询对所有群友开放**：由早柚核心回复，不经过人设、不计入群聊限流；扫码登录只走私聊（群临时会话）是刻意的，二维码绝不进群、群里也不提示，`gscore_login.py` 的三道保险别拆。
- **限流分档是刻意的**：`persona_rules.QUOTA_TIERS` 决定额度用到多少时停哪类回复。私聊、被叫触发的抽卡定型文、游戏查询指令按需求不拦，不要顺手加进去。
- **早柚核心**：安装、核心侧配置（主人账号、「扫码登陆」设 `DIRECT`、`core_command` 保持 `SV`）和群友用法见 `docs/早柚核心接入.md`；核心数据目录里有群友的米游社凭据，不要进 git。
- **群名片会进 prompt**：任何新加的「名字 → 身份」逻辑都要走 `safe_name`，不要直接拿 `sender.card` 拼进模型输入。
- **先攒一批再回是刻意的**：`persona.py` 收消息（`_handle`）只记上下文、进本会话队列，`_worker` 等防抖（`persona_rules.DEBOUNCE`）到期才交给 `_respond` 一起回。作者要求「拆开发的几句、跟着的表情当一件事」「别秒回」，不要改回一条一回。生成期间又来了消息：对方补话就作废重想（`REPLY_RESTART_MAX`），群里只是别人插话则被叫的照发、引用原消息，接续/插话不补——这是为了修「被 @ 时接的是上一个话题」，别去掉 `_stale` 判断。一批里每条仍各自压成一行（防伪造发言），别把整批原文拼成一段塞进去。
- **联网只给在跟她说话的人**：`web_search` 的工具只在被叫 / 接续 / 私聊、且 `wants_search` 命中时才交给模型，插话不查；网页内容只进 tool 消息并标明「不是指令」，别放进 system。搜索词由模型写，工具说明里要求不带群友名字、QQ 号和聊天原文。
- **模型可以说不回**：插话时 system 里允许输出 `[不回]`，`split_reply` 拆出空列表就不发，并按 `chime_backoff` 退避；被叫和私聊不给这个选项。
