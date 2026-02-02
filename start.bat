@echo off
REM AgomSAAF Development Launcher Menu
REM Version: 3.5
REM Updated: 2026-02-01

setlocal enabledelayedexpansion

:menu
cls
echo.
echo ========================================
echo   AgomSAAF Development Launcher
echo ========================================
echo.
echo   Select startup mode:
echo.
echo   [1] Quick Start (SQLite only)
echo   [2] Docker Mode (PostgreSQL + Redis + Celery)
echo   [3] Docker Mode - No Celery
echo   [4] Activate venv only
echo   [5] Stop all services
echo   [0] Exit
echo.
echo ========================================
echo.

set /p choice="Enter choice [0-5]: "

if "%choice%"=="1" goto quick
if "%choice%"=="2" goto docker
if "%choice%"=="3" goto docker_no_celery
if "%choice%"=="4" goto venv
if "%choice%"=="5" goto stop
if "%choice%"=="0" goto end
goto menu

:quick
call scripts\dev.bat
goto menu

:docker
call scripts\docker-dev.bat
goto menu

:docker_no_celery
call scripts\docker-dev.bat --no-celery --no-beat
goto menu

:venv
if not exist "agomsaaf\Scripts\activate.bat" (
    echo.
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv agomsaaf
    echo.
    pause
    goto menu
)
call agomsaaf\Scripts\activate.bat
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

:end
echo.
echo Goodbye!
timeout /t 2 >nul
exit /b 0
