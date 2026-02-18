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
set PYTHON_EXEC=
if /I "%CONDA_DEFAULT_ENV%"=="agomsaaf" (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if not defined PYTHON_EXEC set PYTHON_EXEC=%%i
    )
)
if not defined PYTHON_EXEC set PYTHON_EXEC=agomsaaf\Scripts\python.exe
set DJANGO_PORT=%1
if "%DJANGO_PORT%"=="" set DJANGO_PORT=8000

REM Header
echo.
echo ====================================
echo   AgomSAAF Quick Dev Launcher
echo ====================================
echo.

REM ========== 1. Check Virtual Environment ==========
echo [1/3] Checking Python runtime...
if not exist "%PYTHON_EXEC%" (
    echo [ERROR] Python runtime not found: %PYTHON_EXEC%
    echo Please activate conda env "agomsaaf" OR run: python -m venv agomsaaf
    pause
    exit /b 1
)
echo [OK] Python runtime ready: %PYTHON_EXEC%
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

echo [INFO] Ensuring macro periodic tasks...
"%PYTHON_EXEC%" manage.py setup_macro_daily_sync --hour 8 --minute 5
if errorlevel 1 (
    echo [WARN] Failed to configure macro periodic tasks
) else (
    echo [OK] Macro periodic tasks configured
)
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
