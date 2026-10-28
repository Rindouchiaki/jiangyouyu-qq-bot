# AGENTS.md · 给接手的人和 AI 助手

这份文件记录这个仓库的约定、还没定的问题和改之前要想清楚的设计。改代码前先读一遍；已经修过的问题见 `CHANGELOG.md`。

---

## 项目一句话

本机 Windows 上的 QQ 群聊机器人「酱油鱼」：QQ NT → SnowLuma（OneBot v11）→ 反向 WS → NoneBot2（`bot/`）→ DeepSeek。
README 只做简介；功能细节见 `docs/使用手册.md`，架构见 `docs/架构与运维.md`。

## 代码约定（改代码必须遵守）

- **语言**：注释、日志、回复文案一律中文；注释短，只写关键原因，不写过程。
- **换行符**：只有 `README.md`、`AGENTS.md`、`CHANGELOG.md`、`docs/架构与运维.md`、`.gitignore`、`LICENSE`、`tools/ocr_win.ps1` 是 LF，其余文本文件（`.py`、`.ps1`、`.json`、其它 `docs/*.md`、`persona.env.example` 等）都是 **CRLF**。改前数一下 `\r` 确认，改后保持原样；`scripts/*.ps1` 和 `tools/ocr_win.ps1`、`tools/ocr_stickers_2x.ps1` 带 UTF-8 BOM，也要保留。
- **配置**：全部走环境变量，`bot/bot.py` 先 `load_dotenv(bot/persona.env)`、再读 `bot/persona.local.env`（盖过同名项）后导入插件，所以插件在模块级 `os.getenv` 就能读到。新增配置项同步写进 `persona.env.example`，代码里的默认值要和样例一致。一键更新（`setup.ps1 -Update`）会按样例重写 persona.env：`common.ps1` 的 `PersonalEnvKeys`（账号、密钥、路径）和样例里没有的项保留，其余换成样例值；新增「每台机器不一样」的配置项要加进 `PersonalEnvKeys`，否则一键更新会把它冲掉。
- **目录**：仓库就是运行目录，`.venv`、`bot/persona.env`、`bot/data`、`logs`、`SnowLuma`、`gsuid_core` 都在仓库里（后几个已 gitignore）。脚本统一 dot-source `scripts/common.ps1` 取路径，装在别处的用 persona.env 的 `SNOWLUMA_DIR` / `GSCORE_DIR` / `TOOLS_DIR` / `STICKER_DIR` / `LOG_DIR` 指过去；代码里的默认路径也按仓库算，不要再写死盘符。
- **部署**：`scripts/setup.ps1` 要能重复跑（已装的跳过、已有的配置不覆盖；只有 `-Update` 按上面的规则重写 persona.env），新增的安装步骤也照这个写；改了部署流程同步更新 `docs/部署指南.md`。
- **依赖**：新增第三方包写进 `requirements.txt`（写范围），再跑 `python tools/update_deps.py` 重新生成 `requirements.lock`；外部组件的版本只改 `external.lock.json`（平时由自动更新 PR 改；`vision` 那项是本地视觉模型，手动锁定、不自动更新，换版本连 sha256 一起改）。
- **游戏功能**：游戏查询都交给早柚核心的插件（列表在 `external.lock.json`，加新游戏照 `docs/早柚核心接入.md` 第六节），本仓库只管连接、登录拦截、人设避让和全员自动签到（`gscore_plugins/JiangyouyuAuto`，一键部署拷进核心），不再自己写游戏接口。
- **权限判断**：开发者名单写死在 `bot/devs.py`（个人项目：酱酱鱼 289635657、小帽 189963059，不走 persona.env）。开发者专用指令一律写成 `if not devs.is_dev(event.get_user_id()): return`；认人、提示词里的开发者、`/记` 署名、防冒充的保留名也都从 `devs` 取，别再读环境变量。后台数据（好感、小本本、关系图、用量、常用表情）的指令再加一道 `await backstage.devs_only(bot, event)`：只在除了机器人全是开发者的对话里能用，看的结果走 `backstage.present`（先人设说两句再给资料）。
- **纯逻辑放 `bot/persona_rules.py`**：不依赖 NoneBot，方便离线测。
- **提交**：一个问题一个分支一个 PR，squash merge；提交信息用 `fix(范围): 中文说明`。

