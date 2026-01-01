@echo off
REM AgomSAAF - Redis + Celery + Django Startup Script

setlocal enabledelayedexpansion

REM Configuration
set PYTHON_EXEC=agomsaaf\Scripts\python.exe
set REDIS_PORT=6379
set DJANGO_PORT=8000

echo.
echo ====================================
echo   AgomSAAF Dev Environment Launcher
echo ====================================
echo.

REM ========== 1. Check Virtual Environment ==========
echo [INFO] Checking virtual environment...
if not exist "%PYTHON_EXEC%" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv agomsaaf
    pause
    exit /b 1
)
echo [OK] Virtual environment ready
echo.

REM ========== 2. Check Redis ==========
echo [INFO] Checking Redis...
where redis-server >nul 2>&1
if errorlevel 1 (
    echo [WARN] Redis not installed or not in PATH
    echo.
    echo Options:
    echo   1. I have Redis installed, start it manually
    echo   2. Skip Redis (Celery will not start)
    echo   3. Cancel
    echo.
    choice /c 123 /n /m "Select [1-3]: "
    if errorlevel 3 exit /b 1
    if errorlevel 2 set SKIP_CELERY=1
    if errorlevel 1 goto :run_django
) else (
    REM Check if Redis is running
    redis-cli -p %REDIS_PORT% ping >nul 2>&1
    if errorlevel 1 (
        echo [INFO] Starting Redis...
        start "Redis Server" redis-server --port %REDIS_PORT%
        timeout /t 2 >nul
        redis-cli -p %REDIS_PORT% ping >nul 2>&1
        if errorlevel 1 (
            echo [ERROR] Redis failed to start!
            pause
            exit /b 1
        )
        echo [OK] Redis started (port %REDIS_PORT%)
    ) else (
        echo [OK] Redis already running
    )
)
echo.

REM ========== 3. Database Migration ==========
echo [INFO] Checking database migrations...
"%PYTHON_EXEC%" manage.py migrate --skip-checks
if errorlevel 1 (
    echo [WARN] Migration issues, forcing migration...
    "%PYTHON_EXEC%" manage.py migrate
)
echo [OK] Database ready
echo.

REM ========== 4. Start Celery Worker ==========
if not defined SKIP_CELERY (
    echo [INFO] Starting Celery Worker...
    start "Celery Worker" cmd /k "%PYTHON_EXEC% -m celery -A core worker -l info --pool=solo"
    timeout /t 2 >nul
    echo [OK] Celery Worker started
    echo.
)

REM ========== 5. Start Celery Beat (Optional) ==========
echo.
echo Start Celery Beat (scheduler for periodic tasks)?
echo   1. Start Beat
echo   2. Skip Beat
echo.
choice /c 12 /n /m "Select [1-2]: "
if errorlevel 1 (
    echo [INFO] Starting Celery Beat...
    start "Celery Beat" cmd /k "%PYTHON_EXEC% -m celery -A core beat -l info"
    timeout /t 2 >nul
    echo [OK] Celery Beat started
)

REM ========== 6. Start Django ==========
:run_django
echo.
echo ====================================
echo   All services started!
echo ====================================
echo.
echo URLs:
echo   - Home:    http://127.0.0.1:%DJANGO_PORT%/
echo   - Admin:   http://127.0.0.1:%DJANGO_PORT%/admin/
echo   - API:     http://127.0.0.1:%DJANGO_PORT%/api/
echo.
echo Service windows:
if not defined SKIP_CELERY (
    echo   - Redis:     separate window
    echo   - Celery:    separate window
)
echo   - Django:    current window
echo.
echo Press Ctrl+C to stop Django server
echo (Close other windows manually)
echo.
echo ====================================
echo.

"%PYTHON_EXEC%" manage.py runserver %DJANGO_PORT%

echo.
echo Django server stopped
pause
