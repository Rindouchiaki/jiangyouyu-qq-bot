#requires -Version 5.1
<#
.SYNOPSIS
    下载 SnowLuma 的 Windows 发行包（默认完整版，自带 Node.js）并解压。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install-snowluma.ps1
    powershell -ExecutionPolicy Bypass -File .\install-snowluma.ps1 -Version v2.2.0
    powershell -ExecutionPolicy Bypass -File .\install-snowluma.ps1 -Lite

.NOTES
    -Lite 包不含 Node.js，需要本机已有 Node 24（engines: ^24.22.1 || >=26.12.1）。
    国内网络慢可用 -Proxy 指定 HTTP 代理，或改用 GitHub 加速前缀。
#>
[CmdletBinding()]
param(
    [string]$Version = 'latest',
    [string]$Destination = 'Z:\snowluma\SnowLuma',
    [switch]$Lite,
    [string]$Proxy
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$headers = @{ 'User-Agent' = 'snowluma-install-script'; 'Accept' = 'application/vnd.github+json' }
$apiBase = 'https://api.github.com/repos/SnowLuma/SnowLuma/releases'

if ($Version -eq 'latest') {
    Write-Host '查询最新 release ...' -ForegroundColor Cyan
    $release = Invoke-RestMethod -Uri "$apiBase/latest" -Headers $headers
} else {
    Write-Host "查询 release $Version ..." -ForegroundColor Cyan
    $release = Invoke-RestMethod -Uri "$apiBase/tags/$Version" -Headers $headers
}

Write-Host ("版本: {0}  发布时间: {1}" -f $release.tag_name, $release.published_at) -ForegroundColor Green

$pattern = if ($Lite) { 'win-x64-lite\.zip$' } else { 'win-x64\.zip$' }
$asset = $release.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1

if (-not $asset) {
    $names = ($release.assets | ForEach-Object { $_.name }) -join ', '
    throw "没有找到匹配 $pattern 的资产。该 release 的资产: $names"
}

Write-Host ("资产: {0}  ({1:N1} MB)" -f $asset.name, ($asset.size / 1MB)) -ForegroundColor Green

$tmpDir = Join-Path $env:TEMP ("snowluma-dl-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$zipPath = Join-Path $tmpDir $asset.name

$dlParams = @{
    Uri             = $asset.browser_download_url
    OutFile         = $zipPath
    UseBasicParsing = $true
    Headers         = @{ 'User-Agent' = 'snowluma-install-script' }
}
if ($Proxy) { $dlParams['Proxy'] = $Proxy }

Write-Host '下载中 ...' -ForegroundColor Cyan
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest @dlParams

if (Test-Path -LiteralPath $Destination) {
    $existing = Get-ChildItem -LiteralPath $Destination -Force | Select-Object -First 1
    if ($existing) {
        Write-Host "目标目录已存在且非空: $Destination" -ForegroundColor Yellow
        throw '为避免覆盖已有安装，请先移动/删除该目录，或换 -Destination。'
    }
}
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

Write-Host "解压到 $Destination ..." -ForegroundColor Cyan
Expand-Archive -LiteralPath $zipPath -DestinationPath $Destination -Force

# 有些压缩包会多一层顶层目录，拍平
$children = Get-ChildItem -LiteralPath $Destination -Force
if ($children.Count -eq 1 -and $children[0].PSIsContainer -and
    (Test-Path -LiteralPath (Join-Path $children[0].FullName 'index.mjs'))) {
    Write-Host '拍平顶层目录 ...' -ForegroundColor Cyan
    Get-ChildItem -LiteralPath $children[0].FullName -Force |
        Move-Item -Destination $Destination
    Remove-Item -LiteralPath $children[0].FullName -Force -Recurse
}

Remove-Item -LiteralPath $tmpDir -Force -Recurse -ErrorAction SilentlyContinue

$entry = Join-Path $Destination 'index.mjs'
if (-not (Test-Path -LiteralPath $entry)) {
    throw "解压后未找到 index.mjs，请检查压缩包结构: $Destination"
}

Write-Host ''
Write-Host '安装完成。下一步:' -ForegroundColor Green
Write-Host "  1) cd `"$Destination`""
Write-Host '  2) .\launcher.bat        # 首次启动请在控制台里记下「临时密码 / initial credentials」'
Write-Host '  3) 浏览器打开 http://127.0.0.1:5099/'
Write-Host '  4) 确认 QQ 已注入、账号在线，然后在网络适配器里复制 accessToken'
Write-Host '  5) 冒烟测试: scripts\smoke-test-onebot.ps1 -Token <HTTP_TOKEN>'
Write-Host ''
if (-not $Lite) {
    Write-Host '（完整版自带 Node.js，无需另装）' -ForegroundColor DarkGray
} else {
    Write-Host '提示: Lite 包需要 Node 24，运行 node -v 检查版本。' -ForegroundColor Yellow
}
