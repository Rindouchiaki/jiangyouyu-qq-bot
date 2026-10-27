# 各脚本共用（dot-source）：仓库根目录、bot\persona.env 读写、各运行目录。
# 运行目录默认都在仓库里，旧机器上已经装在别处的可以在 persona.env 里用 *_DIR 指过去。

$script:Root = Split-Path -Parent $PSScriptRoot
$script:EnvFile = Join-Path $script:Root 'bot\persona.env'
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Read-EnvFile([string]$Path = $script:EnvFile) {
    $map = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($line in [IO.File]::ReadAllLines($Path, [Text.Encoding]::UTF8)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#') -or $t.IndexOf('=') -lt 1) { continue }
        $k, $v = $t.Split('=', 2)
        $v = $v.Trim()
        if ($v.Length -ge 2 -and ($v[0] -eq '"' -or $v[0] -eq "'") -and $v[-1] -eq $v[0]) { $v = $v.Substring(1, $v.Length - 2) }
        $map[$k.Trim()] = $v
    }
    return $map
}

# 改一项（没有就追加）；UTF-8 无 BOM + CRLF：python-dotenv 读到 BOM 会把第一项的键名读坏
function Set-EnvValue([string]$Key, [string]$Value, [string]$Path = $script:EnvFile) {
    $lines = New-Object System.Collections.Generic.List[string]
    if (Test-Path -LiteralPath $Path) { $lines.AddRange([IO.File]::ReadAllLines($Path, [Text.Encoding]::UTF8)) }
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    $hit = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match $pattern) { $lines[$i] = "$Key=$Value"; $hit = $true; break }
    }
    if (-not $hit) { $lines.Add("$Key=$Value") }
    [IO.File]::WriteAllText($Path, (($lines -join "`r`n") + "`r`n"), $script:Utf8NoBom)
}

function Resolve-StackPath([string]$Value, [string]$Default) {
    if (-not $Value) { return $Default }
    $Value = [Environment]::ExpandEnvironmentVariables($Value)
    if ([IO.Path]::IsPathRooted($Value)) { return $Value }
    return [IO.Path]::GetFullPath((Join-Path $script:Root $Value))
}

function Get-StackConfig {
    $envMap = Read-EnvFile
    $tools = Resolve-StackPath $envMap['TOOLS_DIR'] (Join-Path $script:Root 'tools')
    [pscustomobject]@{
        Root     = $script:Root
        EnvFile  = $script:EnvFile
        Env      = $envMap
        Python   = Join-Path $script:Root '.venv\Scripts\python.exe'
        BotDir   = Join-Path $script:Root 'bot'
        Logs     = Resolve-StackPath $envMap['LOG_DIR'] (Join-Path $script:Root 'logs')
        SnowLuma = Resolve-StackPath $envMap['SNOWLUMA_DIR'] (Join-Path $script:Root 'SnowLuma')
        Core     = Resolve-StackPath $envMap['GSCORE_DIR'] (Join-Path $script:Root 'gsuid_core')
        Tools    = $tools
        Ffmpeg   = Join-Path $tools 'ffmpeg\bin'
        QQ       = Resolve-StackPath $envMap['QQ_EXE'] 'C:\Program Files\Tencent\QQNT\QQ.exe'
    }
}

# external.lock.json：SnowLuma、早柚核心和插件锁定的版本（CI 自动开 PR 更新）
function Get-ExternalLock {
    Get-Content -LiteralPath (Join-Path $script:Root 'external.lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-Listening([int]$Port) {
    [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Listening([int]$Port, [int]$Seconds = 45) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Test-Listening $Port) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}
