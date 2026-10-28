<#
.SYNOPSIS
    一键部署：装好运行环境、生成配置，可选直接启动。重复跑是安全的，已经装好的步骤会跳过。

.DESCRIPTION
    1. 检查 git、uv（没有 uv 就自动装）
    2. 旧机器（Z:\snowluma 那套）可沿用：拷 persona.env、聊天数据、表情原图，SnowLuma / 早柚核心 / tools 原地继续用
    3. bot\persona.env：没有就从样例生成，问几项必填的
    4. Python 3.12 虚拟环境 + 依赖（requirements.lock 锁定的版本），ffmpeg 放到 tools\ffmpeg\bin
    5. SnowLuma：没装就下载 external.lock.json 锁定的版本并校验 sha256；生成 onebot.json（随机 token），和 persona.env 的 token 对齐
    6. 早柚核心 + external.lock.json 里列的游戏插件，装锁定的提交，再装各插件自己的依赖
    已经装了的外部组件默认不动，只提示和锁定版本不一致；-Update 才把它们换到锁定版本（「一键更新.cmd」用）。
    最常用的是双击仓库根目录的「一键部署.cmd」（= 本脚本 -Start）。

.EXAMPLE
    .\scripts\setup.ps1                      # 装好、配好，不启动
    .\scripts\setup.ps1 -Start               # 装好后直接启动全部
    .\scripts\setup.ps1 -From Z:\snowluma    # 沿用旧安装
    .\scripts\setup.ps1 -NoCore              # 不装早柚核心
    .\scripts\setup.ps1 -Update              # SnowLuma / 核心 / 插件换到锁定版本（先停服务）
    .\scripts\setup.ps1 -Yes                 # 不提问，全部按默认（必填项留空的要自己去 persona.env 填）
#>
[CmdletBinding()]
param(
    [string]$From,
    [switch]$Start,
    [switch]$NoCore,
    [switch]$Update,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch { }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
. "$PSScriptRoot\common.ps1"
$root = $script:Root
$envFile = $script:EnvFile
$PythonVersion = '3.12'
$lock = Get-ExternalLock
# 早柚核心的游戏插件：锁文件 git 里除了核心本身的每一项
$CorePlugins = @($lock.git.PSObject.Properties.Name | Where-Object { $_ -ne 'gsuid_core' })
$CoreGames = ($CorePlugins | ForEach-Object { $lock.git.$_.game }) -join ' / '

function Step([string]$Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }
function Info([string]$Text) { Write-Host "   $Text" -ForegroundColor DarkGray }
function Ok([string]$Text) { Write-Host "   $Text" -ForegroundColor Green }
function Warn([string]$Text) { Write-Host "   $Text" -ForegroundColor Yellow }

function Ask([string]$Question, [string]$Default = '') {
    if ($Yes) { return $Default }
    $suffix = if ($Default) { "（回车 = $Default）" } else { '' }
    $answer = Read-Host "   $Question$suffix"
    if ($answer) { return $answer.Trim() }
    return $Default
}

function Confirm([string]$Question) {
    if ($Yes) { return $true }
    $answer = Read-Host "   $Question [Y/n]"
    return (-not $answer) -or ($answer -match '^[yY是]')
}

function New-Token {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

# 外部命令失败（退出码非 0）时抛错；PS 5.1 不会自己抛
function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$What) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What 失败（退出码 $LASTEXITCODE）" }
}

# uv 管理的 Python 解释器完整路径；没有就先下载。
# 用完整路径而不是「3.12」：个别机器上 uv 建「次版本号链接」会失败，用路径就绕开了；
# --system 免得在仓库目录里找到 .venv 自己
function Get-Python([string]$Version) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $found = & uv python find --system $Version 2>$null | Select-Object -First 1
        if (-not $found) {
            & uv python install $Version | Out-Host
            $found = & uv python find --system $Version 2>$null | Select-Object -First 1
        }
    } finally { $ErrorActionPreference = $old }
    if (-not $found -or -not (Test-Path -LiteralPath $found)) { throw "没装上 Python $Version（uv python install $Version 看报错）" }
    return $found
}

function Update-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user;$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin"
}