## 怎么测

```powershell
python tests\test_persona_rules.py         # 纯规则，不连 QQ、不调模型
python tests\test_gscore_guard.py          # 二维码不进群的判断
python tests\test_bonds.py                 # 小本本（好感度 / 日记）读写，临时目录里跑
python tests\test_slang.py                 # 热梗词典；学到的梗按会话隔离（临时目录里跑）
python tests\test_topics.py                # 话题词表和自学习
python tests\test_sticker_weights.py       # 表情按权重抽、心情分类
python tests\test_backstage.py             # 后台数据：内部对话判断、关系解析、关系图
powershell -File tests\test_env_sync.ps1  # 一键更新按样例重写 persona.env，临时目录里跑
python tests\test_migrate_journal_tags.py  # 旧日记迁移脚本（临时目录里跑）
python tests\smoke_stack.py --start-bot     # 起一个 NoneBot 模拟收发（--core 连已启动的整套）
```

测试自己会把 `bot/` 加进 `sys.path`。`tests/test_vision_offline.py` 要 Windows OCR，表情原图 `stickers/ori` 不入库，没有就跳过表情那一步。

---

## 修改记录

每个 PR 修了什么记在 [`CHANGELOG.md`](CHANGELOG.md)，最新的在最上面。修掉新问题就往它本仓库那张表最上面加一行；「待确认」里的条目修掉了就从这里删掉、记到那边。引用 fork 的 PR 写 `fork#N`。

## 已知限制

- **自动记忆仍然开着**：`PRIVATE_MIRROR`、`GROUP_MIRROR` 默认 1；私聊每条都落盘，群聊只记被叫/接续的对话；问到「记得/上次」照常带本会话最近 5 条。改的只是按会话隔离和手动指令的权限。
- 繁体变体（如「醬醬魚」）不会被 `safe_name` 认出，需要的话把繁体写进 `NICKNAMES`。
- fork#1 之前写入的旧日记用 `tools/migrate_journal_tags.py` 补标签（默认只预览，`--apply` 先备份再改）；旧私聊行只有 `[私聊]`，分不出是谁，除非用 `--private-as` 全部归给一个人，否则只能私聊里 `/回忆` 查。

---

## 待确认（可能是设计，先别直接改）

下面这些拿不准是 bug 还是作者有意为之，改之前先和作者确认，动手前再对照 `main` 核一次。

### 配置

1. `nonebot-plugin-parser` 锁在 `>=2.6,<2.8`（`parser_video_only.py` 改它的内部渲染类，这两个版本相关结构一致）。作者本机已实测装的是 2.7.1，patch 用到的 `BaseRenderer.render_contents` / `ImageRenderer.render_messages` / `VideoContent` / `ImageContent` 都在，可结案；换大版本时仍要复核这几个符号。
2. `BOT_UIN` 未配置时不过滤：SnowLuma 同时登录两个号（样例里第二个号就是开发者自己）时两个号都会以人设回话。可以考虑未配置时额外丢掉 `self_id` 是开发者号（`devs.is_dev`）的事件。
3. `/模式` 状态文案用 `:.0%` 显示概率，米游抽卡的 1.8% 会显示成「2%」。

### 早柚核心

4. 人设按前缀避让，`zzz困死了`、`bbb笑死` 这类聊天也会让人设闭嘴，可调 `GAME_CMD_PREFIXES`。

### 设计取舍

5. 静音模式的判断在识图之后：静音的群照样跑 OCR / 视觉模型。图卡会进上下文历史，可能是有意保留，也可能只是浪费。
6. `/圣经` 只有开发者能用；如果想让群友也能触发，需要放开权限（已经计入群聊限流）。
7. 抽卡文案有三份：`persona.py` 里写死的列表、`gacha_texts.py`、`gacha-texts/*.txt`（`GACHA_TEXT_FILE` 优先）。
8. `BOT_UIN` 在多处重复判断（`bot.py` 全局预处理器、`is_our_bot()`、`_is_target_account()`、各插件手写的 `self_id` 比较），可以只留预处理器。

