[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [string]$PythonExe = "",
    [string]$QmtRoot = "D:\qmt",
    [string]$PipeName = "agom_qmt_builtin_bridge",
    [switch]$RunReadProbe
)

$ErrorActionPreference = "Stop"

function Resolve-ExistingPath([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description does not exist: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Write-Step([string]$Text) {
    Write-Host "[Agom QMT setup] $Text" -ForegroundColor Cyan
}

$InstallRoot = $null
if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $InstallRoot = Join-Path $env:LOCALAPPDATA "AgomQmtAgent"
}
if (-not $ConfigPath) {
    if (-not $InstallRoot) {
        throw "LOCALAPPDATA is unavailable. Pass -ConfigPath to select the Agent configuration."
    }
    $ConfigPath = Join-Path $InstallRoot "config.json"
}
$ConfigPath = Resolve-ExistingPath $ConfigPath "Agent configuration"
$ConfigDirectory = Split-Path -Parent $ConfigPath
$StrategyPath = Resolve-ExistingPath (Join-Path $PSScriptRoot "..\builtin_strategy.py") "Built-in strategy source"
$QmtExecutable = Join-Path $QmtRoot "bin.x64\XtItClient.exe"
if (-not (Test-Path -LiteralPath $QmtExecutable)) {
    throw "QMT executable was not found. Pass -QmtRoot with the actual installation root: $QmtRoot"
}
if ($PipeName -notmatch '^[A-Za-z0-9_-]{1,80}$') {
    throw "PipeName must contain only letters, numbers, underscores, and hyphens."
}

Write-Step "Reading the existing Agent configuration without changing credentials."
$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
foreach ($RequiredField in @("agent_id", "server_url", "qmt_userdata_path", "broker_account_id", "system_account_id")) {
    if (-not ($Config.PSObject.Properties.Name -contains $RequiredField)) {
        throw "Agent configuration is missing required field: $RequiredField"
    }
}
if ([string]$Config.broker_account_type -and [string]$Config.broker_account_type -ne "STOCK") {
    throw "The built-in bridge currently supports STOCK accounts only."
}

$BackupPath = "$ConfigPath.builtin-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $ConfigPath -Destination $BackupPath
$Config | Add-Member -NotePropertyName "qmt_trade_api" -NotePropertyValue "builtin_python" -Force
$Config | Add-Member -NotePropertyName "qmt_builtin_pipe_name" -NotePropertyValue $PipeName -Force
if (-not ($Config.PSObject.Properties.Name -contains "qmt_builtin_bridge_timeout_seconds")) {
    $Config | Add-Member -NotePropertyName "qmt_builtin_bridge_timeout_seconds" -NotePropertyValue 10
}
$Config | Add-Member -NotePropertyName "dry_run" -NotePropertyValue $true -Force
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ConfigPath, ($Config | ConvertTo-Json -Depth 10) + "`n", $Utf8NoBom)
Write-Step "Configuration updated. Backup: $BackupPath"
Write-Step "dry_run remains true. No order or cancel function is called by this setup script."

Write-Host ""
Write-Host "Next steps in QMT:" -ForegroundColor Yellow
Write-Host "1. Log in using the quote + trade mode."
Write-Host "2. Create a Python strategy named AgomBuiltinBridge."
Write-Host "3. Replace the editor content with the complete file: $StrategyPath"
Write-Host "4. Do not edit PIPE_ADDRESS or account code in the strategy."
Write-Host "5. Save the strategy, then open model trading / strategy trading."
Write-Host "6. Create a model-trading entry, bind the same STOCK account as broker_account_id, and start it."
Write-Host "7. Keep QMT and this strategy running. Do not start duplicate strategies using the same pipe."
Write-Host "8. Run this script again with -RunReadProbe after the strategy is running."

if (-not (Get-Process -Name "XtItClient" -ErrorAction SilentlyContinue)) {
    Write-Warning "QMT is not currently running. Start and log in before the read probe."
}

if ($RunReadProbe) {
    Write-Host ""
    Read-Host "Confirm that AgomBuiltinBridge is running in QMT model trading, then press Enter" | Out-Null
    if (-not $PythonExe) {
        if (-not $InstallRoot) {
            throw "LOCALAPPDATA is unavailable. Pass -PythonExe to select the Agent interpreter."
        }
        $PythonExe = Join-Path $InstallRoot "runtime\Scripts\python.exe"
    }
    $PythonExe = Resolve-ExistingPath $PythonExe "Agent Python interpreter"
    $LogDirectory = Join-Path $ConfigDirectory "logs"
    New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
    $EvidenceFile = Join-Path $LogDirectory "builtin-read-probe.json"
    Write-Step "Running the read-only probe. No order or cancel request is sent."
    & $PythonExe -m qmt_agent.main --config $ConfigPath --qmt-read-probe --evidence-file $EvidenceFile
    if ($LASTEXITCODE -ne 0) {
        throw "Read-only probe failed. Review the report and QMT strategy log: $EvidenceFile"
    }
    Write-Step "Read-only probe passed. Evidence: $EvidenceFile"
    Write-Step "Keep dry_run enabled until simulation, order/cancel, recovery, and reconciliation acceptance pass."
}
