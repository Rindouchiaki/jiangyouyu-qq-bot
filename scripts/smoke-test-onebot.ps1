#requires -Version 5.1
<#
.SYNOPSIS
    SnowLuma OneBot v11 冒烟测试：校验 access token、查登录账号、探 WS 事件流。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\smoke-test-onebot.ps1 -Token "xxx"

.EXAMPLE
    .\smoke-test-onebot.ps1 -Token "xxx" -BaseUrl "http://127.0.0.1:3000/" -SkipWebSocket

.NOTES
    Token 在 WebUI 的「网络适配器」里复制，或见 config/onebot_<uin>.json 的 accessToken。
    HTTP 与 WS 的 token 是各自独立的，这里 WS 默认复用 -Token，可用 -WsToken 单独指定。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Token,
    [string]$BaseUrl = 'http://127.0.0.1:3000/',
    [string]$WsUrl = 'ws://127.0.0.1:3001/',
    [string]$WsToken,
    [switch]$SkipWebSocket
)

$ErrorActionPreference = 'Stop'
$script:failed = 0

function Invoke-OneBotAction {
    param([string]$Action, [hashtable]$Params = @{})

    $body = @{ action = $Action; params = $Params; echo = "$Action-$([guid]::NewGuid().ToString('N').Substring(0,6))" } | ConvertTo-Json -Depth 8 -Compress
    $uri = $BaseUrl.TrimEnd('/') + '/'

    try {
        $resp = Invoke-RestMethod -Uri $uri -Method Post -Body $body -ContentType 'application/json' `
            -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec 10
        return [pscustomobject]@{ Ok = $true; Response = $resp; Error = $null }
    } catch {
        return [pscustomobject]@{ Ok = $false; Response = $null; Error = $_.Exception.Message }
    }
}

function Test-OneBotAction {
    param([string]$Action, [hashtable]$Params = @{}, [switch]$Critical)

    Write-Host ("→ {0} ... " -f $Action) -NoNewline
    $r = Invoke-OneBotAction -Action $Action -Params $Params

    if (-not $r.Ok) {
        Write-Host 'FAIL' -ForegroundColor Red
        Write-Host ("  传输错误: {0}" -f $r.Error) -ForegroundColor Red
        Write-Host '  排查: SnowLuma 是否在跑？端口/token 对不对？host 是否只监听 127.0.0.1？' -ForegroundColor DarkYellow
        if ($Critical) { $script:failed++ }
        return $null
    }

    $retcode = $r.Response.retcode
    $status = $r.Response.status
    if ($status -eq 'ok' -or $retcode -eq 0) {
        Write-Host 'OK' -ForegroundColor Green
        return $r.Response
    }

    Write-Host ("FAIL (status={0} retcode={1})" -f $status, $retcode) -ForegroundColor Red
    if ($r.Response.wording) { Write-Host ("  wording: {0}" -f $r.Response.wording) -ForegroundColor Red }
    if ($r.Response.message) { Write-Host ("  message: {0}" -f $r.Response.message) -ForegroundColor Red }
    if ($retcode -in @(1403, 1401)) {
        Write-Host '  → 鉴权失败：token 不匹配或无 token 头' -ForegroundColor DarkYellow
    }
    if ($Critical) { $script:failed++ }
    return $r.Response
}

Write-Host ''
Write-Host '=== SnowLuma OneBot v11 冒烟测试 ===' -ForegroundColor Cyan
Write-Host ("HTTP: {0}" -f $BaseUrl)
Write-Host ''

$login = Test-OneBotAction -Action 'get_login_info' -Critical
if ($login -and $login.data) {
    Write-Host ("  当前账号: {0}  昵称: {1}" -f $login.data.user_id, $login.data.nickname) -ForegroundColor Green
}

$status = Test-OneBotAction -Action 'get_status'
if ($status -and $status.data) {
    Write-Host ("  online={0}  good={1}" -f $status.data.online, $status.data.good) -ForegroundColor Green
}

$ver = Test-OneBotAction -Action 'get_version_info'
if ($ver -and $ver.data) {
    Write-Host ("  协议端: {0} {1}" -f $ver.data.app_name, $ver.data.app_version) -ForegroundColor Green
}

if ($SkipWebSocket) {
    Write-Host ''
    Write-Host '跳过 WebSocket 测试 (-SkipWebSocket)' -ForegroundColor DarkGray
} else {
    Write-Host ''
    Write-Host '→ WebSocket 事件流 ... ' -NoNewline
    $ws = $null
    try {
        $useToken = if ($WsToken) { $WsToken } else { $Token }
        $ws = [System.Net.WebSockets.ClientWebSocket]::new()
        if ($useToken) { $ws.Options.SetRequestHeader('Authorization', "Bearer $useToken") }

        $cts = [System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(10))
        $ws.ConnectAsync([Uri]$WsUrl, $cts.Token).GetAwaiter().GetResult()
        Write-Host 'CONNECTED' -ForegroundColor Green

        $buffer = [byte[]]::new(8192)
        $seg = [ArraySegment[byte]]::new($buffer)
        $cts2 = [System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(8))
        try {
            $result = $ws.ReceiveAsync($seg, $cts2.Token).GetAwaiter().GetResult()
            if ($result.Count -gt 0) {
                $text = [Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
                $obj = $text | ConvertFrom-Json -ErrorAction SilentlyContinue
                Write-Host ("  收到事件: post_type={0} message_type={1}" -f $obj.post_type, $obj.message_type) -ForegroundColor Green
            }
        } catch {
            Write-Host '  （8 秒内无事件——正常。去 QQ 里发条消息再跑一次，或检查 role 是否为 Universal）' -ForegroundColor DarkGray
        }
    } catch {
        Write-Host 'FAIL' -ForegroundColor Red
        Write-Host ("  WS 连接失败: {0}" -f $_.Exception.Message) -ForegroundColor Red
        Write-Host '  排查: 3001 是否监听、token 是否与 WS 适配器一致、路径是否为 /' -ForegroundColor DarkYellow
        $script:failed++
    } finally {
        if ($ws) {
            try { $ws.Dispose() } catch { }
        }
    }
}

Write-Host ''
if ($script:failed -eq 0) {
    Write-Host '结果: 全部通过 ✅  SnowLuma 管道已就绪，可以接机器人框架了。' -ForegroundColor Green
    exit 0
} else {
    Write-Host ("结果: {0} 项失败 ❌  见上方提示。" -f $script:failed) -ForegroundColor Red
    exit 1
}
