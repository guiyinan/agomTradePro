@echo off
REM AgomSAAF Development Environment Stop Script
REM Version: 3.5
REM Updated: 2026-02-01

setlocal enabledelayedexpansion

echo.
echo ====================================
echo   Stopping AgomSAAF Services
echo ====================================
echo.

REM ========== 1. Stop Docker Services ==========
echo [1/3] Stopping Docker containers...
docker --version >nul 2>&1
if errorlevel 1 (
    echo [SKIP] Docker not available
) else (
    docker-compose -f docker-compose-dev.yml down
    echo [OK] Docker containers stopped
)
echo.

REM ========== 2. Stop Celery Processes ==========
echo [2/3] Stopping Celery processes...

REM Use wmic to find processes with celery in command line
for /f "tokens=2" %%i in ('wmic process get ProcessId,CommandLine /format:csv ^| findstr /i "celery"') do (
    if not "%%i"=="ProcessId" (
        echo Stopping Celery process PID: %%i
        taskkill /PID %%i /F >nul 2>&1
    )
)
echo [OK] Celery processes stopped
echo.

REM ========== 3. Clean up Temporary Files ==========
echo [3/3] Cleaning up temporary files...
if exist "start_celery_worker.bat" del /q "start_celery_worker.bat"
if exist "start_celery_beat.bat" del /q "start_celery_beat.bat"
echo [OK] Cleanup complete
echo.

REM ========== 4. Django Reminder ==========
echo ====================================
echo   Stop Complete
echo ====================================
echo.
echo Note: Django server runs in the main window
echo       Press Ctrl+C in the Django window to stop it
echo.
pause
