param(
  [Parameter(Mandatory = $true)][string]$Installer
)

$ErrorActionPreference = "Stop"
$installDirectory = Join-Path $env:RUNNER_TEMP "Sonara-clean-install"
$userDataDirectory = Join-Path $env:LOCALAPPDATA "com.sonara.reader"
$sentinel = Join-Path $userDataDirectory "uninstall-preservation-check.txt"
New-Item -ItemType Directory -Force -Path $userDataDirectory | Out-Null
Set-Content -Path $sentinel -Value "Keep this user data during uninstall."

$installerPath = (Resolve-Path $Installer).Path
$signature = Get-AuthenticodeSignature $installerPath
if ($signature.Status -ne "Valid") { throw "Windows installer signature is not valid: $($signature.Status)." }
$install = Start-Process -FilePath $installerPath -ArgumentList "/S /D=$installDirectory" -Wait -PassThru
if ($install.ExitCode -ne 0) { throw "Windows installer returned $($install.ExitCode)." }

$app = Get-ChildItem $installDirectory -Filter "sonara-desktop.exe" -File -Recurse | Select-Object -First 1
$runtime = Get-ChildItem $installDirectory -Filter "sonara-runtime.exe" -File -Recurse | Select-Object -First 1
$tools = Get-ChildItem $installDirectory -Directory -Recurse | Where-Object { $_.Name -eq "tools" -and (Test-Path (Join-Path $_.FullName "bin\tesseract.exe")) } | Select-Object -First 1
if (-not $app -or -not $runtime -or -not $tools) { throw "The installed application is missing its executable, runtime, or PDF/OCR tools." }
if ((Get-AuthenticodeSignature $app.FullName).Status -ne "Valid") { throw "Installed Sonara executable is not signed." }
if ((Get-AuthenticodeSignature $runtime.FullName).Status -ne "Valid") { throw "Bundled Python runtime is not signed." }
foreach ($name in @("pdftotext.exe", "pdftoppm.exe", "tesseract.exe")) {
  $tool = Join-Path $tools.FullName "bin\$name"
  if ((Get-AuthenticodeSignature $tool).Status -ne "Valid") { throw "Bundled native tool $name is not signed." }
}

$smoke = Start-Process -FilePath $app.FullName -ArgumentList "--sonara-smoke-check" -Wait -PassThru
if ($smoke.ExitCode -ne 0) { throw "Installed app resource smoke check failed with exit code $($smoke.ExitCode)." }
$env:PATH = "$($tools.FullName)\bin;$env:PATH"
$env:TESSDATA_PREFIX = Join-Path $tools.FullName "tessdata"
$env:POPPLER_DATADIR = Join-Path $tools.FullName "share\poppler"
& (Join-Path $tools.FullName "bin\pdftotext.exe") -v
if ($LASTEXITCODE -ne 0) { throw "Installed Poppler pdftotext failed with exit code $LASTEXITCODE." }
& (Join-Path $tools.FullName "bin\pdftoppm.exe") -v
if ($LASTEXITCODE -ne 0) { throw "Installed Poppler pdftoppm failed with exit code $LASTEXITCODE." }
$languages = & (Join-Path $tools.FullName "bin\tesseract.exe") --list-langs
if ($LASTEXITCODE -ne 0 -or $languages -notcontains "eng") { throw "Installed Tesseract or English model failed its startup check." }

$uninstaller = Get-ChildItem $installDirectory -Filter "uninstall.exe" -File -Recurse | Select-Object -First 1
if (-not $uninstaller) { throw "Installed NSIS uninstaller was not found." }
$remove = Start-Process -FilePath $uninstaller.FullName -ArgumentList "/S" -Wait -PassThru
if ($remove.ExitCode -ne 0) { throw "Windows uninstaller returned $($remove.ExitCode)." }
if (-not (Test-Path $sentinel)) { throw "Uninstall unexpectedly removed Sonara user data." }
Write-Output "Windows clean install, resource discovery, PDF/OCR, code-signature, and uninstall-data checks passed."
