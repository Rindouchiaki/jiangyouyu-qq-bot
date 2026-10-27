<#
.SYNOPSIS
    停止整套栈：只杀从仓库、SnowLuma、早柚核心、tools 目录里起来的进程（连同它们的子进程），
    外加占着 NoneBot 端口跑 bot.py 的 python，不碰你的 QQ 和其他程序。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\stop-all.ps1
#>
[CmdletBinding()]
param(
    [int]$NoneBotPort = 18080
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
$cfg = Get-StackConfig
$dirs = @($cfg.Root, $cfg.SnowLuma, $cfg.Core, $cfg.Tools) |
    Where-Object { $_ } |
    ForEach-Object { $_.TrimEnd('\') + '\' } |
    Select-Object -Unique

$all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
$targets = @{}

function Add-Tree([int]$ProcId) {
    if ($ProcId -eq $PID -or $targets.ContainsKey($ProcId)) { return }
    $targets[$ProcId] = $true
    # venv 的 python.exe、uv run 都会再拉起真正干活的子进程，一起带走
    foreach ($child in $all | Where-Object { $_.ParentProcessId -eq $ProcId }) { Add-Tree ([int]$child.ProcessId) }
}

# 1) 可执行文件在这些目录下的（NoneBot 的 venv、SnowLuma 的 node、核心的 venv、llama-server）
foreach ($proc in $all) {
    $exe = $proc.ExecutablePath
    if (-not $exe) { continue }
    foreach ($dir in $dirs) {
        if ($exe.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase)) { Add-Tree ([int]$proc.ProcessId); break }
    }
}

# 2) 占着 NoneBot 端口、命令行是 bot.py 的 python（旧目录布局里起的那份也算），连同拉起它的 venv 启动器
foreach ($conn in (Get-NetTCPConnection -State Listen -LocalPort $NoneBotPort -ErrorAction SilentlyContinue)) {
    $proc = $all | Where-Object { $_.ProcessId -eq $conn.OwningProcess } | Select-Object -First 1
    if ($proc -and $proc.Name -match '^pythonw?\.exe$' -and $proc.CommandLine -like '*bot.py*') {
        $parent = $all | Where-Object { $_.ProcessId -eq $proc.ParentProcessId -and $_.Name -match '^pythonw?\.exe$' } | Select-Object -First 1
        Add-Tree ([int]$(if ($parent) { $parent.ProcessId } else { $proc.ProcessId }))
    }
}

# QQ 本体不在这些目录里；万一有人把 QQ 装进了仓库，也别动它
foreach ($procId in @($targets.Keys)) {
    $proc = $all | Where-Object { $_.ProcessId -eq $procId } | Select-Object -First 1
    if ($proc -and $proc.Name -eq 'QQ.exe') { $targets.Remove($procId) }
}

if ($targets.Count -eq 0) {
    Write-Host '没有需要停止的服务。' -ForegroundColor DarkGray
    exit 0
}

foreach ($procId in @($targets.Keys)) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) { continue }
    Write-Host ("停止 {0} (pid {1})" -f $proc.ProcessName, $procId) -ForegroundColor Yellow
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2
$ports = @($NoneBotPort, 8765, 5099, 3000, 3001, 11435)
$left = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports }
if ($left) {
    Write-Warning ("仍有端口在监听: {0}（可能是别的程序，或者装在别处的服务，看 persona.env 的 *_DIR）" -f (($left.LocalPort | Sort-Object -Unique) -join ', '))
} else {
    Write-Host '已全部停止。' -ForegroundColor Green
}
