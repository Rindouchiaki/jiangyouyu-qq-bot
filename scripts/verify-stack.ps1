<#
.SYNOPSIS
    整套栈自检：框架层就绪？协议端在线？反向 WS 连上了？QQ 登录了？

.DESCRIPTION
    登录前也能跑：会显示「等待登录」而不是报错。
    登录后跑这一条，就能一次性确认 SnowLuma -> NoneBot -> 插件 全链路。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Z:\snowluma\scripts\verify-stack.ps1
#>
[CmdletBinding()]
param(
    [int]$NoneBotPort = 18080,
    [int]$WebUiPort = 5099,
    [int]$HttpPort = 3000,
    [int]$CorePort = 8765,
    [string]$HttpToken = '<ONEBOT_HTTP_TOKEN>',
    [string]$NbToken = '<ONEBOT_ACCESS_TOKEN>'
)

$ErrorActionPreference = 'Continue'
$root = 'Z:\snowluma'
$nbLog = Join-Path $root 'logs\nonebot.out.log'
$slLog = Join-Path $root 'logs\snowluma.out.log'
$results = [System.Collections.Generic.List[object]]::new()

function Add-Result([string]$Item, [string]$State, [string]$Note = '') {
    $results.Add([pscustomobject]@{ 检查 = $Item; 结果 = $State; 说明 = $Note })
    $color = switch ($State) { 'PASS' { 'Green' } 'WAIT' { 'Yellow' } default { 'Red' } }
    Write-Host ("  [{0}] {1} {2}" -f $State, $Item, $Note) -ForegroundColor $color
}

Write-Host '=== 栈自检 ===' -ForegroundColor Cyan

# 1) NoneBot2
$nb = Get-NetTCPConnection -State Listen -LocalPort $NoneBotPort -ErrorAction SilentlyContinue
if ($nb) { Add-Result 'NoneBot2 监听' 'PASS' "127.0.0.1:$NoneBotPort" }
else { Add-Result 'NoneBot2 监听' 'FAIL' '未监听，先跑 scripts\start-all.ps1' }

# 2) SnowLuma WebUI
$sl = Get-NetTCPConnection -State Listen -LocalPort $WebUiPort -ErrorAction SilentlyContinue
if ($sl) { Add-Result 'SnowLuma WebUI' 'PASS' "127.0.0.1:$WebUiPort" }
else { Add-Result 'SnowLuma WebUI' 'FAIL' '未监听，先跑 scripts\start-all.ps1' }

# 2.5) 早柚核心（可选，游戏查询）
$core = Get-NetTCPConnection -State Listen -LocalPort $CorePort -ErrorAction SilentlyContinue
if ($core) { Add-Result '早柚核心监听' 'PASS' "127.0.0.1:$CorePort" }
else { Add-Result '早柚核心监听' 'WAIT' '未监听：游戏查询不可用，人设不受影响' }

# 3) 框架层往返（不依赖 QQ）
if ($nb) {
    $py = Join-Path $root 'stack\.venv\Scripts\python.exe'
    if (Test-Path $py) {
        $env:PYTHONIOENCODING = 'utf-8'
        $out = & $py (Join-Path $root 'stack\tests\fake_onebot_client.py') --token $NbToken --self-id 100000001 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0) { Add-Result '框架层往返 (/ping)' 'PASS' '收到 send_msg pong' }
        elseif ($out -match '403|already a bot') {
            Add-Result '框架层往返 (/ping)' 'WAIT' '真账号已占着同 self_id 的连接，假客户端连不进去（不是故障）'
        }
        else {
            Add-Result '框架层往返 (/ping)' 'FAIL' '见下方输出'
            Write-Host $out -ForegroundColor DarkGray
        }
    }
}

# 4) OneBot HTTP（需要 QQ 已登录并 Load）
$http = Get-NetTCPConnection -State Listen -LocalPort $HttpPort -ErrorAction SilentlyContinue
if (-not $http) {
    Add-Result 'OneBot HTTP 3000' 'WAIT' '账号未登录/未 Load（预期）'
} else {
    $body = @{ action = 'get_login_info'; params = @{}; echo = 'verify' } | ConvertTo-Json -Compress
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$HttpPort/" -Method Post -Body $body `
            -ContentType 'application/json' -Headers @{ Authorization = "Bearer $HttpToken" } -TimeoutSec 8
        if ($resp.status -eq 'ok' -and $resp.data.user_id) {
            Add-Result 'QQ 已登录' 'PASS' ("uin={0} 昵称={1}" -f $resp.data.user_id, $resp.data.nickname)
        } else {
            Add-Result 'QQ 已登录' 'FAIL' ($resp | ConvertTo-Json -Depth 4 -Compress)
        }
    } catch {
        Add-Result 'OneBot HTTP 调用' 'FAIL' $_.Exception.Message
    }
}

# 5) 反向 WS 是否连上（看 NoneBot 日志；10001 是自检用的假客户端，要排除）
if (Test-Path $nbLog) {
    $hits = Select-String -LiteralPath $nbLog -Pattern 'OneBot V11 \| Bot (\d+) connected' -ErrorAction SilentlyContinue
    $real = $hits | Where-Object { $_.Matches[0].Groups[1].Value -ne '10001' } | Select-Object -Last 1
    if ($real) {
        Add-Result '反向 WS 连接' 'PASS' $real.Line.Trim()
    } else {
        Add-Result '反向 WS 连接' 'WAIT' 'NoneBot 还没收到 SnowLuma 的真实连接（需账号上线并 Load）'
    }
} else {
    Add-Result 'NoneBot 日志' 'WAIT' "未找到 $nbLog"
}

# 4.5) 账号级配置一致性（登录后 SnowLuma 会生成 onebot_<uin>.json）
$cfgDir = Join-Path $root 'SnowLuma\config'
$perUin = Get-ChildItem -LiteralPath $cfgDir -Filter 'onebot_*.json' -ErrorAction SilentlyContinue
if ($perUin) {
    foreach ($f in $perUin) {
        try {
            $c = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json
            $client = @($c.networks.wsClients) | Where-Object { $_.url -like '*18080*' } | Select-Object -First 1
            if (-not $client) {
                Add-Result "账号配置 $($f.Name)" 'FAIL' '缺少指向 18080 的 wsClients'
            } elseif ($client.accessToken -ne $NbToken) {
                Add-Result "账号配置 $($f.Name)" 'FAIL' 'wsClients token 与 NoneBot 不一致，需同步'
            } else {
                Add-Result "账号配置 $($f.Name)" 'PASS' 'wsClients 已指向 18080 且 token 一致'
            }
        } catch {
            Add-Result "账号配置 $($f.Name)" 'FAIL' $_.Exception.Message
        }
    }
} else {
    Add-Result '账号级配置' 'WAIT' '尚未生成 onebot_<uin>.json（登录后出现）'
}

Write-Host ''
$fail = @($results | Where-Object { $_.结果 -eq 'FAIL' }).Count
$wait = @($results | Where-Object { $_.结果 -eq 'WAIT' }).Count
if ($fail -gt 0) { Write-Host "结果: $fail 项失败，$wait 项等待中" -ForegroundColor Red; exit 1 }
if ($wait -gt 0) { Write-Host "结果: 无失败，$wait 项等待登录" -ForegroundColor Yellow; exit 0 }
Write-Host '结果: 全部通过 ✅' -ForegroundColor Green
exit 0
