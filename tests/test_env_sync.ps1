# Sync-EnvFromExample（一键更新按样例重写 persona.env）的离线校验：临时目录里造样例和旧配置，看重写结果
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\..\scripts\common.ps1"

$tmp = Join-Path ([IO.Path]::GetTempPath()) ('envsync_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
$example = Join-Path $tmp 'persona.env.example'
$envPath = Join-Path $tmp 'persona.env'
$enc = New-Object System.Text.UTF8Encoding $false
[IO.File]::WriteAllText($example, ((@(
    '# 说明行原样保留', 'BOT_UIN=100000001', 'LLM_API_KEY=', '# 插话概率', 'REPLY_CHIME_PROB=0.02', 'NEW_KEY=5',
    '# SNOWLUMA_DIR=Z:\snowluma\SnowLuma', '# LOG_DIR=logs'
) -join "`r`n") + "`r`n"), $enc)
[IO.File]::WriteAllText($envPath, ((@(
    'BOT_UIN=123456', 'LLM_API_KEY=sk-abc#1', 'REPLY_CHIME_PROB=0.1', 'SNOWLUMA_DIR=D:\SnowLuma', 'VLM_ENABLED=1'
) -join "`r`n") + "`r`n"), $enc)

$script:failed = 0
function Check([bool]$Ok, [string]$Name) {
    if ($Ok) { Write-Host "PASS  $Name" } else { Write-Host "FAIL  $Name"; $script:failed++ }
}

$changed = Sync-EnvFromExample -Path $envPath -Example $example
$after = Read-EnvFile $envPath -NoLocal
Check ($after['BOT_UIN'] -eq '123456' -and $after['LLM_API_KEY'] -eq 'sk-abc#1') '账号和密钥原样保留（带 # 的加了引号）'
Check ($after['REPLY_CHIME_PROB'] -eq '0.02' -and $after['NEW_KEY'] -eq '5') '调参项换成样例的值，新项补上'
Check ($after['SNOWLUMA_DIR'] -eq 'D:\SnowLuma' -and -not $after.Contains('LOG_DIR')) '设过的路径写成生效的，没设的保持注释'
Check ($after['VLM_ENABLED'] -eq '1') '样例里没有的项原样保留'
Check ($changed.Count -eq 1 -and $changed[0] -like 'REPLY_CHIME_PROB*') '列出改了值的调参项'
Check (@(Get-ChildItem -LiteralPath $tmp -Filter 'persona.env.bak-*').Count -eq 1) '改之前先备份'
$text = [IO.File]::ReadAllText($envPath, [Text.Encoding]::UTF8)
Check ($text.Contains('# 说明行原样保留') -and $text.Contains('# 插话概率')) '样例里的说明行带过来了'
Check ([IO.File]::ReadAllBytes($envPath)[0] -ne 0xEF) '写出来没有 BOM（dotenv 读 BOM 会坏第一项）'

$again = Sync-EnvFromExample -Path $envPath -Example $example
Check ($again.Count -eq 0 -and @(Get-ChildItem -LiteralPath $tmp -Filter 'persona.env.bak-*').Count -eq 1) '再跑一次没变化就不写、不备份'

Remove-Item -LiteralPath $tmp -Recurse -Force
if ($script:failed) { Write-Host "`n结果: $($script:failed) 项失败"; exit 1 }
Write-Host "`n结果: 全部通过"
