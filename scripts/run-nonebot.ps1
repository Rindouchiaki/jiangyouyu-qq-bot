# 前台启动 NoneBot2（看日志、调试用）；平时用 启动全部.ps1 后台跑
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
$cfg = Get-StackConfig

if (-not (Test-Path $cfg.Python)) { throw "找不到 venv python: $($cfg.Python)" }

# 解析插件需要 ffmpeg 在 PATH 里（便携版放在 tools\ffmpeg\bin）
if (Test-Path $cfg.Ffmpeg) { $env:PATH = "$($cfg.Ffmpeg);$env:PATH" }

$env:HOST = '127.0.0.1'
$env:PORT = '18080'   # 8080 被 Steam 占用，统一用 18080
$env:LOG_LEVEL = 'INFO'
# 日志编码：不设会用 GBK，中文/emoji 变乱码
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# 反向 WS 的 token 在 persona.env 的 ONEBOT_ACCESS_TOKEN，与 SnowLuma onebot.json 的 wsClients[0].accessToken 必须一致

Write-Host "NoneBot2 启动: http://$($env:HOST):$($env:PORT)  反向 WS: ws://$($env:HOST):$($env:PORT)/onebot/v11/ws" -ForegroundColor Cyan
Set-Location $cfg.BotDir
& $cfg.Python bot.py
