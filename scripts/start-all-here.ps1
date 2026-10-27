<#
.SYNOPSIS
    酱油鱼一键启动：QQ → 本地视觉模型 → SnowLuma(协议端) → NoneBot2(人格/插件)。

.DESCRIPTION
    每一步都先查端口，已经在跑的不会重复起。退出脚本后服务继续跑
    （用 Start-Process 分离，不挂在当前窗口上）。

    常用：
      .\启动全部.ps1                  # 全套拉起
      .\启动全部.ps1 -Status          # 只看现在谁在跑
      .\启动全部.ps1 -Stop            # 全停
      .\启动全部.ps1 -NoVl            # 不启本地视觉模型（省 1GB 内存）
      .\启动全部.ps1 -NoAutoLoad      # SnowLuma 不自动注入 QQ 账号

.NOTES
    日志都在 Z:\snowluma\logs\，WebUI http://127.0.0.1:5099/
#>
[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Status,
    [switch]$NoVl,
    [switch]$NoAutoLoad,
    [int]$NoneBotPort = 18080,
    [int]$WebUiPort = 5099,
    [int]$VlPort = 11435
)

$ErrorActionPreference = 'Stop'
# 让中文输出在重定向/日志里也正常（默认可能按 GBK 写）
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch { }
$root = 'Z:\snowluma'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$nbPy = Join-Path $root 'stack\.venv\Scripts\python.exe'
$nbDir = Join-Path $root 'stack\nonebot'
$slExe = Join-Path $root 'SnowLuma\node.exe'
$slDir = Join-Path $root 'SnowLuma'
$vlBin = Join-Path $root 'tools\llama.cpp\bin\llama-server.exe'
$vlModel = Join-Path $root 'tools\vl-model\Qwen3-VL-2B-Instruct-Q4_K_M.gguf'
$vlMmproj = Join-Path $root 'tools\vl-model\mmproj-F16.gguf'
$qqExe = 'C:\Program Files\Tencent\QQNT\QQ.exe'
$ffmpegBin = Join-Path $root 'tools\ffmpeg\bin'

function Test-Listening([int]$Port) {
    [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Listening([int]$Port, [int]$Seconds = 45) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Test-Listening $Port) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Show-Status {
    Write-Host ''
    Write-Host '--- 当前状态 ---' -ForegroundColor Cyan
    foreach ($item in @(
            @{ Port = $WebUiPort; Name = 'SnowLuma WebUI' },
            @{ Port = 3000; Name = 'OneBot HTTP' },
            @{ Port = 3001; Name = 'OneBot WS' },
            @{ Port = $NoneBotPort; Name = 'NoneBot2' },
            @{ Port = $VlPort; Name = '本地视觉模型' })) {
        $conn = Get-NetTCPConnection -State Listen -LocalPort $item.Port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) {
            $pr = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            Write-Host ("  [OK]   {0,-16} {1,-5}  pid {2}  {3}" -f $item.Name, $item.Port, $conn.OwningProcess, $pr.ProcessName) -ForegroundColor Green
        } else {
            Write-Host ("  [--]   {0,-16} {1,-5}  未运行" -f $item.Name, $item.Port) -ForegroundColor DarkGray
        }
    }
    $qq = Get-Process -Name QQ -ErrorAction SilentlyContinue
    if ($qq) {
        Write-Host ("  [OK]   QQ               pid {0}" -f ($qq | Select-Object -First 1).Id) -ForegroundColor Green
    } else {
        Write-Host '  [--]   QQ               未运行' -ForegroundColor DarkGray
    }
}

# ------------------------------------------------------------------ 停止
if ($Stop) {
    Write-Host '正在停止 NoneBot2 / SnowLuma / 本地视觉模型 ...' -ForegroundColor Yellow
    foreach ($port in @($NoneBotPort, $WebUiPort, $VlPort, 3000, 3001)) {
        Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    }
    # NoneBot 的 runtime 子进程可能不占端口，按命令行兜底
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*Z:\snowluma\stack\nonebot*' -or $_.CommandLine -like '*bot.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Write-Host '已停止（QQ 保留运行，需要的话手动关）' -ForegroundColor Green
    Show-Status
    return
}

if ($Status) { Show-Status; return }

Write-Host '=== 酱油鱼一键启动 ===' -ForegroundColor Cyan

# ------------------------------------------------------------------ 1) QQ
$qqRunning = [bool](Get-Process -Name QQ -ErrorAction SilentlyContinue)
if (-not $qqRunning) {
    if (Test-Path $qqExe) {
        Write-Host '启动 QQ ...' -ForegroundColor Yellow
        Start-Process -FilePath $qqExe | Out-Null
        Start-Sleep -Seconds 8
        $qqRunning = [bool](Get-Process -Name QQ -ErrorAction SilentlyContinue)
    } else {
        Write-Warning "找不到 QQ：$qqExe"
    }
}
if ($qqRunning) {
    Write-Host 'QQ 已在运行（如果还没登录，脚本照样能起，只是 SnowLuma 注入不到账号）' -ForegroundColor DarkGray
}

