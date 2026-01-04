@echo off
REM AgomSAAF - Docker (PostgreSQL + Redis) + Celery + Django Startup Script

setlocal enabledelayedexpansion

REM Configuration
set PYTHON_EXEC=agomsaaf\Scripts\python.exe
set REDIS_PORT=6379
set DJANGO_PORT=8000
set COMPOSE_FILE=docker-compose-dev.yml

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

REM ========== 2. Check Docker ==========
echo [INFO] Checking Docker...
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
echo [INFO] Checking Docker containers...
docker ps --filter "name=agomsaaf_postgres_dev" --format "{{.Names}}" | findstr "agomsaaf_postgres_dev" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Starting Docker services (PostgreSQL + Redis)...
    docker-compose -f %COMPOSE_FILE% up -d
    if errorlevel 1 (
        echo [ERROR] Failed to start Docker services!
        pause
        exit /b 1
    )
    echo [OK] Docker services starting
) else (
    echo [OK] Docker containers already running
)

REM Wait for PostgreSQL to be ready
echo [INFO] Waiting for PostgreSQL to be ready...
:wait_postgres
timeout /t 2 >nul
docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf -d agomsaaf >nul 2>&1
if errorlevel 1 goto :wait_postgres
echo [OK] PostgreSQL ready

REM Wait for Redis to be ready
echo [INFO] Waiting for Redis to be ready...
:wait_redis
timeout /t 1 >nul
docker exec agomsaaf_redis_dev redis-cli ping >nul 2>&1
if errorlevel 1 goto :wait_redis
echo [OK] Redis ready
echo.

REM ========== 4. Database Migration ==========
echo [INFO] Checking database migrations...
"%PYTHON_EXEC%" manage.py migrate --skip-checks
if errorlevel 1 (
    echo [WARN] Migration issues, forcing migration...
    "%PYTHON_EXEC%" manage.py migrate
)
echo [OK] Database ready
echo.

REM ========== 5. Start Celery Worker ==========
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