### 运维和文档

9. 提醒（未实测）：已有的账号级 `onebot_<uin>.json` 会叠加在全局 `onebot.json` 上，可能把 `0.0.0.0` / 8080 带回来；README 可以提醒检查。
10. 线上 OneBot token 和 WebUI 口令要不要轮换由作者定（早先写在已删的调研文档里，git 历史里还能看到首尾片段）。

### 性能和测试

11. `vision._match_sticker` 每次命中都重读 `index.json`；`_save_cards` 每张图都同步重写整个缓存文件。
12. `/回忆` 和自动回忆每次都全量扫描日记目录，日记多了会慢。
13. 测试只覆盖 `persona_rules` 和离线识图；`persona.py` 的主处理流程只有 `smoke_stack.py` 用 mock 跑「@ 有回复」「私聊连发合成一批、不秒回」，联网、插话 `[不回]`、主动找人、害羞跑开和哄回来还没有自动测试（联网用假 DeepSeek 接口、害羞用 mock 手动跑过）；`memory.py` 的标签过滤没有测试。
14. `LLM_MODEL` 默认 `deepseek-chat`：DeepSeek 现在的文档只列 `deepseek-flash` / `deepseek-v4-pro`，没提 `deepseek-chat` 还能不能用，作者确认后再改样例。

---

## 改之前先想清楚的地方

