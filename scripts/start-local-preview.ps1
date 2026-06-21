[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,

    [Parameter(Mandatory = $false)]
    [string]$BindHost = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [ValidateRange(5, 120)]
    [int]$TimeoutSeconds = 45,

    [Parameter(Mandatory = $false)]
    [string]$SettingsModule = "core.settings.development",

    [Parameter(Mandatory = $false)]
    [switch]$RefreshMarketThermometer,

    [Parameter(Mandatory = $false)]
    [string]$MarketThermometerAsOfDate = ""
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

function Get-PreviewPidFile([int]$TargetPort) {
    $tmpDir = Join-Path $root "tmp"
    New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
    return (Join-Path $tmpDir ("local-preview-" + $TargetPort + ".pid"))
}

function Stop-PreviewByPort([int]$TargetPort) {
    $listenLine = netstat -ano | Select-String -Pattern (":$TargetPort\s+.*LISTENING\s+")
    if (-not $listenLine) {
        return $false
    }
    $line = ($listenLine | Select-Object -First 1).Line.Trim()
    $parts = $line -split "\s+"
    $portPid = $parts[-1]
    if (-not $portPid) {
        return $false
    }
    Stop-Process -Id ([int]$portPid) -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    return $true
}

function Get-ListeningPid([int]$TargetPort) {
    $listenLine = netstat -ano | Select-String -Pattern (":$TargetPort\s+.*LISTENING\s+")
    if (-not $listenLine) {
        return $null
    }
    $line = ($listenLine | Select-Object -First 1).Line.Trim()
    $parts = $line -split "\s+"
    if ($parts.Length -lt 1) {
        return $null
    }
    return $parts[-1]
}

function Get-PreviewLoginHint([string]$PythonPath, [string]$DjangoSettingsModule) {
    $probe = @"
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "$DjangoSettingsModule")
import django
django.setup()
from django.contrib.auth import authenticate

for username in ("admin", "codex_demo_admin", "codex_verify"):
    if authenticate(username=username, password="Aa123456") is not None:
        print(username)
        break
"@

    try {
        $resolvedUsername = $probe | & $PythonPath - 2>$null | Select-Object -First 1
        if ($resolvedUsername) {
            return ($resolvedUsername.Trim() + " / Aa123456")
        }
    } catch {
        return $null
    }

    return $null
}

$pythonExe = Resolve-PythonExe
$pidFile = Get-PreviewPidFile -TargetPort $Port
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdoutLog = Join-Path $logDir ("local-preview-" + $Port + ".stdout.log")
$stderrLog = Join-Path $logDir ("local-preview-" + $Port + ".stderr.log")

if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existingPid) {
        Stop-Process -Id ([int]$existingPid) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

Stop-PreviewByPort -TargetPort $Port | Out-Null

if (Test-Path $stdoutLog) {
    Remove-Item $stdoutLog -Force
}
if (Test-Path $stderrLog) {
    Remove-Item $stderrLog -Force
}

if ($RefreshMarketThermometer) {
    Write-Host "[INFO] Refreshing market thermometer before preview startup..." -ForegroundColor Cyan
    $refreshArgs = @(
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $root "scripts/refresh-local-market-thermometer.ps1"),
        "-SettingsModule",
        $SettingsModule
    )
    if ($MarketThermometerAsOfDate) {
        $refreshArgs += @("-AsOfDate", $MarketThermometerAsOfDate)
    }
    & powershell @refreshArgs
}

$serverScript = Join-Path $root "scripts\local_preview_server.py"
$env:DISABLE_CELERY_FILE_LOGS = "true"
$serverProcess = Start-Process -FilePath $pythonExe `
    -ArgumentList @(
        $serverScript,
        "--host",
        $BindHost,
        "--port",
        [string]$Port,
        "--settings",
        $SettingsModule
    ) `
    -WorkingDirectory $root `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

$baseUrl = "http://{0}:{1}" -f $BindHost, $Port
$ready = $false
for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri ($baseUrl + "/account/login/?next=/dashboard/") -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
            $ready = $true
            break
        }
    } catch {
        # keep waiting
    }
}

if (-not $ready) {
    Write-Host "[ERROR] Local preview failed to start." -ForegroundColor Red
    if (Test-Path $stdoutLog) {
        Write-Host "--- stdout tail ---" -ForegroundColor Yellow
        Get-Content $stdoutLog -Tail 80 | Out-Host
    }
    if (Test-Path $stderrLog) {
        Write-Host "--- stderr tail ---" -ForegroundColor Yellow
        Get-Content $stderrLog -Tail 80 | Out-Host
    }
    Stop-PreviewByPort -TargetPort $Port | Out-Null
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    exit 1
}

$listeningPid = Get-ListeningPid -TargetPort $Port
$pidToRecord = if ($listeningPid) { $listeningPid } else { [string]$serverProcess.Id }
Set-Content -Path $pidFile -Value $pidToRecord -Encoding ASCII

Write-Host "[OK] Local preview is ready." -ForegroundColor Green
Write-Host ("[INFO] URL: " + $baseUrl + "/") -ForegroundColor Cyan
Write-Host ("[INFO] Login: " + $baseUrl + "/account/login/?next=/dashboard/") -ForegroundColor Cyan
$loginHint = Get-PreviewLoginHint -PythonPath $pythonExe -DjangoSettingsModule $SettingsModule
if ($loginHint) {
    Write-Host ("[INFO] Preview credentials: " + $loginHint) -ForegroundColor Cyan
}
Write-Host ("[INFO] PID: " + $pidToRecord) -ForegroundColor Gray
Write-Host ("[INFO] stdout: " + $stdoutLog) -ForegroundColor Gray
Write-Host ("[INFO] stderr: " + $stderrLog) -ForegroundColor Gray