# 把一个 git 仓库放到锁定的提交：没有就浅克隆；有就只在 -Update 时切过去（有本地改动不动）
function Sync-GitRepo([string]$Name, [string]$Dir) {
    $want = $lock.git.$Name
    $short = $want.commit.Substring(0, 7)
    if (-not (Test-Path -LiteralPath (Join-Path $Dir '.git'))) {
        if ((Test-Path -LiteralPath $Dir) -and (Get-ChildItem -LiteralPath $Dir -Force | Select-Object -First 1)) {
            throw "$Dir 已存在但不是 git 仓库，挪开再跑"
        }
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        Invoke-Native git @('-C', $Dir, 'init', '-q') "初始化 $Name"
        Invoke-Native git @('-C', $Dir, 'remote', 'add', 'origin', $want.repo) "初始化 $Name"
        Invoke-Native git @('-C', $Dir, 'fetch', '-q', '--depth=1', 'origin', $want.commit) "下载 $Name"
        Invoke-Native git @('-C', $Dir, '-c', 'advice.detachedHead=false', 'checkout', '-q', 'FETCH_HEAD') "检出 $Name"
        Ok "$Name @ $short"
        return $true
    }
    $head = (& git -C $Dir rev-parse HEAD)
    if ($head -eq $want.commit) { Info "$Name 已是锁定版本 $short"; return $false }
    if (-not $Update) {
        Warn "$Name 现在是 $($head.Substring(0, 7))，锁定的是 $short；要换过去就双击「一键更新.cmd」"
        return $false
    }
    if (& git -C $Dir status --porcelain --untracked-files=no) {
        Warn "$Name 有本地改动，没更新（$Dir）"
        return $false
    }
    Invoke-Native git @('-C', $Dir, 'fetch', '-q', '--depth=1', $want.repo, $want.commit) "下载 $Name"
    # 锁文件说了算：revert 了更新 PR 再跑一键更新，就是退回旧版本
    $nowTime = [long](& git -C $Dir show -s --format=%ct HEAD)
    $wantTime = [long](& git -C $Dir show -s --format=%ct FETCH_HEAD)
    Invoke-Native git @('-C', $Dir, '-c', 'advice.detachedHead=false', 'checkout', '-q', 'FETCH_HEAD') "更新 $Name"
    $how = if ($wantTime -lt $nowTime) { '（锁定的比原来旧，按锁定版本退回）' } else { '' }
    Ok "$Name $($head.Substring(0, 7)) → $short$how"
    return $true
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, $script:Utf8NoBom)
}

Write-Host '=== 酱油鱼一键部署 ===' -ForegroundColor Cyan
Info "仓库：$root"

# ------------------------------------------------------------------ 1) 工具
Step '检查 git 和 uv'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw '没找到 git：先装 Git for Windows（https://git-scm.com/download/win），装完重新打开窗口再跑'
}
Ok "git：$((git --version) -join '')"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Warn '没找到 uv（管理 Python 的工具），现在自动安装 ...'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements | Out-Host
    }
    Update-Path
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        # 没有 winget 或装失败：用 uv 官方安装脚本（装到 %USERPROFILE%\.local\bin）
        powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex' | Out-Host
        Update-Path
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv 安装失败，手动装：https://docs.astral.sh/uv/getting-started/installation/' }
}
Ok "uv：$((uv --version) -join '')"

