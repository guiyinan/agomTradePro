@echo off
REM AgomTradePro Development Launcher Menu
REM Version: 3.5
REM Updated: 2026-02-01

setlocal enabledelayedexpansion

:menu
cls
echo.
echo ========================================
echo   AgomTradePro Development Launcher
echo ========================================
echo.
echo   Select startup mode:
echo.
echo   [1] Quick Start (SQLite only)
echo   [2] SQLite + Redis + Celery
echo   [3] Docker Mode (PostgreSQL + Redis + Celery)
echo   [4] Docker Mode - No Celery
echo   [5] Activate venv only
echo   [6] Stop all services
echo   [7] Quick Start + URL/API Scan
echo   [8] Quick Start (Verbose Django Logs)
echo   [0] Exit
echo.
echo ========================================
echo.

set /p choice="Enter choice [0-8]: "

if "%choice%"=="1" goto quick
if "%choice%"=="2" goto sqlite_redis_celery
if "%choice%"=="3" goto docker
if "%choice%"=="4" goto docker_no_celery
if "%choice%"=="5" goto venv
if "%choice%"=="6" goto stop
if "%choice%"=="7" goto quick_scan
if "%choice%"=="8" goto quick_verbose
if "%choice%"=="0" goto end
goto menu

:quick
set PYTHONUNBUFFERED=1
set DJANGO_LOG_LEVEL=INFO
call scripts\dev.bat
goto menu

:sqlite_redis_celery
set PYTHONUNBUFFERED=1
set DJANGO_LOG_LEVEL=INFO
call scripts\docker-dev.bat --sqlite
goto menu

:docker
set PYTHONUNBUFFERED=1
set DJANGO_LOG_LEVEL=INFO
call scripts\docker-dev.bat
goto menu

:docker_no_celery
set PYTHONUNBUFFERED=1
set DJANGO_LOG_LEVEL=INFO
call scripts\docker-dev.bat --no-celery --no-beat
goto menu

:venv
if not exist "agomtradepro\Scripts\activate.bat" (
    echo.
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv agomtradepro
    echo.
    pause
    goto menu
)
call agomtradepro\Scripts\activate.bat
echo.
echo ========================================
echo   Virtual Environment Activated
echo ========================================
echo.
echo Common Commands:
echo   python manage.py runserver       - Start dev server
echo   python manage.py makemigrations  - Create migrations
echo   python manage.py migrate         - Run migrations
echo   python manage.py createsuperuser  - Create admin
echo   python manage.py shell           - Django Shell
echo   deactivate                       - Exit venv
echo.
cmd /k
goto menu

:stop
call scripts\stop-dev.bat
goto menu

:quick_scan
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev-smoke.ps1
goto menu

:quick_verbose
set PYTHONUNBUFFERED=1
set DJANGO_LOG_LEVEL=DEBUG
echo.
echo [INFO] Verbose Django logging enabled ^(DJANGO_LOG_LEVEL=DEBUG^)
call scripts\dev.bat
goto menu

:end
echo.
echo Goodbye!
timeout /t 2 >nul
exit /b 0
