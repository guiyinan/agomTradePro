# AgomSAAF Development Environment Startup Script
# Version: 3.5
# Updated: 2026-02-01

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateSet('sqlite', 'postgres', 'docker')]
    [string]$Mode = 'sqlite',

    [Parameter(Mandatory=$false)]
    [switch]$SkipCelery,

    [Parameter(Mandatory=$false)]
    [switch]$SkipBeat,

    [Parameter(Mandatory=$false)]
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$PythonExe = "agomsaaf\Scripts\python.exe"

# Header
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " AgomSAAF Development Environment" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Function: Check virtual environment
function Test-VirtualEnvironment {
    if (-not (Test-Path $PythonExe)) {
        Write-Host "[ERROR] Virtual environment not found!" -ForegroundColor Red
        Write-Host "Please run: python -m venv agomsaaf" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[OK] Virtual environment found" -ForegroundColor Green
}

# Function: Run migrations
function Invoke-Migrations {
    Write-Host "[INFO] Running database migrations..." -ForegroundColor Yellow
    & $PythonExe manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] Migration failed, retrying with --skip-checks..." -ForegroundColor Yellow
        & $PythonExe manage.py migrate --skip-checks
    }
    Write-Host "[OK] Migrations complete" -ForegroundColor Green
}

# Function: Check/Start Docker services
function Start-DockerServices {
    Write-Host "[INFO] Checking Docker..." -ForegroundColor Yellow

    $null = docker --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Docker not found!" -ForegroundColor Red
        return $false
    }

    Write-Host "[INFO] Starting PostgreSQL and Redis containers..." -ForegroundColor Yellow
    docker-compose -f docker-compose-dev.yml up -d

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to start Docker services!" -ForegroundColor Red
        return $false
    }

    # Wait for PostgreSQL
    Write-Host "[INFO] Waiting for PostgreSQL to be ready..." -ForegroundColor Yellow
    $maxAttempts = 30
    for ($i = 0; $i -lt $maxAttempts; $i++) {
        $result = docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf -d agomsaaf 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] PostgreSQL ready" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 2
    }

    # Wait for Redis
    Write-Host "[INFO] Waiting for Redis to be ready..." -ForegroundColor Yellow
    for ($i = 0; $i -lt $maxAttempts; $i++) {
        $result = docker exec agomsaaf_redis_dev redis-cli ping 2>&1
        if ($result -eq "PONG") {
            Write-Host "[OK] Redis ready" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 1
    }

    Write-Host ""
    return $true
}

# Function: Start Celery Worker
function Start-CeleryWorker {
    if ($SkipCelery) { return }

    Write-Host "[INFO] Starting Celery Worker..." -ForegroundColor Yellow
    $workerScript = "@echo off
title Celery Worker
call agomsaaf\Scripts\activate.bat
python -m celery -A core worker -l info --pool=solo
pause"

    $workerScript | Out-File -FilePath "start_celery_worker.bat" -Encoding ASCII
    Start-Process "cmd.exe" -ArgumentList "/k start_celery_worker.bat" -WindowStyle Normal
    Start-Sleep -Seconds 2
    Write-Host "[OK] Celery Worker started" -ForegroundColor Green
}

# Function: Start Celery Beat
function Start-CeleryBeat {
    if ($SkipBeat) { return }

    Write-Host "[INFO] Starting Celery Beat..." -ForegroundColor Yellow
    $beatScript = "@echo off
title Celery Beat
call agomsaaf\Scripts\activate.bat
python -m celery -A core beat -l info
pause"

    $beatScript | Out-File -FilePath "start_celery_beat.bat" -Encoding ASCII
    Start-Process "cmd.exe" -ArgumentList "/k start_celery_beat.bat" -WindowStyle Normal
    Start-Sleep -Seconds 2
    Write-Host "[OK] Celery Beat started" -ForegroundColor Green
}

# Main execution
Test-VirtualEnvironment

if ($Mode -eq 'docker') {
    $dockerOk = Start-DockerServices
    if (-not $dockerOk) {
        Write-Host "[WARN] Falling back to SQLite mode" -ForegroundColor Yellow
        $Mode = 'sqlite'
    }
}

Write-Host ""
Invoke-Migrations

# Start Celery services (only in docker/postgres mode)
if ($Mode -eq 'docker' -or $Mode -eq 'postgres') {
    Start-CeleryWorker
    Start-CeleryBeat
}

# Start Django server
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Starting Django Development Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "URLs:" -ForegroundColor White
Write-Host "  - Home:  http://127.0.0.1:$Port/" -ForegroundColor Cyan
Write-Host "  - Admin: http://127.0.0.1:$Port/admin/" -ForegroundColor Cyan
Write-Host "  - API:   http://127.0.0.1:$Port/api/" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Gray
Write-Host ""

& $PythonExe manage.py runserver $Port
