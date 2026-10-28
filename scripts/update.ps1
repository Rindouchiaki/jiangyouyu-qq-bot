<#
.SYNOPSIS
    一键更新：拉最新代码 → 停服务 → 依赖和外部组件换到锁定版本 → 重新启动。

.DESCRIPTION
    GitHub 上合并了「chore(deps)」自动更新 PR（或者别的改动）之后，双击仓库根目录的「一键更新.cmd」就行。
    SnowLuma 升级时被替换下来的旧文件在「SnowLuma.bak-旧版本」，核心和插件是 git 仓库，出问题都能退回去。
    bot\persona.env 会按样例重写：账号、密钥、路径和自己加的项保留，回复频率这类调参项换成样例里的新值，
    旧文件备份成 persona.env.bak-时间；自己要长期保留的调参写进 bot\persona.local.env。

.EXAMPLE
    .\scripts\update.ps1             # 拉代码 + 更新 + 重启
    .\scripts\update.ps1 -NoPull     # 不拉代码，只把依赖换到当前锁定版本
    .\scripts\update.ps1 -KeepEnv    # persona.env 不按样例重写（默认会把调参项换成样例的新值）
#>
[CmdletBinding()]
param(
    [switch]$NoPull,
    [switch]$KeepEnv
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new() } catch { }
. "$PSScriptRoot\common.ps1"
$root = $script:Root

Write-Host '=== 酱油鱼一键更新 ===' -ForegroundColor Cyan

if (-not $NoPull) {
    Write-Host ''
    Write-Host '== 拉最新代码' -ForegroundColor Cyan
    $dirty = & git -C $root status --porcelain --untracked-files=no
    if ($dirty) {
        Write-Host $dirty
        throw '仓库里有改过还没提交的文件（上面列的），先处理掉再更新（不想要就 git checkout -- 文件名）'
    }
    $before = (& git -C $root rev-parse HEAD)
    & git -C $root pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'git pull 失败：看上面的报错（本地有自己的提交时要先合并）' }
    $after = (& git -C $root rev-parse HEAD)
    if ($before -eq $after) {
        Write-Host '   代码已经是最新的' -ForegroundColor DarkGray
    } else {
        & git -C $root --no-pager log --oneline "$before..$after"
    }
}

Write-Host ''
Write-Host '== 停止服务' -ForegroundColor Cyan
& "$PSScriptRoot\stop-all.ps1"

# 用刚拉下来的 setup.ps1：装依赖、外部组件换到锁定版本，再启动
& "$PSScriptRoot\setup.ps1" -Update -Start -KeepEnv:$KeepEnv
exit $LASTEXITCODE
