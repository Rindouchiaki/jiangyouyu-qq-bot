#requires -Version 5.1
<#
.SYNOPSIS
    下载 SnowLuma 的 Windows 发行包（默认完整版，自带 Node.js）并解压；-Upgrade 原地升级。

.DESCRIPTION
    默认装 external.lock.json 锁定的版本，并校验 sha256（锁文件里的值，以及 GitHub 给的摘要）。
    -Upgrade：只替换发行包自己的文件（看包里的 release.json），config、日志、登录状态都不动；
    被替换下来的旧文件放到「<目录>.bak-旧版本」，出问题可以挪回去。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install-snowluma.ps1
    powershell -ExecutionPolicy Bypass -File .\install-snowluma.ps1 -Upgrade
    powershell -ExecutionPolicy Bypass -File .\install-snowluma.ps1 -Version latest
    powershell -ExecutionPolicy Bypass -File .\install-snowluma.ps1 -Lite

.NOTES
    -Lite 包不含 Node.js，需要本机已有 Node 24（engines: ^24.22.1 || >=26.12.1）。
    国内网络慢可用 -Proxy 指定 HTTP 代理，或改用 GitHub 加速前缀。
#>
[CmdletBinding()]
param(
    # 不传就用 external.lock.json 锁定的版本；latest = GitHub 上最新的
    [string]$Version,
    # 不传就装到仓库的 SnowLuma\（persona.env 的 SNOWLUMA_DIR 可改）
    [string]$Destination,
    [string]$Sha256,
    [switch]$Upgrade,
    [switch]$Lite,
    [string]$Proxy
)

$ErrorActionPreference = 'Stop'
# PS 5.1 的参数默认值里 $PSScriptRoot 是空的，只能放到这里算
. "$PSScriptRoot\common.ps1"
if (-not $Destination) { $Destination = (Get-StackConfig).SnowLuma }
if (-not $Version) {
    $lock = Get-ExternalLock
    $Version = $lock.snowluma.version
    if (-not $Sha256 -and -not $Lite) { $Sha256 = $lock.snowluma.sha256 }
}
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

$existing = $null
if (Test-Path -LiteralPath $Destination) { $existing = Get-ChildItem -LiteralPath $Destination -Force | Select-Object -First 1 }
if ($existing -and -not $Upgrade) {
    Write-Host "目标目录已存在且非空: $Destination" -ForegroundColor Yellow
    throw '为避免覆盖已有安装，请先移动/删除该目录，换 -Destination，或用 -Upgrade 原地升级。'
}

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

# 校验：锁文件里的 sha256，以及 GitHub 给这个资产算的摘要（有就都对）
$actual = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$expected = @()
if ($Sha256) { $expected += $Sha256.ToLowerInvariant() }
if ($asset.digest -and $asset.digest -like 'sha256:*') { $expected += $asset.digest.Substring(7).ToLowerInvariant() }
foreach ($want in $expected) {
    if ($actual -ne $want) {
        Remove-Item -LiteralPath $tmpDir -Force -Recurse -ErrorAction SilentlyContinue
        throw "下载的文件 sha256 不对（应为 $want，实际 $actual），可能下载坏了或被篡改，没有安装"
    }
}
if ($expected) { Write-Host "sha256 校验通过：$actual" -ForegroundColor Green }
else { Write-Host "没有可对照的 sha256：$actual" -ForegroundColor Yellow }

$unpacked = Join-Path $tmpDir 'unpacked'
Write-Host '解压 ...' -ForegroundColor Cyan
Expand-Archive -LiteralPath $zipPath -DestinationPath $unpacked -Force

# 有些压缩包会多一层顶层目录，拍平
$children = @(Get-ChildItem -LiteralPath $unpacked -Force)
if ($children.Count -eq 1 -and $children[0].PSIsContainer -and
    (Test-Path -LiteralPath (Join-Path $children[0].FullName 'index.mjs'))) {
    $unpacked = $children[0].FullName
}
if (-not (Test-Path -LiteralPath (Join-Path $unpacked 'index.mjs'))) {
    throw "压缩包里没有 index.mjs，结构不对: $zipPath"
}

function Get-PackageEntries([string]$Dir) {
    # 发行包自己的文件：release.json 的 entries，加上 release.json 和自带的 node.exe
    $file = Join-Path $Dir 'release.json'
    $names = @('release.json', 'node.exe')
    if (Test-Path -LiteralPath $file) {
        $names += @((Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json).entries)
    }
    return $names | Select-Object -Unique
}

if ($existing) {
    $oldInfo = Join-Path $Destination 'release.json'
    $oldVersion = if (Test-Path -LiteralPath $oldInfo) { (Get-Content -LiteralPath $oldInfo -Raw -Encoding UTF8 | ConvertFrom-Json).version } else { 'unknown' }
    $backup = "$Destination.bak-$oldVersion"
    if (Test-Path -LiteralPath $backup) { $backup = "$backup-" + (Get-Date -Format 'yyyyMMddHHmmss') }
    Write-Host "原地升级 $oldVersion → $($release.tag_name)，被替换的旧文件放到 $backup" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    $oldEntries = Get-PackageEntries $Destination
    $newEntries = Get-PackageEntries $unpacked
    foreach ($name in ($oldEntries + $newEntries | Select-Object -Unique)) {
        $old = Join-Path $Destination $name
        if (Test-Path -LiteralPath $old) { Move-Item -LiteralPath $old -Destination (Join-Path $backup $name) }
    }
    foreach ($name in $newEntries) {
        $new = Join-Path $unpacked $name
        if (Test-Path -LiteralPath $new) { Move-Item -LiteralPath $new -Destination (Join-Path $Destination $name) }
    }
} else {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -LiteralPath $unpacked -Force | Move-Item -Destination $Destination
}

Remove-Item -LiteralPath $tmpDir -Force -Recurse -ErrorAction SilentlyContinue

$entry = Join-Path $Destination 'index.mjs'
if (-not (Test-Path -LiteralPath $entry)) {
    throw "安装后未找到 index.mjs，请检查: $Destination"
}

Write-Host ''
if ($existing) {
    Write-Host "已升级到 $($release.tag_name)（config、日志、登录状态没动）。" -ForegroundColor Green
    return
}
Write-Host '安装完成。下一步:' -ForegroundColor Green
Write-Host '  1) 双击仓库根目录的「一键启动.cmd」（或 .\scripts\启动全部.ps1）'
Write-Host '  2) 浏览器打开 http://127.0.0.1:5099/ ，初始密码在 bot\persona.env 的 SNOWLUMA_WEBUI_PASSWORD'
Write-Host '  3) 确认 QQ 已注入、账号在线'
Write-Host ''
if (-not $Lite) {
    Write-Host '（完整版自带 Node.js，无需另装）' -ForegroundColor DarkGray
} else {
    Write-Host '提示: Lite 包需要 Node 24，运行 node -v 检查版本。' -ForegroundColor Yellow
}
