param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\AgomQmtAgent",
    [switch]$RemoveState
)

$ErrorActionPreference = "Stop"
$ResolvedRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$DriveRoot = [System.IO.Path]::GetPathRoot($ResolvedRoot)
if ($ResolvedRoot -eq $DriveRoot -or $ResolvedRoot.Length -lt 8) {
    throw "Refusing to uninstall from an unsafe target path: $ResolvedRoot"
}

if (Get-ScheduledTask -TaskName "AgomQmtAgent" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "AgomQmtAgent" -Confirm:$false
}

foreach ($Name in @("qmt_agent", "runtime", "cache", "secrets")) {
    $Target = Join-Path $ResolvedRoot $Name
    if (Test-Path -LiteralPath $Target) {
        Remove-Item -LiteralPath $Target -Recurse -Force
    }
}

if ($RemoveState) {
    foreach ($Name in @("state", "logs", "config.json", "config.yaml", "STOP")) {
        $Target = Join-Path $ResolvedRoot $Name
        if (Test-Path -LiteralPath $Target) {
            Remove-Item -LiteralPath $Target -Recurse -Force
        }
    }
}

Write-Host "QMT Agent task, code, runtime, cache, and encrypted token were removed."
if (-not $RemoveState) {
    Write-Host "Configuration, logs, STOP file, and SQLite state were preserved at $ResolvedRoot."
}
