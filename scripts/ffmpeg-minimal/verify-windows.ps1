param(
  [string]$RuntimeDir = "client/src-tauri/resources/ffmpeg"
)

$ErrorActionPreference = "Stop"
$ffmpeg = Join-Path $RuntimeDir "ffmpeg.exe"
$ffprobe = Join-Path $RuntimeDir "ffprobe.exe"
$font = Join-Path $RuntimeDir "NotoSansSC-Regular.otf"
$licenses = @(
  (Join-Path $RuntimeDir "FFmpeg-LGPLv3.txt"),
  (Join-Path $RuntimeDir "NotoSansSC-OFL-1.1.txt")
)

@($ffmpeg, $ffprobe, $font) + $licenses | ForEach-Object {
  if (-not (Test-Path -LiteralPath $_ -PathType Leaf)) {
    throw "required runtime file is missing: $_"
  }
}

$buildConfig = (& $ffmpeg -hide_banner -buildconf 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw "ffmpeg -buildconf failed" }
foreach ($forbidden in @("--enable-gpl", "--enable-nonfree", "libx264", "libx265", "openh264")) {
  if ($buildConfig.ToLowerInvariant().Contains($forbidden)) {
    throw "forbidden FFmpeg build option detected: $forbidden"
  }
}

$encoders = (& $ffmpeg -hide_banner -encoders 2>&1 | Out-String)
$decoders = (& $ffmpeg -hide_banner -decoders 2>&1 | Out-String)
$filters = (& $ffmpeg -hide_banner -filters 2>&1 | Out-String)
foreach ($required in @("h264_mf", " aac ", " png ")) {
  if (-not $encoders.Contains($required)) { throw "required encoder is missing: $required" }
}
foreach ($required in @(" h264 ", " hevc ", " aac ", " png ")) {
  if (-not $decoders.Contains($required)) { throw "required decoder is missing: $required" }
}
foreach ($required in @(" overlay ", " scale ", " format ")) {
  if (-not $filters.Contains($required)) { throw "required filter is missing: $required" }
}

$fontHash = (Get-FileHash -LiteralPath $font -Algorithm SHA256).Hash.ToLowerInvariant()
if ($fontHash -ne "faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9") {
  throw "NotoSansSC-Regular.otf SHA256 mismatch"
}

Write-Host "Windows media runtime verification passed."
