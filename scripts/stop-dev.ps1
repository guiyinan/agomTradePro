# AgomSAAF Development Environment Stop Script
# Version: 3.5
# Updated: 2026-02-01

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [switch]$Force,

    [Parameter(Mandatory=$false)]
    [switch]$All
)

$ErrorActionPreference = 'Continue'

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Stopping AgomSAAF Services" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Function: Stop Docker services
function Stop-DockerServices {
    Write-Host "[1/4] Checking Docker services..." -ForegroundColor Yellow

    $null = docker --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[INFO] Stopping Docker containers..." -ForegroundColor Yellow
        docker-compose -f docker-compose-dev.yml down
        Write-Host "[OK] Docker containers stopped" -ForegroundColor Green
    } else {
        Write-Host "[SKIP] Docker not available" -ForegroundColor Gray
    }
    Write-Host ""
}

# Function: Stop Celery processes
function Stop-CeleryProcesses {
    Write-Host "[2/4] Stopping Celery processes..." -ForegroundColor Yellow

    $processes = Get-WmiObject Win32_Process | Where-Object {
        $_.CommandLine -like "*celery*worker*" -or
        $_.CommandLine -like "*celery*beat*" -or
        $_.MainWindowTitle -like "*Celery*"
    }

    if ($processes) {
        foreach ($proc in $processes) {
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
                Write-Host "[OK] Stopped PID $($proc.ProcessId)" -ForegroundColor Green
            } catch {
                Write-Host "[WARN] Could not stop PID $($proc.ProcessId)" -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "[SKIP] No Celery processes found" -ForegroundColor Gray
    }
    Write-Host ""
}

# Function: Clean up temporary batch files
function Remove-TempFiles {
    Write-Host "[3/4] Cleaning up temporary files..." -ForegroundColor Yellow

    $tempFiles = @("start_celery_worker.bat", "start_celery_beat.bat")
    foreach ($file in $tempFiles) {
        if (Test-Path $file) {
            Remove-Item $file -Force
            Write-Host "[OK] Removed $file" -ForegroundColor Green
        }
    }
    Write-Host "[OK] Cleanup complete" -ForegroundColor Green
    Write-Host ""
}

# Function: Show Django stop reminder
function Show-DjangoReminder {
    Write-Host "[4/4] Django Server" -ForegroundColor Yellow
    Write-Host "[INFO] Django server runs in the main window" -ForegroundColor Gray
    Write-Host "[INFO] Press Ctrl+C in the Django window to stop it" -ForegroundColor Gray
    Write-Host ""
}

# Main execution
Stop-DockerServices
Stop-CeleryProcesses
Remove-TempFiles
Show-DjangoReminder

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Stop Complete" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
