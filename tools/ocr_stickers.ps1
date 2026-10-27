# 用 Windows 自带 OCR 给表情包识别文字（PS 5.1 / WinRT）
# 用法: powershell.exe -NoProfile -ExecutionPolicy Bypass -File ocr_stickers.ps1 -Dir <ori目录> -Out <jsonl>
param(
    [Parameter(Mandatory = $true)][string]$Dir,
    [Parameter(Mandatory = $true)][string]$Out
)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { throw '系统 OCR 引擎不可用（可能缺中文语言包）' }

$files = Get-ChildItem -LiteralPath $Dir -File | Where-Object { $_.Extension -match '^\.(jpg|jpeg|png|gif|bmp|webp)$' }
$total = $files.Count
$i = 0

$sw = [IO.StreamWriter]::new($Out, $false, [Text.UTF8Encoding]::new($false))
try {
    foreach ($f in $files) {
        $i++
        $text = ''
        try {
            $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($f.FullName)) ([Windows.Storage.StorageFile])
            $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
            $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
            $res = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            # OCR 中文会按字分隔，去掉多余空格
            $text = ($res.Text -replace '\s+', '')
            $stream.Dispose()
        } catch {
            $text = ''
        }

        $obj = [ordered]@{ file = $f.Name; text = $text }
        $sw.WriteLine(($obj | ConvertTo-Json -Compress))
        if ($i % 50 -eq 0) { Write-Host "  OCR $i/$total ..." }
    }
} finally {
    $sw.Dispose()
}
Write-Host "OCR 完成: $total 张 -> $Out"
