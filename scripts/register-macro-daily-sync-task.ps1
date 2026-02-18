param(
    [string]$TaskName = "AgomSAAF-Daily-Macro-Sync",
    [string]$Time = "08:05",
    [string]$PythonExe = "agomsaaf\\Scripts\\python.exe",
    [string]$WorkDir = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

$actionArgs = @(
    "manage.py",
    "sync_macro_data",
    "--source", "akshare",
    "--indicators", "CN_PMI", "CN_CPI", "CN_CPI_NATIONAL_YOY",
    "--years", "5"
) -join " "

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $actionArgs -WorkingDirectory $WorkDir
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Output "REGISTERED=$TaskName AT=$Time"
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
