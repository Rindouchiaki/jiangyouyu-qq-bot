<#
.SYNOPSIS
    酱油鱼守护：一键启动过之后，NoneBot2 或本地视觉模型（开着且装了的话）掉了就自动补起来。

.DESCRIPTION
    只在 logs\.stack-on 这个标记存在时才干活。「一键停止.cmd」（= start-all-here.ps1 -Stop）
    会删掉标记，所以手动停掉之后守护不会又把服务拉回来。

    由计划任务 JiangyouyuWatchdog 每 5 分钟调一次，也可以手动执行：
      .\scripts\watchdog.ps1

.NOTES
    日志写在 logs\watchdog.log，只在真的发现掉线时才写，平时不刷屏。
#>
[CmdletBinding()]
param(
    [int]$NoneBotPort = 18080,
    [int]$VlPort = 11435
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch { }
. "$PSScriptRoot\common.ps1"
$cfg = Get-StackConfig
$logs = $cfg.Logs
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$flag = Join-Path $logs '.stack-on'
$watchLog = Join-Path $logs 'watchdog.log'
# 视觉模型开着而且真装了才看护它，没装模型的机器别每 5 分钟都当它掉线
$vlWatch = $cfg.VlEnabled -and ((Test-Path (Join-Path $cfg.Tools 'llama.cpp\bin\llama-server.exe')) -or (Test-Path (Join-Path $cfg.Tools 'llama.cpp\llama-server.exe')))

# 没启动过、或者用户刚用「一键停止」停过：什么都不做
if (-not (Test-Path $flag)) { return }

# 一键启动刚跑过（标记刚写）：这轮让给它，别和它同时拉开同一个服务
$flagAge = (Get-Date) - (Get-Item -LiteralPath $flag).LastWriteTime
if ($flagAge.TotalMinutes -lt 4) { return }
# 另一个 start-all 还在跑：也让它
$starting = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*start-all-here.ps1*' })
if ($starting.Count -gt 0) { return }

function Test-Listening([int]$port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1)
}

$down = @()
if (-not (Test-Listening $NoneBotPort)) { $down += 'NoneBot2' }
if ($vlWatch -and -not (Test-Listening $VlPort)) { $down += '本地视觉模型' }
if ($down.Count -eq 0) { return }

Add-Content -LiteralPath $watchLog -Value ("[{0}] 发现掉线: {1}，尝试拉起" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), ($down -join '、')) -Encoding utf8

& "$PSScriptRoot\start-all-here.ps1" -NoneBotPort $NoneBotPort -VlPort $VlPort | Out-Null

$after = @()
if (-not (Test-Listening $NoneBotPort)) { $after += 'NoneBot2' }
if ($vlWatch -and -not (Test-Listening $VlPort)) { $after += '本地视觉模型' }
$result = if ($after.Count -eq 0) { '已恢复' } else { "仍未恢复: $($after -join '、')" }
Add-Content -LiteralPath $watchLog -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $result) -Encoding utf8