# ------------------------------------------------------------------ 2) 旧安装
$oldBotDir = $null
if (-not $From -and -not (Test-Path -LiteralPath $envFile) -and (Test-Path -LiteralPath 'Z:\snowluma\stack\nonebot\persona.env')) {
    Step '发现旧安装 Z:\snowluma'
    if (Confirm '沿用旧安装（配置、聊天数据、SnowLuma 登录状态、早柚核心都继续用）？') { $From = 'Z:\snowluma' }
}
if ($From) {
    Step "沿用旧安装 $From"
    if (-not (Test-Path -LiteralPath $From)) { throw "找不到 $From" }
    $oldBotDir = Join-Path $From 'stack\nonebot'
    $oldEnv = Join-Path $oldBotDir 'persona.env'
    if (Test-Path -LiteralPath $envFile) {
        Info 'bot\persona.env 已存在，不覆盖'
    } elseif (Test-Path -LiteralPath $oldEnv) {
        Copy-Item -LiteralPath $oldEnv -Destination $envFile
        Ok "拷了配置：$oldEnv"
    } else {
        Warn "旧安装里没有 $oldEnv，等下按新装处理"
    }
    $oldData = Join-Path $oldBotDir 'data'
    $newData = Join-Path $root 'bot\data'
    if ((Test-Path -LiteralPath $oldData) -and -not (Test-Path -LiteralPath $newData)) {
        Copy-Item -LiteralPath $oldData -Destination $newData -Recurse
        Ok '拷了聊天上下文、模式设置、用量记录（bot\data）'
    }
    $oldOri = Join-Path $From 'stickers\ori'
    $newOri = Join-Path $root 'stickers\ori'
    if ((Test-Path -LiteralPath $oldOri) -and -not (Test-Path -LiteralPath $newOri)) {
        Copy-Item -LiteralPath $oldOri -Destination $newOri -Recurse
        Ok '拷了表情原图（stickers\ori）'
    }
    # 大目录原地用，不搬：SnowLuma 里有 QQ 登录状态，核心里有群友的米游社凭据
    if (Test-Path -LiteralPath $envFile) {
        $cur = Read-EnvFile
        foreach ($pair in @(@('SNOWLUMA_DIR', 'SnowLuma'), @('GSCORE_DIR', 'gsuid_core'), @('TOOLS_DIR', 'tools'))) {
            $dir = Join-Path $From $pair[1]
            if (-not $cur[$pair[0]] -and (Test-Path -LiteralPath $dir)) {
                Set-EnvValue $pair[0] $dir
                Ok "$($pair[0]) = $dir（原地继续用）"
            }
        }
    }
}

# ------------------------------------------------------------------ 3) persona.env
Step '配置 bot\persona.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $root 'bot\persona.env.example') -Destination $envFile
    Ok '从 persona.env.example 生成了 persona.env'
}
# 样例里的占位号码当作没填
$placeholders = @('', '100000001', '100000002')
$cur = Read-EnvFile
$required = [ordered]@{
    LLM_API_KEY = 'DeepSeek（或其它 OpenAI 兼容接口）的 API Key'
    BOT_UIN     = '机器人的 QQ 号'
    DEV_UIN     = '你自己的 QQ 号（管理指令只认这个号）'
}
foreach ($key in $required.Keys) {
    if ($placeholders -notcontains [string]$cur[$key]) { continue }
    $value = Ask "填 $key（$($required[$key])）"
    if ($value) { Set-EnvValue $key $value; Ok "$key 已填" }
    else { Warn "$key 没填：之后打开 bot\persona.env 填上再启动" }
}
# 新加了游戏插件时，旧 persona.env 里写死的 GAME_CMD_PREFIXES 补上新前缀，否则人设会抢答新游戏的指令
$prefixLine = (Read-EnvFile)['GAME_CMD_PREFIXES']
if ($prefixLine) {
    $have = @($prefixLine.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $missing = @($CorePlugins | ForEach-Object { $lock.git.$_.prefixes } | Where-Object { $have -notcontains $_ } | Select-Object -Unique)
    if ($missing) {
        Set-EnvValue 'GAME_CMD_PREFIXES' (($have + $missing) -join ',')
        Ok ("人设避让的指令前缀补上了：{0}" -f ($missing -join '、'))
    }
}

# ------------------------------------------------------------------ 4) Python 环境
Step "NoneBot 的 Python $PythonVersion 环境和依赖"
$interp = Get-Python $PythonVersion
Info "Python：$interp"
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    Invoke-Native uv @('venv', (Join-Path $root '.venv'), '--python', $interp) '建虚拟环境'
}
# requirements.lock 是 CI 验证过的确切版本；requirements.txt 只写范围，给自动更新算新版本用
Invoke-Native uv @('pip', 'install', '--python', $py, '-r', (Join-Path $root 'requirements.lock')) '安装依赖'
Ok '依赖已装好'

