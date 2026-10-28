# 各脚本共用（dot-source）：仓库根目录、bot\persona.env 读写（含一键更新时按样例重写）、各运行目录。
# 运行目录默认都在仓库里，旧机器上已经装在别处的可以在 persona.env 里用 *_DIR 指过去。

$script:Root = Split-Path -Parent $PSScriptRoot
$script:EnvFile = Join-Path $script:Root 'bot\persona.env'
# 自己长期要保留的调参写这里：bot.py 读完 persona.env 再读它（盖过同名项），一键更新不碰
$script:LocalEnvFile = Join-Path $script:Root 'bot\persona.local.env'
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Read-EnvFile([string]$Path = $script:EnvFile, [switch]$NoLocal) {
    $map = [ordered]@{}
    $paths = @($Path)
    # 读默认的 persona.env 时连 persona.local.env 一起读，和 bot.py 看到的一致
    if (-not $NoLocal -and $Path -eq $script:EnvFile) { $paths += $script:LocalEnvFile }
    foreach ($p in $paths) {
        if (-not (Test-Path -LiteralPath $p)) { continue }
        foreach ($line in [IO.File]::ReadAllLines($p, [Text.Encoding]::UTF8)) {
            $t = $line.Trim()
            if (-not $t -or $t.StartsWith('#') -or $t.IndexOf('=') -lt 1) { continue }
            $k, $v = $t.Split('=', 2)
            $v = $v.Trim()
            if ($v.Length -ge 2 -and ($v[0] -eq '"' -or $v[0] -eq "'") -and $v[-1] -eq $v[0]) { $v = $v.Substring(1, $v.Length - 2) }
            $map[$k.Trim()] = $v
        }
    }
    return $map
}

# 一键更新按样例重写 persona.env 时原样保留的项：账号、密钥、路径这些每台机器不一样的
$script:PersonalEnvKeys = @(
    'BOT_UIN', 'NICKNAMES', 'LLM_BASE_URL', 'LLM_MODEL', 'LLM_API_KEY',
    'GSUID_CORE_HOST', 'GSUID_CORE_PORT', 'GSUID_CORE_WS_TOKEN', 'BAISHOU_VAULT', 'GACHA_TEXT_FILE',
    'ONEBOT_ACCESS_TOKEN', 'SNOWLUMA_WEBUI_PASSWORD', 'SEARCH_API_KEY',
    'SNOWLUMA_DIR', 'GSCORE_DIR', 'TOOLS_DIR', 'STICKER_DIR', 'LOG_DIR', 'QQ_EXE'
)

function Format-EnvValue([string]$Value) {
    # 带 # 或首尾空格的要加引号，不然 dotenv 会截掉
    if ($Value -match '#' -or $Value -ne $Value.Trim()) { return '"' + $Value.Replace('"', '\"') + '"' }
    return $Value
}

# 一键更新用：按样例重写 persona.env。账号、密钥、路径（PersonalEnvKeys）照原样带过去，调参项换成样例里的值，
# 样例里没有的项原样放在最后。有变化才写，写之前备份成 persona.env.bak-时间。返回改了值的调参项说明。
function Sync-EnvFromExample(
    [string]$Path = $script:EnvFile,
    [string]$Example = (Join-Path $script:Root 'bot\persona.env.example')
) {
    $cur = Read-EnvFile $Path -NoLocal
    $out = New-Object System.Collections.Generic.List[string]
    $changed = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    foreach ($line in [IO.File]::ReadAllLines($Example, [Text.Encoding]::UTF8)) {
        $m = [regex]::Match($line, '^(\s*#\s*)?([A-Z][A-Z0-9_]*)=(.*)$')
        if (-not $m.Success) { $out.Add($line); continue }
        $key = $m.Groups[2].Value
        if ($m.Groups[1].Success) {
            # 样例里注释掉的路径项（# SNOWLUMA_DIR=...）：自己设过就写成生效的
            if ($cur.Contains($key) -and $script:PersonalEnvKeys -contains $key) {
                $out.Add("$key=$(Format-EnvValue $cur[$key])"); $seen[$key] = $true
            } else { $out.Add($line) }
            continue
        }
        $seen[$key] = $true
        $value = $m.Groups[3].Value
        if ($cur.Contains($key)) {
            if ($script:PersonalEnvKeys -contains $key) { $value = Format-EnvValue $cur[$key] }
            elseif ($cur[$key] -cne $value) { $changed.Add("$key：$($cur[$key]) → $value") }
        }
        $out.Add("$key=$value")
    }
    $extra = @($cur.Keys | Where-Object { -not $seen.ContainsKey($_) })
    if ($extra.Count) {
        $out.Add('')
        $out.Add('# ---- 样例里没有、自己加的配置（一键更新原样保留）----')
        foreach ($k in $extra) { $out.Add("$k=$(Format-EnvValue $cur[$k])") }
    }
    $text = ($out -join "`r`n") + "`r`n"
    $old = if (Test-Path -LiteralPath $Path) { [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) } else { '' }
    if ($text -cne $old) {
        if (Test-Path -LiteralPath $Path) { Copy-Item -LiteralPath $Path -Destination ("$Path.bak-" + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
        [IO.File]::WriteAllText($Path, $text, $script:Utf8NoBom)
    }
    return ,$changed
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
        # Ollama（白守的向量模型）：可执行文件和模型目录都能在 persona.env 里覆盖
        Ollama   = Resolve-StackPath $envMap['OLLAMA_EXE'] 'Z:\Ollama\ollama.exe'
        OllamaModels = if ($envMap['OLLAMA_MODELS']) { $envMap['OLLAMA_MODELS'] } else { 'Z:\Ollama\models' }
        # 本地视觉模型：和 vision.py 同一个开关（默认开、用 llama.cpp）；VLM_ENABLED=0 或改用 Ollama 就不拉起 llama.cpp
        VlEnabled = ("$($envMap['VLM_ENABLED'])".Trim() -notin @('0', 'false', 'False')) -and ("$(if ($envMap['VLM_PROVIDER']) { $envMap['VLM_PROVIDER'] } else { 'openai' })".Trim().ToLower() -eq 'openai')
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
