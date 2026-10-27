<#
.SYNOPSIS
    停止整套栈（只杀 Z:\snowluma 下的进程，不碰你的 QQ 和其他程序）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Z:\snowluma\scripts\stop-all.ps1
#>
[CmdletBinding()]
param(
    [int[]]$Ports = @(18080, 8765, 5099, 3000, 3001)
)

$ErrorActionPreference = 'Stop'
$root = 'Z:\snowluma'

$targets = @{}

# 1) 按端口找
foreach ($port in $Ports) {
    foreach ($conn in (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) {
        $ownerId = [int]$conn.OwningProcess
        $proc = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
        if ($proc -and $proc.Path -and $proc.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
            $targets[$ownerId] = $proc
        }
    }
}

# 2) 按可执行文件路径兜底（端口还没起来或已被换绑的情况）
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object {
        $proc = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
        if ($proc) { $targets[[int]$_.ProcessId] = $proc }
    }

# 3) 早柚核心由 uv 拉起，真正占端口的 python 可能在 uv 自己的目录里（不在 $root 下），按命令行认
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessId -ne $PID -and $_.Name -match '^(python|pythonw|uv)\.exe$' -and $_.CommandLine -like "*$(Join-Path $root 'gsuid_core')*" } |
    ForEach-Object {
        $proc = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
        if ($proc) { $targets[[int]$_.ProcessId] = $proc }
    }

if ($targets.Count -eq 0) {
    Write-Host '没有在 Z:\snowluma 下运行的服务需要停止。' -ForegroundColor DarkGray
    exit 0
}

foreach ($procId in @($targets.Keys)) {
    $proc = $targets[$procId]
    Write-Host ("停止 {0} (pid {1})" -f $proc.ProcessName, $procId) -ForegroundColor Yellow
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2
$left = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $Ports }
if ($left) {
    Write-Warning ("仍有端口在监听: {0}" -f (($left.LocalPort | Sort-Object -Unique) -join ', '))
} else {
    Write-Host '已全部停止。' -ForegroundColor Green
}
