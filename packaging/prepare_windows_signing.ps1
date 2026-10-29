$ErrorActionPreference = "Stop"

if (-not $env:SONARA_WINDOWS_PFX_BASE64 -or -not $env:SONARA_WINDOWS_PFX_PASSWORD) {
  Write-Output "Windows signing secrets are absent; this native build will be unsigned and cannot pass the publish gate."
  "SONARA_WINDOWS_SIGNING_CONFIGURED=false" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
  exit 0
}

$certificatePath = Join-Path $env:RUNNER_TEMP "sonara-signing-certificate.pfx"
[IO.File]::WriteAllBytes($certificatePath, [Convert]::FromBase64String($env:SONARA_WINDOWS_PFX_BASE64))
$password = ConvertTo-SecureString $env:SONARA_WINDOWS_PFX_PASSWORD -AsPlainText -Force
$certificate = Import-PfxCertificate -FilePath $certificatePath -CertStoreLocation Cert:\CurrentUser\My -Password $password
if (-not $certificate -or -not $certificate.HasPrivateKey) { throw "The Windows signing certificate has no private key." }

$signTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse |
  Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
  Sort-Object FullName -Descending |
  Select-Object -First 1
if (-not $signTool) { throw "Windows SDK signtool.exe was not found on the runner." }

$stagedTools = "packaging/staging/sonara/tools/bin"
$executables = @("packaging/staging/sonara/sonara-runtime.exe") +
  @(Get-ChildItem $stagedTools -Filter "*.exe" -File | ForEach-Object { $_.FullName })
foreach ($executable in $executables) {
  if (-not (Test-Path $executable)) { throw "Expected staged executable is missing: $executable" }
  & $signTool.FullName sign /fd SHA256 /f $certificatePath /p $env:SONARA_WINDOWS_PFX_PASSWORD /tr "http://timestamp.digicert.com" /td SHA256 $executable
  if ($LASTEXITCODE -ne 0) { throw "signtool failed to sign $executable with exit code $LASTEXITCODE." }
  & $signTool.FullName verify /pa /all $executable
  if ($LASTEXITCODE -ne 0) { throw "signtool could not verify $executable." }
}

$configPath = "src-tauri/tauri.conf.json"
$config = Get-Content $configPath -Raw | ConvertFrom-Json -AsHashtable
$config.bundle.windows = @{
  certificateThumbprint = $certificate.Thumbprint
  digestAlgorithm = "sha256"
  timestampUrl = "http://timestamp.digicert.com"
}
$config | ConvertTo-Json -Depth 100 | Set-Content $configPath -Encoding utf8
"SONARA_WINDOWS_SIGNING_CONFIGURED=true" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
Write-Output "Imported Windows code-signing identity $($certificate.Thumbprint)."
