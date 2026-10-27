# 本地（非容器）启动 NoneBot2，参数与容器版保持一致
$ErrorActionPreference = 'Stop'

$root = 'Z:\snowluma'
$nbRoot = Join-Path $root 'stack\nonebot'
$py = Join-Path $root 'stack\.venv\Scripts\python.exe'

if (-not (Test-Path $py)) { throw "找不到 venv python: $py" }

# 解析插件需要 ffmpeg 在 PATH 里（便携版放在 tools\ffmpeg\bin）
$ffmpegBin = 'Z:\snowluma\tools\ffmpeg\bin'
if (Test-Path $ffmpegBin) { $env:PATH = "$ffmpegBin;$env:PATH" }

$env:HOST = '127.0.0.1'
$env:PORT = '18080'   # 8080 被 Steam 占用，统一用 18080
$env:LOG_LEVEL = 'INFO'
# 日志编码：不设会用 GBK，中文/emoji 变乱码
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# 与 SnowLuma config/onebot.json 的 wsClients[0].accessToken 必须一致
$env:ONEBOT_ACCESS_TOKEN = '<ONEBOT_ACCESS_TOKEN>'

Write-Host "NoneBot2 启动: http://$($env:HOST):$($env:PORT)  反向 WS: ws://$($env:HOST):$($env:PORT)/onebot/v11/ws" -ForegroundColor Cyan
Set-Location $nbRoot
& $py bot.py