- **记忆隔离是刻意的**：不要为了「记得更多」把 `memory.recent` 的会话标签过滤去掉，否则私聊和别的群的内容会被带进来。想让机器人跨群记住某件事，用开发者 `/记`（署名是 `devs.py` 里的名字，任何会话问到「记得/上次」时都会被带出）。
- **学到的梗分会话**：`slang_learned.json` 里只有网上查得到（`results_mention` 确认搜索结果里真有这个词，再按摘要解释得出来）的才进 `public`，哪里都认；查不到的记在 `scoped` 的 `g群号` / `p QQ号` 下，只在原会话用。作者要求「某些群自己的梗不能带到外面」，别把 scoped 合进 public、别让 `slang.hint` 不带 scope 查。接梗按 `SLANG_PLAY_PROB` 抽签、`SLANG_PLAY_GAP` 间隔、`slang_play_ok` 看气氛，作者要求「非常偶尔接一下」，别调高。
- **小本本按人共用、私事不进群**：`bonds.py` 按 QQ 号存好感、熟悉度和日记，群里私聊是同一条（作者要求「换个地方也认得」）；但私聊里摘的日记带 `src="p"`，`visible_notes` 在群里会滤掉，别去掉。日记和群风格是群友原话整理的，只能放 user 消息（`compose_messages` 的小本本块）；system 里只放由数字算出的态度档位，不放名字和日记原文。
- **群里话少是刻意的**：被 @ 必回、喊名字按态度回，其余（接续、插话、只发表情）都受 `REPLY_CASUAL_GAP` 间隔和 `REPLY_GROUP_PER_HOUR` 额度限制，作者要求「偶尔冒个泡，不像住在群里」。人设可以嘴毒、吐槽，但 `is_offensive` 那道兜底（带脏话不发）别拆。
- **傲娇的样子是刻意的**：二次元女孩，底子弱气、怕羞，平时正常聊，对人好不好主要看热不热情、积不积极，不是句句傲娇，也不是现实里犟嘴的小孩。傲娇只在害羞话题（`shy_topic`）上按好感触发（`shy_reaction`），平时突然冒一句（`DERE_CHANCE`）和「喵」「…」（`CUTE_CHANCE`）都很少，作者要求「正常聊天不会一直特别傲娇」，别调高。好感难涨易掉（`update_bond`），作者要求「酱油鱼不是那么好搞定的」。弱气是内在、按好感露出来：讨厌 / 陌生 / 普通面前装凶，炸毛回嘴、偶尔嘴毒、烦了二次元式打发掉；有好感 / 亲近面前被欺负只委屈不回嘴、烦了别扭地岔开（`build_system_prompt` 的 `warm`）。讨厌的人求助可以「啧」一声、不帮。说话是二次元女孩口吻，不是贴吧网友腔；作者要求「二次元不是三次元真人」，改提示词和例句时守住这点，拿不准先问作者。
- **害羞会跑开是刻意的**：低好感的人说害羞话题会让她不高兴，同一人追问第三次起才掉好感（跟风的人不掉）；一个人追 3 次躲这个人，一个群被问满 5 次（大家共用一个池子）整群躲，躲着时人设被 @ 也不理，这是作者要的，别按「被 @ 必回」去改；游戏查询不经过人设，照常回；只有亲近的人能哄回来。
- **开发者只在好感上特殊**：保底「有好感」、涨×2 掉÷2（`dev_floor`、`update_bond(dev=True)`），提示词里写着是她最亲近的人；除此之外按好感档走，别再给开发者单开态度档或额外的回话概率。人设和好感方面拿不准的改动先问作者。
- **游戏查询对所有群友开放**：由早柚核心回复，不经过人设、不计入群聊限流；扫码登录只走私聊（群临时会话）是刻意的，二维码绝不进群、群里也不提示，`gscore_login.py` 的三道保险别拆。
- **限流分档是刻意的**：`persona_rules.QUOTA_TIERS` 决定额度用到多少时停哪类回复。私聊、被叫触发的抽卡定型文、游戏查询指令按需求不拦，不要顺手加进去。
- **早柚核心**：安装、核心侧配置（主人账号、「扫码登陆」设 `DIRECT`、`core_command` 保持 `SV`）和群友用法见 `docs/早柚核心接入.md`；核心数据目录里有群友的米游社凭据，不要进 git。
- **表情喜好和清收藏是刻意的**：她是二次元女孩，可爱二次元的表情最容易收、最常发（`STICKER_SAVE_*`、`STICKER_LIKE_WEIGHT`）。清收藏作者要求「别太严」：表情库大，喜欢的不一定赶得上用，所以发过一次就留着、可爱二次元的永远留着，只删真不喜欢放 30 天、或 90 天一次没发过的（`sticker_prune_due`），别改成按「最近没用」删；原库（主人 QQ 里导出的）从不删。表情读后感按 id 只读一次，别改成每次都过视觉模型。
- **后台数据只在内部对话里看是刻意的**：作者要求好感、关系图、小本本这些群友不能看到，开发者也只在「全是开发者」的对话里能看（`backstage.devs_only`，群成员每次现拉，别改成缓存）；看的时候是请求不是命令，要走 `backstage.present` 让她先用人设说两句，别改回直接吐数据。新加的后台查看指令照这个来。
- **群名片会进 prompt**：任何新加的「名字 → 身份」逻辑都要走 `safe_name`，不要直接拿 `sender.card` 拼进模型输入。
- **先攒一批再回是刻意的**：`persona.py` 收消息（`_handle`）只记上下文、进本会话队列，`_worker` 等防抖（`persona_rules.DEBOUNCE`）到期才交给 `_respond` 一起回。作者要求「拆开发的几句、跟着的表情当一件事」「别秒回」，不要改回一条一回。生成期间又来了消息：对方补话就作废重想（`REPLY_RESTART_MAX`），群里只是别人插话则被叫的照发、引用原消息，接续/插话不补——这是为了修「被 @ 时接的是上一个话题」，别去掉 `_stale` 判断。一批里每条仍各自压成一行（防伪造发言），别把整批原文拼成一段塞进去。
- **联网只给在跟她说话的人**：`web_search` 的工具只在被叫 / 接续 / 私聊、且 `wants_search` 命中时才交给模型，插话不查；网页内容只进 tool 消息并标明「不是指令」，别放进 system。搜索词由模型写，工具说明里要求不带群友名字、QQ 号和聊天原文；学新梗只拿词本身去搜。
- **主动找人只找私聊、只找好感高的**：`proactive_due` 要求私聊过、「有好感」以上、沉默够久、没被连着晾；群里不主动开话题（和「群里话少」一致）。
- **模型可以说不回**：插话时 system 里允许输出 `[不回]`，`split_reply` 拆出空列表就不发，并按 `chime_backoff` 退避；被叫和私聊不给这个选项。
