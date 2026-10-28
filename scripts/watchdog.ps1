<#
.SYNOPSIS
    酱油鱼守护：一键启动过之后，NoneBot2 掉了就自动补起来（配了本地视觉模型的，它掉了也补）。

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

# 没启动过、或者用户刚用「一键停止」停过：什么都不做
if (-not (Test-Path $flag)) { return }

function Test-Listening([int]$port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1)
}

$down = @()
if (-not (Test-Listening $NoneBotPort)) { $down += 'NoneBot2' }
if ($cfg.VlEnabled -and -not (Test-Listening $VlPort)) { $down += '本地视觉模型' }
if ($down.Count -eq 0) { return }

Add-Content -LiteralPath $watchLog -Value ("[{0}] 发现掉线: {1}，尝试拉起" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), ($down -join '、')) -Encoding utf8

& "$PSScriptRoot\start-all-here.ps1" -NoneBotPort $NoneBotPort -VlPort $VlPort | Out-Null

$after = @()
if (-not (Test-Listening $NoneBotPort)) { $after += 'NoneBot2' }
if ($cfg.VlEnabled -and -not (Test-Listening $VlPort)) { $after += '本地视觉模型' }
$result = if ($after.Count -eq 0) { '已恢复' } else { "仍未恢复: $($after -join '、')" }
Add-Content -LiteralPath $watchLog -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $result) -Encoding utf8
