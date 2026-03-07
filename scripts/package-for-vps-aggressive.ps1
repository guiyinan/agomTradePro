param(
    [string]$Tag,
    [string]$OutputDir = "dist",
    [string]$SqliteFile = "db.sqlite3",
    [switch]$WithLocalSqlite,
    [switch]$PreferWslBuild,
    [switch]$WslOnly,
    [switch]$SkipRedisData,
    [switch]$SkipWheelCache,
    [switch]$RefreshWheelCache,
    [switch]$AllowOnlinePipFallback,
    [switch]$NoStageContext,
    [switch]$UseWslContext,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot/shared/common.ps1"

function Show-Help {
    @"
Usage:
  ./scripts/package-for-vps-aggressive.ps1 [options]

Purpose:
  Aggressive wrapper around package-for-vps.ps1.
  Tries multiple build strategies automatically until one succeeds.

Options:
  -Tag <string>             Bundle/image tag. Default: current timestamp.
  -OutputDir <string>       Bundle output directory. Default: dist
  -SqliteFile <string>      SQLite file to inject when -WithLocalSqlite is set. Default: db.sqlite3
  -WithLocalSqlite          Inject local SQLite into the final bundle after image packaging succeeds
  -PreferWslBuild           Prefer WSL-context build strategies before Windows-local ones
  -WslOnly                  Only try WSL-context build strategies
  -SkipRedisData            Keep Redis data out of the bundle
  -SkipWheelCache           Skip local Linux wheel cache preparation
  -RefreshWheelCache        Force refresh local Linux wheel cache before first attempt
  -AllowOnlinePipFallback   Allow online pip fallback from the first attempt
  -NoStageContext           Start with project-root build context
  -UseWslContext            Start with WSL build context
  -Help, -h, --help         Show help

Output:
  Prints FINAL_BUNDLE=<path> on success.
"@ | Write-Host
}

if ($Help -or $args -contains "-h" -or $args -contains "--help") {
    Show-Help
    exit 0
}

Require-Command docker

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ([string]::IsNullOrWhiteSpace($Tag)) {
    $Tag = Get-Date -Format "yyyyMMddHHmmss"
}

function Test-WslDistroAvailable {
    try {
        $distros = @(
            (& wsl.exe -l -q 2>$null) |
            ForEach-Object { ($_ -replace "`0", "").Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_ -notin @("docker-desktop", "docker-desktop-data") }
        )
        return ($distros.Count -gt 0)
    } catch {
        return $false
    }
}

function Invoke-PackageAttempt {
    param(
        [string]$Label,
        [switch]$DisableBuildKit,
        [switch]$AttemptRefreshWheelCache,
        [switch]$AttemptAllowOnlinePipFallback,
        [switch]$AttemptNoStageContext,
        [switch]$AttemptUseWslContext
    )

    $cmdArgs = @(
        "-File", "scripts/package-for-vps.ps1",
        "-Tag", $Tag,
        "-OutputDir", $OutputDir,
        "-SkipData",
        "-SkipRedisData"
    )

    if ($SkipWheelCache) { $cmdArgs += "-SkipWheelCache" }
    if ($DisableBuildKit) { $cmdArgs += "-DisableBuildKit" }
    if ($AttemptRefreshWheelCache) { $cmdArgs += "-RefreshWheelCache" }
    if ($AttemptAllowOnlinePipFallback) { $cmdArgs += "-AllowOnlinePipFallback" }
    if ($AttemptNoStageContext) { $cmdArgs += "-NoStageContext" }
    if ($AttemptUseWslContext) { $cmdArgs += "-UseWslContext" }

    Write-Info "Packaging attempt: $Label"
    Write-Host ("  pwsh " + ($cmdArgs -join " ")) -ForegroundColor DarkGray

    & "C:\Program Files\PowerShell\7\pwsh.exe" @cmdArgs
    return $LASTEXITCODE
}

$wslAvailable = Test-WslDistroAvailable
$strategies = @()

function New-Strategy {
    param(
        [string]$Label,
        [bool]$DisableBuildKit,
        [bool]$RefreshWheelCache,
        [bool]$AllowOnline,
        [bool]$NoStageContext,
        [bool]$UseWslContext
    )

    return [pscustomobject]@{
        Label = $Label
        DisableBuildKit = $DisableBuildKit
        RefreshWheelCache = $RefreshWheelCache
        AllowOnline = $AllowOnline
        NoStageContext = $NoStageContext
        UseWslContext = $UseWslContext
    }
}

function Add-WslStrategies {
    if (-not $wslAvailable) {
        return
    }

    $list = @(
        (New-Strategy -Label "WSL context + BuildKit + cached wheelhouse" -DisableBuildKit $false -RefreshWheelCache $RefreshWheelCache -AllowOnline $AllowOnlinePipFallback -NoStageContext $false -UseWslContext $true),
        (New-Strategy -Label "WSL context + legacy builder + cached wheelhouse" -DisableBuildKit $true -RefreshWheelCache $false -AllowOnline $AllowOnlinePipFallback -NoStageContext $false -UseWslContext $true),
        (New-Strategy -Label "WSL context + legacy builder + refreshed wheelhouse" -DisableBuildKit $true -RefreshWheelCache $true -AllowOnline $AllowOnlinePipFallback -NoStageContext $false -UseWslContext $true),
        (New-Strategy -Label "WSL context + legacy builder + refreshed wheelhouse + online fallback" -DisableBuildKit $true -RefreshWheelCache $true -AllowOnline $true -NoStageContext $false -UseWslContext $true)
    )

    $script:wslStrategies = $list
    $script:strategies += $list
}

function Add-WindowsStrategies {
    $script:strategies += @(
        (New-Strategy -Label "BuildKit + staged context + cached wheelhouse" -DisableBuildKit $false -RefreshWheelCache $RefreshWheelCache -AllowOnline $AllowOnlinePipFallback -NoStageContext $NoStageContext -UseWslContext $false),
        (New-Strategy -Label "Legacy builder + staged context + cached wheelhouse" -DisableBuildKit $true -RefreshWheelCache $false -AllowOnline $AllowOnlinePipFallback -NoStageContext $NoStageContext -UseWslContext $false),
        (New-Strategy -Label "Legacy builder + staged context + refreshed wheelhouse" -DisableBuildKit $true -RefreshWheelCache $true -AllowOnline $AllowOnlinePipFallback -NoStageContext $NoStageContext -UseWslContext $false),
        (New-Strategy -Label "Legacy builder + staged context + refreshed wheelhouse + online fallback" -DisableBuildKit $true -RefreshWheelCache $true -AllowOnline $true -NoStageContext $NoStageContext -UseWslContext $false),
        (New-Strategy -Label "Legacy builder + project-root context + refreshed wheelhouse + online fallback" -DisableBuildKit $true -RefreshWheelCache $true -AllowOnline $true -NoStageContext $true -UseWslContext $false)
    )
}

if ($WslOnly -and -not $wslAvailable) {
    Throw-Err "WslOnly was requested, but no usable WSL distro was found"
}

if ($UseWslContext -or $PreferWslBuild -or $WslOnly) {
    Add-WslStrategies
}

if (-not $WslOnly) {
    Add-WindowsStrategies
}

if (-not ($UseWslContext -or $PreferWslBuild -or $WslOnly)) {
    Add-WslStrategies
}

$strategies = @($strategies | Select-Object -Unique)

$bundlePath = Join-Path $ProjectRoot (Join-Path $OutputDir "agomsaaf-vps-bundle-$Tag.tar.gz")
$success = $false
$attemptsRun = @()

foreach ($strategy in $strategies) {
    $exitCode = Invoke-PackageAttempt `
        -Label $strategy.Label `
        -DisableBuildKit:([bool]$strategy.DisableBuildKit) `
        -AttemptRefreshWheelCache:([bool]$strategy.RefreshWheelCache) `
        -AttemptAllowOnlinePipFallback:([bool]$strategy.AllowOnline) `
        -AttemptNoStageContext:([bool]$strategy.NoStageContext) `
        -AttemptUseWslContext:([bool]$strategy.UseWslContext)

    $attemptsRun += "$($strategy.Label) => exit $exitCode"
    if ($exitCode -eq 0 -and (Test-Path $bundlePath)) {
        $success = $true
        break
    }
    Write-Warn "Attempt failed: $($strategy.Label)"
}

if (-not $success) {
    Write-Err "All packaging attempts failed"
    $attemptsRun | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    exit 1
}

$finalBundle = $bundlePath

if ($WithLocalSqlite) {
    if (-not (Test-Path $SqliteFile)) {
        Throw-Err "SQLite file not found: $SqliteFile"
    }

    Write-Info "Injecting local SQLite into packaged bundle"
    & "C:\Program Files\PowerShell\7\pwsh.exe" `
        -File "scripts/inject-sqlite-into-bundle.ps1" `
        -SourceBundle $bundlePath `
        -OutputTag "$Tag-live" `
        -SqliteFile $SqliteFile

    if ($LASTEXITCODE -ne 0) {
        Throw-Err "SQLite injection failed"
    }

    $finalBundle = Join-Path $ProjectRoot (Join-Path $OutputDir "agomsaaf-vps-bundle-$Tag-live.tar.gz")
    if (-not (Test-Path $finalBundle)) {
        Throw-Err "Expected injected bundle not found: $finalBundle"
    }
}

Write-Info "Packaging complete"
Write-Host "FINAL_BUNDLE=$finalBundle"