# ------------------------------------------------------------------ 2) 本地视觉模型
if (-not $NoVl) {
    if (Test-Listening $VlPort) {
        Write-Host "本地视觉模型已在 $VlPort 运行，跳过" -ForegroundColor DarkGray
    } elseif (-not (Test-Path $vlBin) -or -not (Test-Path $vlModel) -or -not (Test-Path $vlMmproj)) {
        Write-Warning "本地视觉模型不全（bin/model/mmproj 缺一个），跳过；无字图片将没有描述"
    } else {
        Write-Host '启动本地视觉模型（Qwen3-VL-2B, 首次加载约 10-20 秒）...' -ForegroundColor Yellow
        $vlArgs = @('-m', $vlModel, '--mmproj', $vlMmproj, '--host', '127.0.0.1', '--port', "$VlPort", '-c', '8192', '-ngl', '0', '--jinja')
        $p = Start-Process -FilePath $vlBin -ArgumentList $vlArgs -WorkingDirectory (Split-Path $vlBin) `
            -RedirectStandardOutput (Join-Path $logs 'vl.out.log') `
            -RedirectStandardError (Join-Path $logs 'vl.log') `
            -PassThru -WindowStyle Hidden
        if (-not (Wait-Listening $VlPort 60)) {
            Write-Warning "本地视觉模型没起来，看 $logs\vl.log（不影响聊天，只是无字图没描述）"
        } else {
            Write-Host "本地视觉模型已启动 (pid $($p.Id))  http://127.0.0.1:$VlPort" -ForegroundColor Green
        }
    }
}

# ------------------------------------------------------------------ 3) SnowLuma
if (Test-Listening $WebUiPort) {
    Write-Host "SnowLuma 已在 $WebUiPort 运行，跳过" -ForegroundColor DarkGray
} elseif (-not (Test-Path $slExe)) {
    throw "找不到 SnowLuma：$slExe"
} else {
    $autoLoad = if ($NoAutoLoad) { '0' } else { '1' }
    $env:SNOWLUMA_HOOK_AUTOLOAD = $autoLoad
    $env:SNOWLUMA_LOG_LEVEL = 'info'
    # 固定 WebUI 初始密码，避免重启就换密码、日志又被脱敏
    $env:SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD = '<WEBUI_PASSWORD>'
    Write-Host '启动 SnowLuma（协议端）...' -ForegroundColor Yellow
    $p = Start-Process -FilePath $slExe -ArgumentList './index.mjs' -WorkingDirectory $slDir `
        -RedirectStandardOutput (Join-Path $logs 'snowluma.out.log') `
        -RedirectStandardError (Join-Path $logs 'snowluma.err.log') `
        -PassThru -WindowStyle Hidden
    if (-not (Wait-Listening $WebUiPort 45)) { throw "SnowLuma 启动失败，见 $logs\snowluma.err.log" }
    Write-Host "SnowLuma 已启动 (pid $($p.Id))  WebUI 127.0.0.1:$WebUiPort" -ForegroundColor Green
    if ($autoLoad -eq '1') { Write-Host '会自动注入已登录的 QQ 账号（没登录就去 WebUI 手动 Load）' -ForegroundColor DarkGray }
}

# ------------------------------------------------------------------ 4) NoneBot2
if (Test-Listening $NoneBotPort) {
    Write-Host "NoneBot2 已在 $NoneBotPort 运行，跳过" -ForegroundColor DarkGray
} elseif (-not (Test-Path $nbPy)) {
    throw "找不到 NoneBot 运行时：$nbPy"
} else {
    if (Test-Path $ffmpegBin) { $env:PATH = "$ffmpegBin;$env:PATH" }
    $env:HOST = '127.0.0.1'
    $env:PORT = "$NoneBotPort"
    $env:LOG_LEVEL = 'INFO'
    $env:ONEBOT_ACCESS_TOKEN = '<ONEBOT_ACCESS_TOKEN>'
    # 不设这两个，日志会按 GBK 写，中文和 emoji 直接 UnicodeEncodeError
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    Write-Host '启动 NoneBot2（人格 + 插件）...' -ForegroundColor Yellow
    $p = Start-Process -FilePath $nbPy -ArgumentList 'bot.py' -WorkingDirectory $nbDir `
        -RedirectStandardOutput (Join-Path $logs 'nonebot.out.log') `
        -RedirectStandardError (Join-Path $logs 'nonebot.err.log') `
        -PassThru -WindowStyle Hidden
    if (-not (Wait-Listening $NoneBotPort 45)) { throw "NoneBot2 启动失败，见 $logs\nonebot.err.log" }
    Write-Host "NoneBot2 已启动 (pid $($p.Id))  127.0.0.1:$NoneBotPort" -ForegroundColor Green
}

Show-Status
Write-Host ''
Write-Host 'WebUI: http://127.0.0.1:5099/   日志: Z:\snowluma\logs\' -ForegroundColor Cyan
Write-Host '停止全部：.\启动全部.ps1 -Stop' -ForegroundColor DarkGray
