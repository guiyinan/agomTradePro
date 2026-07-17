<#
.SYNOPSIS
    Create a verified PostgreSQL backup on the AgomTradePro VPS and download it.
.DESCRIPTION
    Reads the VPS connection from AGOM_VPS_HOST, AGOM_VPS_USER,
    AGOM_VPS_PASS, and AGOM_VPS_PORT. The password is never written to disk.
    The remote custom-format dump is checked with pg_restore --list, downloaded
    over SFTP, and verified locally with SHA-256.
.EXAMPLE
    .\scripts\backup-vps-postgres.ps1
.EXAMPLE
    .\scripts\backup-vps-postgres.ps1 -DownloadLatest
.EXAMPLE
    .\scripts\backup-vps-postgres.ps1 -OutputDir D:\Backups\AgomTradePro
#>
[CmdletBinding()]
param(
    [string]$OutputDir,
    [string]$RemoteBackupDir,
    [switch]$DownloadLatest,
    [ValidateRange(0, 3650)]
    [int]$PruneRemoteOlderThanDays = 0,
    [ValidateRange(30, 86400)]
    [int]$TimeoutSeconds = 900
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\shared\common.ps1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VpsHost = $env:AGOM_VPS_HOST
$VpsUser = if ($env:AGOM_VPS_USER) { $env:AGOM_VPS_USER } else { 'root' }
$VpsPass = $env:AGOM_VPS_PASS
$VpsPort = if ($env:AGOM_VPS_PORT) { [int]$env:AGOM_VPS_PORT } else { 22 }
$TargetDir = if ($env:AGOM_VPS_TARGET_DIR) { $env:AGOM_VPS_TARGET_DIR.TrimEnd('/') } else { '/opt/agomtradepro' }

if (-not $VpsHost) {
    Throw-Err 'AGOM_VPS_HOST is required.'
}
if (-not $VpsPass) {
    Throw-Err 'AGOM_VPS_PASS is required.'
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $ProjectRoot 'backups\vps-postgres'
}
if (-not $RemoteBackupDir) {
    $RemoteBackupDir = "$TargetDir/backups"
}

$ProjectPython = Join-Path $ProjectRoot 'agomtradepro\Scripts\python.exe'
$PythonExe = if (Test-Path $ProjectPython) { $ProjectPython } else { 'python' }
Require-Command $PythonExe 'Python is required to run the PostgreSQL backup client.'

$PythonScript = Join-Path $PSScriptRoot 'backup-vps-postgres.py'
$Arguments = @(
    $PythonScript,
    '--host', $VpsHost,
    '--user', $VpsUser,
    '--port', "$VpsPort",
    '--output-dir', $OutputDir,
    '--remote-backup-dir', $RemoteBackupDir,
    '--timeout', "$TimeoutSeconds",
    '--prune-remote-older-than-days', "$PruneRemoteOlderThanDays"
)
if ($DownloadLatest) {
    $Arguments += '--download-latest'
}

Write-Info '=== AgomTradePro PostgreSQL Backup ==='
Write-Info "VPS:          $VpsUser@${VpsHost}:$VpsPort"
Write-Info "Remote dir:   $RemoteBackupDir/database"
Write-Info "Local dir:    $OutputDir"
Write-Info "Mode:         $(if ($DownloadLatest) { 'download latest' } else { 'create and download' })"
Write-Info "Remote prune: $(if ($PruneRemoteOlderThanDays -gt 0) { "older than $PruneRemoteOlderThanDays days" } else { 'disabled' })"

& $PythonExe @Arguments
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
    Throw-Err "PostgreSQL backup failed with exit code $ExitCode."
}

Write-Info '=== Backup succeeded ==='
exit 0