$cfg = Get-StackConfig
$ffmpegExe = Join-Path $cfg.Ffmpeg 'ffmpeg.exe'
if (-not (Test-Path -LiteralPath $ffmpegExe)) {
    # 解析插件要 PATH 里有 ffmpeg；imageio-ffmpeg 自带一个静态版，拷过去改名，启动脚本会把这个目录加进 PATH
    $bundled = (& $py -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' | Select-Object -Last 1)
    if ($bundled -and (Test-Path -LiteralPath $bundled)) {
        New-Item -ItemType Directory -Force -Path $cfg.Ffmpeg | Out-Null
        Copy-Item -LiteralPath $bundled -Destination $ffmpegExe
        Ok "ffmpeg 放到了 $ffmpegExe"
    } else {
        Warn '没拿到 ffmpeg：B 站等视频解析可能失败'
    }
}

# ------------------------------------------------------------------ 5) SnowLuma
Step 'SnowLuma（QQ 协议端）'
$slDir = $cfg.SnowLuma
$slWant = $lock.snowluma.version
if (Test-Path -LiteralPath (Join-Path $slDir 'index.mjs')) {
    $slInfo = Join-Path $slDir 'release.json'
    $slNow = if (Test-Path -LiteralPath $slInfo) { 'v' + (Get-Content -LiteralPath $slInfo -Raw -Encoding UTF8 | ConvertFrom-Json).version } else { '未知版本' }
    if ($slNow -eq $slWant) {
        Info "已装 $slNow：$slDir"
    } elseif ($Update) {
        if (Test-Listening 5099) { throw 'SnowLuma 还在运行，先双击「一键停止.cmd」再更新' }
        & "$PSScriptRoot\install-snowluma.ps1" -Destination $slDir -Upgrade
    } else {
        Warn "SnowLuma 现在是 $slNow，锁定的是 $slWant；要换过去就双击「一键更新.cmd」"
    }
} else {
    & "$PSScriptRoot\install-snowluma.ps1" -Destination $slDir
}
$slConf = Join-Path $slDir 'config'
New-Item -ItemType Directory -Force -Path $slConf | Out-Null
$onebot = Join-Path $slConf 'onebot.json'
$cur = Read-EnvFile
if (-not (Test-Path -LiteralPath $onebot)) {
    $token = if ($cur['ONEBOT_ACCESS_TOKEN']) { $cur['ONEBOT_ACCESS_TOKEN'] } else { New-Token }
    $text = [IO.File]::ReadAllText((Join-Path $root 'config\onebot.reverse-ws.json'), [Text.Encoding]::UTF8)
    $text = $text.Replace('REPLACE_WITH_32_BYTES_RANDOM_HTTP_TOKEN', (New-Token))
    $text = $text.Replace('REPLACE_WITH_32_BYTES_RANDOM_WS_TOKEN', (New-Token))
    $text = $text.Replace('REPLACE_WITH_32_BYTES_RANDOM_NONEBOT_TOKEN', $token)
    Write-Utf8NoBom $onebot $text
    Set-EnvValue 'ONEBOT_ACCESS_TOKEN' $token
    Ok '生成了 SnowLuma config\onebot.json（只听 127.0.0.1，随机 token），token 已写进 persona.env'
} else {
    # 已有配置：以 SnowLuma 那边连 NoneBot 的 token 为准
    $json = Get-Content -LiteralPath $onebot -Raw -Encoding UTF8 | ConvertFrom-Json
    $client = @($json.networks.wsClients) | Where-Object { $_.url -like '*:18080/*' } | Select-Object -First 1
    if (-not $client) {
        Warn "onebot.json 里没有连 ws://127.0.0.1:18080/onebot/v11/ws 的 wsClients，要在 WebUI 的网络配置里加一个（token 填 persona.env 的 ONEBOT_ACCESS_TOKEN）"
    } elseif ($client.accessToken -ne $cur['ONEBOT_ACCESS_TOKEN']) {
        Set-EnvValue 'ONEBOT_ACCESS_TOKEN' ([string]$client.accessToken)
        Ok 'persona.env 的 ONEBOT_ACCESS_TOKEN 已和 SnowLuma 对齐'
    } else {
        Info 'token 已一致'
    }
    $mainToken = (Read-EnvFile)['ONEBOT_ACCESS_TOKEN']
    foreach ($f in Get-ChildItem -LiteralPath $slConf -Filter 'onebot_*.json' -ErrorAction SilentlyContinue) {
        $acc = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $c = @($acc.networks.wsClients) | Where-Object { $_.url -like '*:18080/*' } | Select-Object -First 1
        if ($c -and $c.accessToken -ne $mainToken) { Warn "$($f.Name) 里连 NoneBot 的 token 和 persona.env 不一致，在 WebUI 里改成一样的" }
    }
}
$runtime = Join-Path $slConf 'runtime.json'
if (-not (Test-Path -LiteralPath $runtime)) { Copy-Item -LiteralPath (Join-Path $root 'config\runtime.json') -Destination $runtime }
$firstRun = -not (Test-Path -LiteralPath (Join-Path $slConf 'webui.json'))
if ($firstRun -and -not (Read-EnvFile)['SNOWLUMA_WEBUI_PASSWORD']) {
    Set-EnvValue 'SNOWLUMA_WEBUI_PASSWORD' ((New-Token).Substring(0, 16))
    Ok 'WebUI 初始密码已生成，在 persona.env 的 SNOWLUMA_WEBUI_PASSWORD'
}

# ------------------------------------------------------------------ 6) 早柚核心
Step "早柚核心（$CoreGames 查询）"
$coreDir = $cfg.Core
if ($NoCore) {
    Info '跳过（-NoCore）'
} else {
    if ($Update -and (Test-Listening 8765)) { throw '早柚核心还在运行，先双击「一键停止.cmd」再更新' }
    [void](Sync-GitRepo 'gsuid_core' $coreDir)
    # plugins 目录核心第一次启动才建，先建好
    $pluginDir = Join-Path $coreDir 'gsuid_core\plugins'
    New-Item -ItemType Directory -Force -Path $pluginDir | Out-Null
    foreach ($name in $CorePlugins) { [void](Sync-GitRepo $name (Join-Path $pluginDir $name)) }
    # 本仓库自己的核心插件（gscore_plugins，自动签到等）：每次覆盖拷一遍
    foreach ($own in Get-ChildItem (Join-Path $root 'gscore_plugins') -Directory) {
        $dest = Join-Path $pluginDir $own.Name
        if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
        Copy-Item -LiteralPath $own.FullName -Destination $dest -Recurse
        Ok "本仓库插件 $($own.Name)"
    }
    Push-Location $coreDir
    try { Invoke-Native uv @('sync', '--python', $interp) '安装早柚核心依赖' } finally { Pop-Location }
    # 插件自己的依赖（比如鸣潮要 opencv）：核心只在用它的指令装插件时才装，我们是 git 拉的，要自己装；
    # 放在 uv sync 后面，sync 会删掉核心 lock 里没有的包
    $corePy = Join-Path $coreDir '.venv\Scripts\python.exe'
    foreach ($name in $CorePlugins) {
        $proj = Join-Path $pluginDir "$name\pyproject.toml"
        if (Test-Path -LiteralPath $proj) {
            Invoke-Native uv @('pip', 'install', '--python', $corePy, '-r', $proj) "安装 $name 的依赖"
        }
    }
    Ok '早柚核心已就绪'
}

# ------------------------------------------------------------------ 收尾
Step '部署完成'
$cur = Read-EnvFile
$missing = @($required.Keys | Where-Object { $placeholders -contains [string]$cur[$_] })
if ($missing) { Warn ("persona.env 还缺：{0}，填好再启动" -f ($missing -join '、')) }
if ($firstRun) {
    Write-Host ''
    Write-Host '   第一次用 SnowLuma 还要手动做两件事（只做一次）：' -ForegroundColor Yellow
    Write-Host "   1. 启动后浏览器打开 http://127.0.0.1:5099/ ，用初始密码 $($cur['SNOWLUMA_WEBUI_PASSWORD']) 登录，改密码、同意协议" -ForegroundColor Yellow
    Write-Host '   2. 电脑上的 QQ 登录机器人号，回到 WebUI 确认账号已注入、在线' -ForegroundColor Yellow
}
if (-not $NoCore) {
    Info '早柚核心的控制台设置（主人账号、扫码登陆设 DIRECT）见 docs\早柚核心接入.md 第三节'
}
if ($oldBotDir) {
    Info '旧日记补会话标签：.venv\Scripts\python tools\migrate_journal_tags.py（先预览，确认后加 --apply）'
}

if ($Start) {
    if ($missing) { Warn '必填项没填，先不启动'; exit 1 }
    Step '启动'
    # 旧目录里起的服务会占着端口，先停掉再用新的起
    & "$PSScriptRoot\stop-all.ps1"
    & "$PSScriptRoot\start-all-here.ps1"
} else {
    Info '启动：双击「一键启动.cmd」，或 .\scripts\启动全部.ps1'
}
