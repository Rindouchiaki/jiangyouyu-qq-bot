<#
.SYNOPSIS
    酱油鱼一键启动：QQ → 本地视觉模型 → SnowLuma(协议端) → 早柚核心(游戏查询) → NoneBot2(人格/插件)。

.DESCRIPTION
    每一步都先查端口，已经在跑的不会重复起。退出脚本后服务继续跑
    （用 Start-Process 分离、隐藏窗口，不挂在当前窗口上）。
    路径和口令都从 bot\persona.env 读；第一次用先双击「一键部署.cmd」（= scripts\setup.ps1 -Start）。

    常用：
      .\scripts\启动全部.ps1                  # 全套拉起
      .\scripts\启动全部.ps1 -Status          # 只看现在谁在跑
      .\scripts\启动全部.ps1 -Stop            # 全停
      .\scripts\启动全部.ps1 -NoVl            # 不启本地视觉模型（省 1GB 内存）
      .\scripts\启动全部.ps1 -NoAutoLoad      # SnowLuma 不自动注入 QQ 账号
      .\scripts\启动全部.ps1 -NoCore          # 不启早柚核心（星铁/绝区零/崩坏3 查询）
      .\scripts\启动全部.ps1 -NoQQ            # 不去拉起 QQ

.NOTES
    日志都在仓库的 logs\（persona.env 的 LOG_DIR 可改），WebUI http://127.0.0.1:5099/
#>
[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Status,
    [switch]$NoVl,
    [switch]$NoAutoLoad,
    [switch]$NoCore,
    [switch]$NoQQ,
    [int]$NoneBotPort = 18080,
    [int]$WebUiPort = 5099,
    [int]$VlPort = 11435,
    [int]$CorePort = 8765
)

$ErrorActionPreference = 'Stop'
# 让中文输出在重定向/日志里也正常（默认可能按 GBK 写）
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch { }
. "$PSScriptRoot\common.ps1"
$cfg = Get-StackConfig
$logs = $cfg.Logs
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$nbPy = $cfg.Python
$nbDir = $cfg.BotDir
$slDir = $cfg.SnowLuma
$slExe = Join-Path $slDir 'node.exe'
$vlBin = Join-Path $cfg.Tools 'llama.cpp\bin\llama-server.exe'
if (-not (Test-Path $vlBin)) { $vlBin = Join-Path $cfg.Tools 'llama.cpp\llama-server.exe' }
$vlModel = Join-Path $cfg.Tools 'vl-model\Qwen3-VL-2B-Instruct-Q4_K_M.gguf'
$vlMmproj = Join-Path $cfg.Tools 'vl-model\mmproj-F16.gguf'
$qqExe = $cfg.QQ
$ffmpegBin = $cfg.Ffmpeg
$coreDir = $cfg.Core

