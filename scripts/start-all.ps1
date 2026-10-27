<#
.SYNOPSIS
    一键启动整套原生栈：NoneBot2（框架层）+ SnowLuma（协议端）。

.DESCRIPTION
    默认不注入 QQ（-AutoLoad 才注入）。启动顺序：先框架、后协议端，
    这样 SnowLuma 一上线就能连上反向 WS。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Z:\snowluma\scripts\start-all.ps1
    # 已登录 QQ 后再用（会自动注入并拉起 OneBot 3000/3001）
    powershell -ExecutionPolicy Bypass -File Z:\snowluma\scripts\start-all.ps1 -AutoLoad
#>
[CmdletBinding()]
param(
    [switch]$AutoLoad,
    [int]$NoneBotPort = 18080,
    [int]$WebUiPort = 5099,
    [string]$WebUiPassword = '<WEBUI_PASSWORD>'
)

$ErrorActionPreference = 'Stop'
$root = 'Z:\snowluma'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$nbPy = Join-Path $root 'stack\.venv\Scripts\python.exe'
$nbDir = Join-Path $root 'stack\nonebot'
$slExe = Join-Path $root 'SnowLuma\node.exe'
$slDir = Join-Path $root 'SnowLuma'

foreach ($p in @($nbPy, $slExe)) {
    if (-not (Test-Path $p)) { throw "缺少运行时: $p" }
}

function Wait-Port([int]$Port, [int]$Seconds = 40) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

# --- 1) NoneBot2 ---
if (Get-NetTCPConnection -State Listen -LocalPort $NoneBotPort -ErrorAction SilentlyContinue) {
    Write-Host "NoneBot2 已在 $NoneBotPort 运行，跳过" -ForegroundColor DarkGray
} else {
    # 解析插件需要 ffmpeg 在 PATH 里（便携版放在 tools\ffmpeg\bin）
$ffmpegBin = 'Z:\snowluma\tools\ffmpeg\bin'
if (Test-Path $ffmpegBin) { $env:PATH = "$ffmpegBin;$env:PATH" }

$env:HOST = '127.0.0.1'
    $env:PORT = "$NoneBotPort"
    $env:LOG_LEVEL = 'INFO'
    $env:ONEBOT_ACCESS_TOKEN = '<ONEBOT_ACCESS_TOKEN>'
    # 不设这个的话，日志走 GBK 会把中文/emoji 写成乱码（loguru 报 UnicodeEncodeError）
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $p = Start-Process -FilePath $nbPy -ArgumentList 'bot.py' -WorkingDirectory $nbDir `
        -RedirectStandardOutput (Join-Path $logs 'nonebot.out.log') `
        -RedirectStandardError (Join-Path $logs 'nonebot.err.log') `
        -PassThru -WindowStyle Hidden
    if (-not (Wait-Port $NoneBotPort)) { throw "NoneBot2 启动失败，见 $logs\nonebot.err.log" }
    Write-Host "NoneBot2 已启动 (pid $($p.Id))  127.0.0.1:$NoneBotPort" -ForegroundColor Green
}

# --- 2) SnowLuma ---
if (Get-NetTCPConnection -State Listen -LocalPort $WebUiPort -ErrorAction SilentlyContinue) {
    Write-Host "SnowLuma 已在 $WebUiPort 运行，跳过" -ForegroundColor DarkGray
} else {
    $env:SNOWLUMA_HOOK_AUTOLOAD = if ($AutoLoad) { '1' } else { '0' }
    $env:SNOWLUMA_LOG_LEVEL = 'info'
    # 固定 WebUI 初始密码，避免"重启即换密码、日志又被脱敏"导致找不回
    $env:SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD = $WebUiPassword
    $p = Start-Process -FilePath $slExe -ArgumentList './index.mjs' -WorkingDirectory $slDir `
        -RedirectStandardOutput (Join-Path $logs 'snowluma.out.log') `
        -RedirectStandardError (Join-Path $logs 'snowluma.err.log') `
        -PassThru -WindowStyle Hidden
    if (-not (Wait-Port $WebUiPort)) { throw "SnowLuma 启动失败，见 $logs\snowluma.err.log" }
    Write-Host "SnowLuma 已启动 (pid $($p.Id))  WebUI 127.0.0.1:$WebUiPort" -ForegroundColor Green
    $mode = '不注入（登录后手动 Load，或用 -AutoLoad 重启）'
    if ($AutoLoad) { $mode = '自动注入（会 hook 已登录的 QQ）' }
    Write-Host ("注入模式: {0}" -f $mode) -ForegroundColor DarkGray
}

Write-Host ''
Write-Host '--- 当前状态 ---' -ForegroundColor Cyan
foreach ($conn in (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $NoneBotPort, $WebUiPort, 3000, 3001 })) {
    $pr = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    Write-Host ("  {0,-6} {1}" -f $conn.LocalPort, $pr.ProcessName)
}

if (-not $AutoLoad) {
    Write-Host ''
    Write-Host 'WebUI: http://127.0.0.1:5099/  （首次登录需改密 + 同意 EULA）' -ForegroundColor Yellow
    Write-Host '登录 QQ 后重跑本脚本加 -AutoLoad，或到 WebUI 手动 Load 账号。' -ForegroundColor Yellow
}


