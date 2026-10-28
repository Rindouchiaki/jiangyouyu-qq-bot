# 表情包库

从本机 QQ（账号 100000002）的收藏表情导出，供机器人在群里调用。

## 结构

```
stickers/
├─ ori/            513 张原图（jpg/png/gif，按内容哈希命名，已去重）
├─ index.json      索引：id / 文件 / 尺寸 / 标签 / OCR 文本 / 分类
├─ ocr.jsonl       第一轮 OCR（原尺寸）
└─ ocr2.jsonl      第二轮 OCR（2 倍放大）
```

## 数据来源

- 源目录（只读）：`%APPDATA%\Tencent\TF\Tencent Files\100000002\nt_qq\nt_data\Emoji\personal_emoji\Ori`
- 同目录还有：`Thumb`（缩略图，未导出）、`marketface`（商店表情 357 个）、`emoji-recv`（接收缓存 1.3 GB，未导出）

## 标签

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| 无文字 | 372 | OCR 没认出字，按视觉标签用 |
| 其他 | 113 | 有字但没命中关键词 |
| 疑问 | 12 | 为什么/啥/吗/? |
| 生气 | 5 | 气死/凶/咬/滚 |
| 卖萌 | 4 | 可爱/亲亲/抱抱/喵 |
| 回应 | 3 | 好的/收到/嗯 |
| 搞笑 | 2 | 哈哈/笑死/草 |
| 拒绝 / 夸奖 | 各 1 | 不行 / 牛 |

另有视觉标签：`静图`/`动图`、`方图`/`近方图`/`横图`/`竖图`、`暖色`/`冷色`/`中性`、`透明`、`有文字`/`无文字`。

> OCR 覆盖有限（约 27%），因为表情包字号小、字体花。现在由本地视觉模型补：机器人后台把每张读一遍，画面、意思、场景、画风、可不可爱记在 `reads.json`（按 id），不改 `index.json`。

## 机器人用法

```
/表情            随机
/表情 搞笑       按分类或标签/文字匹配
/表情 分类       看分类统计
```

插件：`bot/plugins/stickers.py`（冷却 5 秒，只允许机器人号发言）。

## 重新生成

```powershell
# 1) 导出（只读 QQ 目录）
.venv\Scripts\python tools\export_qq_emoji.py --src "<...>\personal_emoji\Ori" --out stickers

# 2) OCR（Windows 自带引擎，PS 5.1）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\ocr_stickers.ps1 -Dir stickers\ori -Out stickers\ocr.jsonl
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\ocr_stickers_2x.ps1 -Dir stickers\ori -Out stickers\ocr2.jsonl

# 3) 合并 + 打标签
.venv\Scripts\python tools\tag_stickers.py --dir stickers
```

> `ocr_stickers_2x.ps1` 必须带 UTF-8 BOM，否则 PowerShell 5.1 会按 ANSI 解析中文导致语法错误。
