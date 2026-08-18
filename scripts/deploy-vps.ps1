<#
.SYNOPSIS
    One-click deploy AgomTradePro to VPS via git-clone.
.DESCRIPTION
    Reads all config from environment variables, creates a temp password file,
    calls the remote build/deploy script, and cleans up.
    Celery is enabled by default. Use -DisableCelery to opt out.
    Supports optional flags: -IncludeSqlite, -DisableCelery, -Upgrade,
    -BuildTimeoutSeconds.
.EXAMPLE
    .\scripts\deploy-vps.ps1
    .\scripts\deploy-vps.ps1 -DisableCelery
    .\scripts\deploy-vps.ps1 -IncludeSqlite
    .\scripts\deploy-vps.ps1 -Upgrade
    .\scripts\deploy-vps.ps1 -BuildTimeoutSeconds 5400
#>
param(
    [switch]$IncludeSqlite,
    [switch]$EnableCelery,
    [switch]$DisableCelery,
    [switch]$Upgrade,
    [switch]$BootstrapDecisionRepair,
    [string]$DecisionAssetCodes,
    [double]$DecisionQuoteMaxAgeHours = 4.0,
    [switch]$DecisionRepairSkipPulse,
    [switch]$DecisionRepairSkipAlpha,
    [switch]$SkipPreDeployBackup,
    [switch]$DisableAutoRollback,
    [switch]$GlobalDockerCleanup,
    [ValidateRange(600, 86400)]
    [int]$BuildTimeoutSeconds = 3600,
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
$HttpPort = if ($env:AGOM_VPS_HTTP_PORT) { [int]$env:AGOM_VPS_HTTP_PORT } else { $null }
$TargetDir = if ($env:AGOM_VPS_TARGET_DIR) { $env:AGOM_VPS_TARGET_DIR } else { '/opt/agomtradepro' }

if (-not $VpsHost) {
    Throw-Err "AGOM_VPS_HOST is not set. Set it in your environment before running this script."
}
if (-not $VpsPass) {
    Throw-Err "AGOM_VPS_PASS is not set. Set it in your environment before running this script."
}

$Action = if ($Upgrade) { 'upgrade' } else { 'fresh' }
$UseCelery = $true
if ($DisableCelery) {
    $UseCelery = $false
}
elseif ($EnableCelery) {
    $UseCelery = $true
}

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
Write-Info "HTTP Port:  $(if ($null -ne $HttpPort) { $HttpPort } else { 'auto' })"
Write-Info "SQLite:     $(if ($IncludeSqlite) { 'YES (overwrite DB and use source encryption key)' } else { 'No (preserve remote data)' })"
Write-Info "Celery:     $(if ($UseCelery) { 'Enabled (default)' } else { 'Disabled' })"
Write-Info "Build timeout: $BuildTimeoutSeconds seconds"
Write-Info "Pre-deploy backup: $(if ($SkipPreDeployBackup) { 'Skipped (emergency)' } else { 'Required' })"
Write-Info "Auto rollback: $(if ($DisableAutoRollback) { 'Disabled (emergency)' } else { 'Enabled' })"
Write-Info "Docker cleanup: $(if ($GlobalDockerCleanup) { 'GLOBAL (explicit)' } else { 'AgomTradePro project only' })"
Write-Info "Decision repair: $(if ($BootstrapDecisionRepair) { 'Enabled' } else { 'Disabled' })"
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

if (Test-Path (Join-Path $ProjectRoot "package.json")) {
    Require-Command npm
    Write-Info "Running TUI runtime preflight..."
    npm ci
    if ($LASTEXITCODE -ne 0) { Throw-Err "npm ci failed." }
    npm run check:tui
    if ($LASTEXITCODE -ne 0) { Throw-Err "TUI runtime bundle check failed." }
    npm run test:tui-js
    if ($LASTEXITCODE -ne 0) { Throw-Err "TUI runtime JavaScript tests failed." }
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
        '--git-clone',
        '--git-branch', $GitBranch,
        '--allowed-hosts', $AllowedHosts,
        '--timeout', "$BuildTimeoutSeconds"
    )

    if ($null -ne $HttpPort) { $pyArgs += @('--http-port', $HttpPort) }
    if ($IncludeSqlite) { $pyArgs += '--include-sqlite' }
    if ($UseCelery)  { $pyArgs += '--enable-celery' } else { $pyArgs += '--disable-celery' }
    if ($BootstrapDecisionRepair) { $pyArgs += '--bootstrap-decision-repair' }
    if ($DecisionAssetCodes) { $pyArgs += @('--decision-asset-codes', $DecisionAssetCodes) }
    if ($DecisionQuoteMaxAgeHours) { $pyArgs += @('--decision-quote-max-age-hours', "$DecisionQuoteMaxAgeHours") }
    if ($DecisionRepairSkipPulse) { $pyArgs += '--decision-repair-skip-pulse' }
    if ($DecisionRepairSkipAlpha) { $pyArgs += '--decision-repair-skip-alpha' }
    if ($SkipPreDeployBackup) { $pyArgs += '--skip-predeploy-backup' }
    if ($DisableAutoRollback) { $pyArgs += '--disable-auto-rollback' }
    if ($GlobalDockerCleanup) { $pyArgs += '--wipe-docker' }

    $ProjectPython = Join-Path $ProjectRoot "agomtradepro\Scripts\python.exe"
    $PythonExe = if (Test-Path $ProjectPython) { $ProjectPython } else { 'python' }

    Write-Info "Launching deploy..."
    & $PythonExe @pyArgs
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Info "=== Deploy succeeded ==="
        Write-Info "Verifying health..."
        $expectedCommit = (& git -C $ProjectRoot rev-parse HEAD).Trim()
        $verifyScriptPath = Join-Path $PSScriptRoot "deploy_vps_verify.py"
        $verifyArgs = @(
            $verifyScriptPath,
            '--host', $VpsHost,
            '--user', $VpsUser,
            '--password-file', $passFile,
            '--port', $VpsPort,
            '--target-dir', $TargetDir,
            '--expected-commit', $expectedCommit,
            # A freshly restarted stack can need more than the SSH probe
            # timeout while healthcheck runs migrations/readiness checks.
            '--timeout', '120'
        )
        if ($null -ne $HttpPort) { $verifyArgs += @('--http-port', $HttpPort) }
        if ($UseCelery) { $verifyArgs += '--expect-celery' }
        if (-not $DisableAutoRollback) { $verifyArgs += '--auto-rollback' }
        try {
            & $PythonExe @verifyArgs
            $verifyExitCode = $LASTEXITCODE
            if ($verifyExitCode -ne 0) {
                Write-Err "Post-deploy verification failed."
                $exitCode = $verifyExitCode
            }
        } catch {
            Write-Warn "Post-deploy verification skipped: $($_.Exception.Message)"
        }
    } else {
        Write-Err "=== Deploy FAILED (exit code $exitCode) ==="
    }
}
finally {
    Remove-Item $passFile -Force -ErrorAction SilentlyContinue
}
exit $exitCode
