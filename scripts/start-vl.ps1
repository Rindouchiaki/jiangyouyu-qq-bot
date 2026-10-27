# 本地视觉模型（llama.cpp + Qwen3-VL-2B）——只在「无字照片」需要描述时用
# 启动后监听 127.0.0.1:11435，OpenAI 兼容接口 /v1/chat/completions
$ErrorActionPreference = 'Stop'

$root = 'Z:\snowluma'
$bin = Join-Path $root 'tools\llama.cpp\bin\llama-server.exe'
if (-not (Test-Path $bin)) { $bin = Join-Path $root 'tools\llama.cpp\llama-server.exe' }
$model = Join-Path $root 'tools\vl-model\Qwen3-VL-2B-Instruct-Q4_K_M.gguf'
$mmproj = Join-Path $root 'tools\vl-model\mmproj-F16.gguf'
$log = Join-Path $root 'logs\vl.log'

foreach ($p in @($bin, $model, $mmproj)) {
    if (-not (Test-Path $p)) { throw "找不到 $p，先跑 scripts\setup-vl.ps1" }
}

New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
Write-Host "本地视觉模型启动: http://127.0.0.1:11435  日志: $log" -ForegroundColor Cyan

# llama-server 往 stderr 打初始化日志，PS 会当成 NativeCommandError；
# 这里临时放宽，否则脚本会在启动瞬间因错误记录把自己（连带服务）弄死
$ErrorActionPreference = 'Continue'
& $bin -m $model --mmproj $mmproj --host 127.0.0.1 --port 11435 -c 8192 -ngl 0 --jinja *>&1 |
    Tee-Object -FilePath $log -Append
