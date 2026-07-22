param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\AgomQmtAgent",
    [switch]$StartTask
)

$ErrorActionPreference = "Stop"
$ResolvedInstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
$SecretsRoot = Join-Path $ResolvedInstallRoot "secrets"
New-Item -ItemType Directory -Force -Path $SecretsRoot | Out-Null
$SecureToken = Read-Host "Paste the one-time Agent token" -AsSecureString
$EncryptedToken = $SecureToken | ConvertFrom-SecureString
if (-not $EncryptedToken) {
    throw "The Agent token cannot be empty."
}
$SecretPath = Join-Path $SecretsRoot "agent-token.dpapi"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($SecretPath, $EncryptedToken, $Utf8NoBom)
$CurrentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $SecretsRoot /inheritance:r /grant:r "${CurrentIdentity}:(OI)(CI)F" "SYSTEM:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restrict the Agent secret directory ACL."
}
Write-Host "The Agent token was encrypted with Windows DPAPI for the current user."
if ($StartTask) {
    if (-not (Get-ScheduledTask -TaskName "AgomQmtAgent" -ErrorAction SilentlyContinue)) {
        throw "The AgomQmtAgent scheduled task does not exist. Install with -RegisterTask first."
    }
    Start-ScheduledTask -TaskName "AgomQmtAgent"
    Write-Host "The AgomQmtAgent scheduled task was started."
}
