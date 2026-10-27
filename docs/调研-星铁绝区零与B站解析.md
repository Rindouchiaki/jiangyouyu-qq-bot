# 调研：星穹铁道 / 绝区零 / B站卡片解析

> 调研时间：2026-10-26　|　仅调研，未安装、未改动任何配置
> 目标环境：NoneBot2 2.5.0 + SnowLuma（OneBot v11），账号 100000001

---

## 一、结论速览

| 需求 | 最合适的项目 | 形态 | 能不能直接塞进现在的 NoneBot2 |
| --- | --- | --- | --- |
| B站分享卡片自动解析下载 | **fllesser/nonebot-plugin-parser** | NoneBot2 插件 | ✅ 直接 `nb plugin install` |
| 星穹铁道查询/面板 | **March7th**（独立 bot）或 **StarRailUID**（早柚生态） | 独立程序 / 早柚扩展 | ❌ 要另起一套 |
| 绝区零查询/面板 | **ZZZeroUID** | 早柚核心（gsuid_core）扩展 | ❌ 要另起一套 |

一句话：**B站解析可以并进来，米家游戏查询得另开一个进程**。

---

## 二、B站 / 分享卡片解析

### 1. fllesser/nonebot-plugin-parser ★231（2026-10-24 更新）—— 首选

<https://github.com/fllesser/nonebot-plugin-parser>

- **形态**：标准 NoneBot2 插件，`nb plugin install nonebot-plugin-parser`
- **触发形态**：B站 av 号 / BV 号 / 完整链接 / 短链 / **卡片** / 小程序 —— 也就是 QQ 里分享出来的那种卡片，能直接吃到
- **产出**：视频、图集、音频；默认用 PIL 渲染通用媒体卡片
- **还支持**：微博（博文/视频/show/文章）、小红书（链接/短链/卡片）
- **依赖**：可选 B站 Cookie（部分内容需要）、ffmpeg（部分格式）、ytdlp（YouTube/TikTok 才用）
- **风险**：视频体积大时 QQ 上传慢或被限；B站画质受 Cookie 权限影响

### 2. mengshouer/nonebot_plugin_analysis_bilibili ★90（2026-10-21）

<https://github.com/mengshouer/nonebot_plugin_analysis_bilibili>

- B站专用，功能更聚焦；如果想要“小而专”可以选它
- 同样是 NoneBot2 插件

### 3. zhiyu1998/nonebot-plugin-resolver ★74（2026-06-20）

<https://github.com/zhiyu1998/nonebot-plugin-resolver>

- 多平台：B站 / TikTok / Twitter / 图片链接 / 小程序
- 更新节奏比前两个慢，作为备选

---

## 三、星穹铁道

### 1. March7th ★133（2026-10-05）

<https://github.com/Mar-7th/March7th>

- **形态**：**独立的 NoneBot2 机器人**，不是插件。自带数据库、ORM、多适配器（OneBot v11/v12、QQ、KOOK、Telegram 等）
- 功能覆盖最全：查询、抽卡、面板、活动日历、模拟器等一整套
- **接入方式**：它有 OneBot v11 适配器，可以作为**另一个 bot** 连到 SnowLuma 的 `wsClients`（SnowLuma 支持一个账号挂多个反向 WS 客户端）
- **成本**：要单独装 Python 依赖、单独跑进程、单独一份数据库；且和现有 persona 会有“抢话”冲突，需要错开触发词

### 2. StarRailUID ★53（2026-09-29）

<https://github.com/baiqwerdvd/StarRailUID>

- **形态**：早柚核心（gsuid_core）的扩展，不是独立插件
- 功能：面板查询、抽卡记录、角色练度等
- 需要先跑 gsuid_core 这一整套

### 3. 早柚核心生态（如果走 StarRailUID/ZZZeroUID 这条线）

- gsuid_core ★362（2026-10-25）：<https://github.com/Genshin-bots/gsuid_core>
- GenshinUID ★875（2026-10-23）：<https://github.com/KimigaiiWuyi/GenshinUID>
- 特点：一套核心 + 各游戏插件（原神/星铁/绝区零），本身也是 NoneBot2 应用，可接 OneBot
- 代价：等于再养一套机器人框架，配置、数据库、更新都要跟着

---

## 四、绝区零

### ZZZeroUID ★122（2026-10-21）

<https://github.com/ZZZure/ZZZeroUID>

- **形态**：早柚核心扩展（对 bot 发 `core安装插件zzzerouid`）
- 功能：`zzz查询`、`zzz刷新抽卡记录`、`zzz抽卡记录`、`zzz刷新面板`、`zzz查询露西`（角色面板）等
- 官方标注仍在施工、迭代很快
- **依赖**：同样需要 gsuid_core；米游社数据需要绑定 UID / Cookie

---

## 五、接入成本对比

| 项目 | 额外进程 | 额外框架 | 需要 Cookie | 与现有 persona 冲突 | 总体成本 |
| --- | --- | --- | --- | --- | --- |
| nonebot-plugin-parser | 无（并入现有） | 无 | 可选 | 低（可 block） | **低** |
| analysis_bilibili | 无 | 无 | 可选 | 低 | 低 |
| March7th | 1 个 | 自带 | 需要（米游社） | 中（两套 bot 抢同一账号事件） | 中高 |
| gsuid_core + StarRailUID/ZZZeroUID | 1 个 | 早柚核心 | 需要（米游社） | 中 | 高 |

---

## 六、需要注意的坑

1. **抢话**：SnowLuma 会把同一个群的消息推给**所有** wsClients。接入第二个 bot 后，persona 和新 bot 都会收到同一条消息；必须靠触发词/前缀错开，否则会出现两个 bot 同时回。
2. **端口**：每个 bot 一条反向 WS，各自占用一个宿主端口（我们现在 18080 是 persona，新 bot 得用 18090 之类）。
3. **米游社风控**：查询类功能要绑定 Cookie 或 UID，抽卡记录依赖 UIGF 格式导入；Cookie 失效会导致整片功能报错。
4. **隐私**：米游社 Cookie 等同于账号凭据，必须只存本机、不进 git。
5. **视频体积**：B站 1080P 视频动辄几十 MB，QQ 上传有实际限制，建议默认只发 720P 或仅发卡片预览。

---

## 七、建议路线（等你拍板）

- **第一优先**：先并入 `nonebot-plugin-parser`。它是纯插件、零额外进程、正好解决“卡片链接自动解析下载”，风险和成本都最低。
- **第二优先**：如果星铁/绝区零查询是刚需，再单开一个 **gsuid_core**（一套核心同时吃 StarRailUID + ZZZeroUID），比装 March7th 更省。前提是能接受再养一个进程和一套配置。
- **暂不建议**：同时上 March7th 和 gsuid_core —— 两套框架并存，维护成本翻倍。

> 以上都没装。你确认要哪个，我再动手，并且会先把触发词和端口规划好，避免和 persona 抢话。
