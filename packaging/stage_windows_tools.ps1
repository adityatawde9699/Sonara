param(
  [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$popplerVersion = "26.07.0-0"
$popplerUrl = "https://github.com/oschwartz10612/poppler-windows/releases/download/v$popplerVersion/Release-$popplerVersion.zip"
$popplerSha256 = "A711B0563B06EDC488583D28198B6734C5A494AFBBD1B9D87D3D2866062FB7E2"
$tesseractVersion = "5.5.3.20260724"
$minimumTesseractVersion = [version]"5.5.4"
$tesseractUrl = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-$tesseractVersion.exe"
$tesseractSha256 = "BEE9E3434BD94FD65387D9BE28CD467A41F61B1275383B55B0F59A1331270AE4"
$downloadDirectory = Join-Path $env:RUNNER_TEMP "sonara-native-tools"
$popplerZip = Join-Path $downloadDirectory "poppler.zip"
$tesseractInstaller = Join-Path $downloadDirectory "tesseract-setup.exe"
$popplerExtract = Join-Path $downloadDirectory "poppler"
$tesseractRoot = Join-Path $env:ProgramFiles "Tesseract-OCR"
$binDirectory = Join-Path $OutputDirectory "bin"
$shareDirectory = Join-Path $OutputDirectory "share"
$tessdataDirectory = Join-Path $OutputDirectory "tessdata"
$licenseDirectory = Join-Path $OutputDirectory "licenses"

New-Item -ItemType Directory -Force -Path $downloadDirectory, $OutputDirectory, $binDirectory, $shareDirectory, $tessdataDirectory, $licenseDirectory | Out-Null

if ([version]($tesseractVersion -replace "^(\d+\.\d+\.\d+).*", '$1') -lt $minimumTesseractVersion) {
  throw "Pinned Windows Tesseract $tesseractVersion is below the security floor $minimumTesseractVersion. Update the verified Windows binary and checksum before packaging."
}

Invoke-WebRequest -Uri $popplerUrl -OutFile $popplerZip
if ((Get-FileHash $popplerZip -Algorithm SHA256).Hash -ne $popplerSha256) { throw "Poppler archive SHA-256 mismatch." }
Expand-Archive -Path $popplerZip -DestinationPath $popplerExtract -Force
$popplerLibrary = Get-ChildItem $popplerExtract -Directory -Recurse | Where-Object { $_.Name -eq "Library" } | Select-Object -First 1
if (-not $popplerLibrary) { throw "Poppler archive did not contain its Library directory." }
$popplerBin = Join-Path $popplerLibrary.FullName "bin"
foreach ($name in @("pdftotext.exe", "pdftoppm.exe")) {
  $source = Join-Path $popplerBin $name
  if (-not (Test-Path $source)) { throw "Poppler archive is missing $name." }
  Copy-Item $source $binDirectory
}
Copy-Item (Join-Path $popplerBin "*.dll") $binDirectory -Force
$popplerData = Join-Path $popplerLibrary.FullName "share\poppler"
if (Test-Path $popplerData) { Copy-Item $popplerData $shareDirectory -Recurse -Force }
$popplerLicenses = Get-ChildItem $popplerExtract -File -Recurse | Where-Object { $_.Name -match "^(COPYING|LICENSE)(\..*)?$" }
foreach ($license in $popplerLicenses) {
  $destination = "poppler-$($license.Directory.Name)-$($license.Name)"
  Copy-Item $license.FullName (Join-Path $licenseDirectory $destination)
}

Invoke-WebRequest -Uri $tesseractUrl -OutFile $tesseractInstaller
if ((Get-FileHash $tesseractInstaller -Algorithm SHA256).Hash -ne $tesseractSha256) { throw "Tesseract installer SHA-256 mismatch." }
$process = Start-Process -FilePath $tesseractInstaller -ArgumentList "/S" -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Tesseract installer failed with exit code $($process.ExitCode)." }
Copy-Item (Join-Path $tesseractRoot "tesseract.exe") $binDirectory
Copy-Item (Join-Path $tesseractRoot "*.dll") $binDirectory -Force
Copy-Item (Join-Path $tesseractRoot "tessdata\eng.traineddata") $tessdataDirectory
foreach ($directory in @("configs", "tessconfigs")) {
  $source = Join-Path $tesseractRoot "tessdata\$directory"
  if (Test-Path $source) { Copy-Item $source $tessdataDirectory -Recurse -Force }
}
$tesseractLicense = Join-Path $tesseractRoot "LICENSE"
if (Test-Path $tesseractLicense) { Copy-Item $tesseractLicense (Join-Path $licenseDirectory "tesseract-LICENSE") }
