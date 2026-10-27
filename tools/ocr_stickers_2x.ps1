# Windows OCR（2 倍放大），给表情包识别文字
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
[Windows.Graphics.Imaging.BitmapTransform, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { throw '系统 OCR 引擎不可用' }

$files = Get-ChildItem -LiteralPath $Dir -File | Where-Object { $_.Extension -match '^\.(jpg|jpeg|png|gif|bmp|webp)$' }
$total = $files.Count
$i = 0
$withText = 0

$sw = [IO.StreamWriter]::new($Out, $false, [Text.UTF8Encoding]::new($false))
try {
    foreach ($f in $files) {
        $i++
        $text = ''
        try {
            $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($f.FullName)) ([Windows.Storage.StorageFile])
            $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
            $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])

            $tf = [Windows.Graphics.Imaging.BitmapTransform]::new()
            $tf.ScaledWidth = [uint32]([Math]::Max($decoder.PixelWidth * 2, 320))
            $tf.ScaledHeight = [uint32]([Math]::Max($decoder.PixelHeight * 2, 320))

            $bmp = Await ($decoder.GetSoftwareBitmapAsync(
                    [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
                    [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
                    $tf,
                    [Windows.Graphics.Imaging.ExifOrientationMode]::RespectExifOrientation,
                    [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])

            $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
            $text = ($res.Text -replace '\s+', '')
            $stream.Dispose()
        } catch {
            $text = ''
        }

        if ($text) { $withText++ }
        $obj = [ordered]@{ file = $f.Name; text = $text }
        $sw.WriteLine(($obj | ConvertTo-Json -Compress))
        if ($i % 50 -eq 0) { Write-Host "  OCR $i/$total (有文字 $withText) ..." }
    }
} finally {
    $sw.Dispose()
}
Write-Host "OCR 完成: $total 张，其中 $withText 张识别到文字 -> $Out"
