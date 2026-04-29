<#
.SYNOPSIS
    One-click deploy AgomTradePro to VPS via git-clone.
.DESCRIPTION
    Reads all config from environment variables, creates a temp password file,
    calls the remote build/deploy script, and cleans up.
    Supports optional flags: -IncludeSqlite, -EnableCelery, -Upgrade.
.EXAMPLE
    .\scripts\deploy-vps.ps1
    .\scripts\deploy-vps.ps1 -EnableCelery
    .\scripts\deploy-vps.ps1 -IncludeSqlite
    .\scripts\deploy-vps.ps1 -Upgrade
#>
param(
    [switch]$IncludeSqlite,
    [switch]$EnableCelery,
    [switch]$Upgrade,
    [string]$GitBranch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\shared\common.ps1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VpsHost = $env:AGOM_VPS_HOST
$VpsUser = if ($env:AGOM_VPS_USER) { $env:AGOM_VPS_USER } else { 'root' }
$VpsPass = $env:AGOM_VPS_PASS
$VpsPort = if ($env:AGOM_VPS_PORT) { [int]$env:AGOM_VPS_PORT } else { 22 }
$HttpPort = if ($env:AGOM_VPS_HTTP_PORT) { [int]$env:AGOM_VPS_HTTP_PORT } else { 8000 }
$TargetDir = if ($env:AGOM_VPS_TARGET_DIR) { $env:AGOM_VPS_TARGET_DIR } else { '/opt/agomtradepro' }

if (-not $VpsHost) {
    Throw-Err "AGOM_VPS_HOST is not set. Set it in your environment before running this script."
}
if (-not $VpsPass) {
    Throw-Err "AGOM_VPS_PASS is not set. Set it in your environment before running this script."
}

$Action = if ($Upgrade) { 'upgrade' } else { 'fresh' }

if (-not $GitBranch) {
    $GitBranch = git rev-parse --abbrev-ref HEAD 2>$null
    if (-not $GitBranch) {
        Throw-Err "Cannot detect current git branch. Pass -GitBranch explicitly."
    }
}

$AllowedHosts = "$VpsHost,demo.agomtrade.pro,localhost,127.0.0.1"

Write-Info "=== AgomTradePro VPS Deploy ==="
Write-Info "Host:       $VpsUser@${VpsHost}:$VpsPort"
Write-Info "Target:     $TargetDir"
Write-Info "Action:     $Action"
Write-Info "Branch:     $GitBranch"
Write-Info "HTTP Port:  $HttpPort"
Write-Info "SQLite:     $(if ($IncludeSqlite) { 'YES (will overwrite remote DB)' } else { 'No (preserve remote data)' })"
Write-Info "Celery:     $(if ($EnableCelery) { 'Enabled' } else { 'Disabled' })"
Write-Info "================================"

$uncommitted = git status --porcelain 2>$null
if ($uncommitted) {
    Write-Warn "There are uncommitted changes:"
    Write-Host $uncommitted
    $confirm = Read-Host "Continue without committing? (y/N)"
    if ($confirm -notmatch '^[yY]') {
        Write-Info "Aborted."
        exit 1
    }
}

$unpushed = git log "@{u}..HEAD" --oneline 2>$null
if ($unpushed) {
    Write-Warn "There are unpushed commits on $GitBranch"
    $confirm = Read-Host "Push to origin/$GitBranch first? (Y/n)"
    if ($confirm -notmatch '^[nN]') {
        Write-Info "Pushing to origin/$GitBranch ..."
        git push origin $GitBranch
        if ($LASTEXITCODE -ne 0) {
            Throw-Err "git push failed."
        }
    }
}

$passFile = Join-Path $env:TEMP "agomtradepro_vps_pass_$([guid]::NewGuid().ToString('N').Substring(0,8)).txt"
try {
    Set-Content -Path $passFile -Value $VpsPass -NoNewline

    $pyArgs = @(
        "$PSScriptRoot\remote_build_deploy_vps.py",
        '--host', $VpsHost,
        '--user', $VpsUser,
        '--password-file', $passFile,
        '--port', $VpsPort,
        '--action', $Action,
        '--wipe-docker',
        '--git-clone',
        '--git-branch', $GitBranch,
        '--http-port', $HttpPort,
        '--allowed-hosts', $AllowedHosts,
        '--timeout', '1800'
    )

    if ($IncludeSqlite) { $pyArgs += '--include-sqlite' }
    if ($EnableCelery)  { $pyArgs += '--enable-celery' }

    $ProjectPython = Join-Path $ProjectRoot "agomtradepro\Scripts\python.exe"
    $PythonExe = if (Test-Path $ProjectPython) { $ProjectPython } else { 'python' }

    Write-Info "Launching deploy..."
    & $PythonExe @pyArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Remove-Item $passFile -Force -ErrorAction SilentlyContinue
}

if ($exitCode -eq 0) {
    Write-Info "=== Deploy succeeded ==="
} else {
    Write-Err "=== Deploy FAILED (exit code $exitCode) ==="
}
exit $exitCode