function Show-Status {
    Write-Host ''
    Write-Host '--- 当前状态 ---' -ForegroundColor Cyan
    foreach ($item in @(
            @{ Port = $WebUiPort; Name = 'SnowLuma WebUI' },
            @{ Port = 3000; Name = 'OneBot HTTP' },
            @{ Port = 3001; Name = 'OneBot WS' },
            @{ Port = $CorePort; Name = '早柚核心' },
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
    & "$PSScriptRoot\stop-all.ps1" -NoneBotPort $NoneBotPort
    Show-Status
    return
}

if ($Status) { Show-Status; return }

if (-not (Test-Path -LiteralPath $cfg.EnvFile)) { throw "还没有 bot\persona.env，先双击「一键部署.cmd」" }

Write-Host '=== 酱油鱼一键启动 ===' -ForegroundColor Cyan

# ------------------------------------------------------------------ 1) QQ
$qqRunning = [bool](Get-Process -Name QQ -ErrorAction SilentlyContinue)
if (-not $qqRunning -and -not $NoQQ) {
    if (Test-Path $qqExe) {
        Write-Host '启动 QQ ...' -ForegroundColor Yellow
        Start-Process -FilePath $qqExe | Out-Null
        Start-Sleep -Seconds 8
        $qqRunning = [bool](Get-Process -Name QQ -ErrorAction SilentlyContinue)
    } else {
        Write-Warning "找不到 QQ：$qqExe（装在别处就在 persona.env 里设 QQ_EXE）"
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
        Write-Host '没装本地视觉模型（可选），跳过；无字图片将没有描述' -ForegroundColor DarkGray
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
    throw "找不到 SnowLuma：$slExe（先双击「一键部署.cmd」；装在别处就在 persona.env 里设 SNOWLUMA_DIR）"
} else {
    $autoLoad = if ($NoAutoLoad) { '0' } else { '1' }
    $env:SNOWLUMA_HOOK_AUTOLOAD = $autoLoad
    $env:SNOWLUMA_LOG_LEVEL = 'info'
    # 固定 WebUI 初始密码，避免重启就换密码、日志又被脱敏（只在第一次启动时生效）
    if ($cfg.Env['SNOWLUMA_WEBUI_PASSWORD']) { $env:SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD = $cfg.Env['SNOWLUMA_WEBUI_PASSWORD'] }
    Write-Host '启动 SnowLuma（协议端）...' -ForegroundColor Yellow
    $p = Start-Process -FilePath $slExe -ArgumentList './index.mjs' -WorkingDirectory $slDir `
        -RedirectStandardOutput (Join-Path $logs 'snowluma.out.log') `
        -RedirectStandardError (Join-Path $logs 'snowluma.err.log') `
        -PassThru -WindowStyle Hidden
    if (-not (Wait-Listening $WebUiPort 45)) { throw "SnowLuma 启动失败，见 $logs\snowluma.err.log" }
    Write-Host "SnowLuma 已启动 (pid $($p.Id))  WebUI 127.0.0.1:$WebUiPort" -ForegroundColor Green
    if ($autoLoad -eq '1') { Write-Host '会自动注入已登录的 QQ 账号（没登录就去 WebUI 手动 Load）' -ForegroundColor DarkGray }
}

# ------------------------------------------------------------------ 4) 早柚核心（可选）
# 先于 NoneBot 起，连接插件一启动就能连上；没装或起不来都不影响人设
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($NoCore) {
    Write-Host '跳过早柚核心（-NoCore）' -ForegroundColor DarkGray
} elseif (Test-Listening $CorePort) {
    Write-Host "早柚核心已在 $CorePort 运行，跳过" -ForegroundColor DarkGray
} elseif (-not (Test-Path $coreDir)) {
    Write-Host "没装早柚核心（$coreDir），游戏查询不可用；双击「一键部署.cmd」会装上" -ForegroundColor DarkYellow
} elseif (-not $uv) {
    Write-Host '找不到 uv，早柚核心没法启动；双击「一键部署.cmd」会装上' -ForegroundColor DarkYellow
} else {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    Write-Host '启动早柚核心（星铁/绝区零/崩坏3 查询）...' -ForegroundColor Yellow
    # 全局 ErrorActionPreference=Stop，起不来也不能拦住后面的 NoneBot
    try {
        $p = Start-Process -FilePath $uv.Source -ArgumentList 'run', 'core' -WorkingDirectory $coreDir `
            -RedirectStandardOutput (Join-Path $logs 'gscore.out.log') `
            -RedirectStandardError (Join-Path $logs 'gscore.err.log') `
            -PassThru -WindowStyle Hidden
        if (Wait-Listening $CorePort 90) {
            Write-Host "早柚核心已启动 (pid $($p.Id))  控制台 http://127.0.0.1:$CorePort/app" -ForegroundColor Green
        } else {
            Write-Host "早柚核心 90 秒内没监听（首次启动可能还在装依赖），见 $logs\gscore.err.log；不影响人设" -ForegroundColor DarkYellow
        }
    } catch {
        Write-Host "早柚核心启动失败：$($_.Exception.Message)；不影响人设" -ForegroundColor DarkYellow
    }
}

# ------------------------------------------------------------------ 5) NoneBot2
if (Test-Listening $NoneBotPort) {
    Write-Host "NoneBot2 已在 $NoneBotPort 运行，跳过" -ForegroundColor DarkGray
} elseif (-not (Test-Path $nbPy)) {
    throw "找不到 NoneBot 运行时：$nbPy（先双击「一键部署.cmd」）"
} else {
    if (Test-Path $ffmpegBin) { $env:PATH = "$ffmpegBin;$env:PATH" }
    $env:HOST = '127.0.0.1'
    $env:PORT = "$NoneBotPort"
    $env:LOG_LEVEL = 'INFO'
    # 反向 WS 的 token 由 bot.py 从 persona.env 的 ONEBOT_ACCESS_TOKEN 读，要和 SnowLuma onebot.json 的 wsClients 一致
    if (-not $cfg.Env['ONEBOT_ACCESS_TOKEN']) { Write-Warning 'persona.env 没有 ONEBOT_ACCESS_TOKEN：反向 WS 不校验 token' }
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
Write-Host "WebUI: http://127.0.0.1:$WebUiPort/   日志: $logs" -ForegroundColor Cyan
Write-Host '停止全部：双击「一键停止.cmd」，或 .\scripts\启动全部.ps1 -Stop' -ForegroundColor DarkGray
