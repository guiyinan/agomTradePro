@echo off
REM AgomSAAF Quick Development Launcher
REM Version: 3.5
REM Updated: 2026-02-01
REM
REM Usage:
REM   dev.bat [port]
REM   dev.bat 8001    # Start on port 8001

setlocal enabledelayedexpansion

REM Configuration
set PYTHON_EXEC=agomsaaf\Scripts\python.exe
set DJANGO_PORT=%1
if "%DJANGO_PORT%"=="" set DJANGO_PORT=8000

REM Header
echo.
echo ====================================
echo   AgomSAAF Quick Dev Launcher
echo ====================================
echo.

REM ========== 1. Check Virtual Environment ==========
echo [1/3] Checking virtual environment...
if not exist "%PYTHON_EXEC%" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv agomsaaf
    pause
    exit /b 1
)
echo [OK] Virtual environment ready
echo.

REM ========== 2. Run Migrations ==========
echo [2/3] Running database migrations...
"%PYTHON_EXEC%" manage.py migrate --skip-checks
if errorlevel 1 (
    echo [WARN] Migration issues, retrying...
    "%PYTHON_EXEC%" manage.py migrate
)
echo [OK] Database ready
echo.

REM ========== 3. Start Django ==========
echo [3/3] Starting Django development server...
echo ====================================
echo Access URLs:
echo   - Home:  http://127.0.0.1:%DJANGO_PORT%/
echo   - Admin: http://127.0.0.1:%DJANGO_PORT%/admin/
echo ====================================
echo Press Ctrl+C to stop server
echo.

"%PYTHON_EXEC%" manage.py runserver %DJANGO_PORT%

REM Server stopped
echo.
echo Server stopped
pause
