[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$AsOfDate = "",

    [Parameter(Mandatory = $false)]
    [string]$SettingsModule = "core.settings.development"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Resolve-PythonExe {
    $venvPython = Join-Path $root "agomtradepro\Scripts\python.exe"
    if ($env:CONDA_DEFAULT_ENV -eq "agomtradepro") {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd) {
            return $pythonCmd.Source
        }
    }
    if (Test-Path $venvPython) {
        return $venvPython
    }
    throw "Python runtime not found. Activate conda env 'agomtradepro' or create venv at agomtradepro\Scripts\python.exe."
}

function Invoke-ManageCommand([string]$PythonPath, [string[]]$Arguments) {
    & $PythonPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("Command failed: " + ($Arguments -join " "))
    }
}

$pythonExe = Resolve-PythonExe
$commonArgs = @("manage.py")
if ($AsOfDate) {
    $asOfArgs = @("--as-of-date", $AsOfDate)
} else {
    $asOfArgs = @()
}

$env:DJANGO_SETTINGS_MODULE = $SettingsModule

Write-Host "[INFO] Syncing market thermometer inputs..." -ForegroundColor Cyan
Invoke-ManageCommand -PythonPath $pythonExe -Arguments ($commonArgs + @("sync_market_thermometer_inputs") + $asOfArgs)

Write-Host "[INFO] Recalculating market thermometer snapshot..." -ForegroundColor Cyan
Invoke-ManageCommand -PythonPath $pythonExe -Arguments ($commonArgs + @("calculate_market_thermometer") + $asOfArgs)

Write-Host "[OK] Local market thermometer refresh completed." -ForegroundColor Green
