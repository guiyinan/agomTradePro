@echo off
REM AgomSAAF Docker Development Launcher
REM Version: 3.5
REM Updated: 2026-02-01
REM
REM Usage:
REM   docker-dev.bat [--no-celery] [--no-beat] [port]

setlocal enabledelayedexpansion

REM Configuration
set PYTHON_EXEC=agomsaaf\Scripts\python.exe
set DJANGO_PORT=8000
set START_CELERY=1
set START_BEAT=1

REM Parse arguments
:parse_args
if "%~1"=="--no-celery" (
    set START_CELERY=0
    shift
    goto parse_args
)
if "%~1"=="--no-beat" (
    set START_BEAT=0
    shift
    goto parse_args
)
if "%~1"=="" goto end_parse
set DJANGO_PORT=%~1
shift
goto end_parse
:end_parse

REM Header
echo.
echo ====================================
echo   AgomSAAF Docker Dev Launcher
echo ====================================
echo.

REM ========== 1. Check Virtual Environment ==========
echo [1/5] Checking virtual environment...
if not exist "%PYTHON_EXEC%" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv agomsaaf
    pause
    exit /b 1
)
echo [OK] Virtual environment ready
echo.

REM ========== 2. Check Docker ==========
echo [2/5] Checking Docker...
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker not installed or not in PATH!
    echo Please install Docker Desktop first.
    pause
    exit /b 1
)
echo [OK] Docker found
echo.

REM ========== 3. Start Docker Services ==========
echo [3/5] Starting Docker services (PostgreSQL + Redis)...
docker-compose -f docker-compose-dev.yml up -d
if errorlevel 1 (
    echo [ERROR] Failed to start Docker services!
    pause
    exit /b 1
)
echo [OK] Docker services started

REM Wait for PostgreSQL
echo [INFO] Waiting for PostgreSQL to be ready...
:wait_postgres
timeout /t 2 >nul
docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf -d agomsaaf >nul 2>&1
if errorlevel 1 goto :wait_postgres
echo [OK] PostgreSQL ready

REM Wait for Redis
echo [INFO] Waiting for Redis to be ready...
:wait_redis
timeout /t 1 >nul
docker exec agomsaaf_redis_dev redis-cli ping >nul 2>&1
if errorlevel 1 goto :wait_redis
echo [OK] Redis ready
echo.

REM ========== 4. Database Migration ==========
echo [4/5] Running database migrations...
"%PYTHON_EXEC%" manage.py migrate --skip-checks
if errorlevel 1 (
    echo [WARN] Migration issues, retrying...
    "%PYTHON_EXEC%" manage.py migrate
)
echo [OK] Database ready
echo.

REM ========== 5. Start Celery Worker ==========
if %START_CELERY%==1 (
    echo [5/5] Starting Celery Worker...
    start "Celery Worker" cmd /k "%PYTHON_EXEC% -m celery -A core worker -l info --pool=solo"
    timeout /t 2 >nul
    echo [OK] Celery Worker started
)

REM ========== 6. Start Celery Beat ==========
if %START_BEAT%==1 (
    echo [INFO] Starting Celery Beat...
    start "Celery Beat" cmd /k "%PYTHON_EXEC% -m celery -A core beat -l info"
    timeout /t 2 >nul
    echo [OK] Celery Beat started
)

REM ========== 7. Start Django ==========
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
echo   - PostgreSQL + Redis:  Docker containers
if %START_CELERY%==1 (
    echo   - Celery Worker:      separate window
)
if %START_BEAT%==1 (
    echo   - Celery Beat:        separate window
)
echo   - Django:             current window
echo.
echo Press Ctrl+C to stop Django server
echo Run "stop-dev.bat" to stop all services
echo.
echo ====================================
echo.

"%PYTHON_EXEC%" manage.py runserver %DJANGO_PORT%

echo.
echo Django server stopped
pause
