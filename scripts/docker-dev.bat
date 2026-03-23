@echo off
REM AgomTradePro Docker Development Launcher
REM Version: 3.5
REM Updated: 2026-02-01
REM
REM Usage:
REM   docker-dev.bat [--sqlite] [--no-celery] [--no-beat] [port]

setlocal enabledelayedexpansion

REM Configuration
set PYTHON_EXEC=agomtradepro\Scripts\python.exe
set DJANGO_PORT=8000
set START_CELERY=1
set START_BEAT=1
set SQLITE_MODE=0

REM Parse arguments
:parse_args
if "%~1"=="--sqlite" (
    set SQLITE_MODE=1
    shift
    goto parse_args
)
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
echo   AgomTradePro Docker Dev Launcher
echo ====================================
echo.

REM ========== 1. Check Virtual Environment ==========
echo [1/5] Checking virtual environment...
if not exist "%PYTHON_EXEC%" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv agomtradepro
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

REM Auto-cleanup stale containers before starting
call :cleanup_stale_containers

if %SQLITE_MODE%==1 (
    echo [3/5] Starting Docker services - Redis only, SQLite mode...
    docker-compose -f docker-compose-dev.yml up -d redis
    if errorlevel 1 (
        echo [ERROR] Failed to start Redis service!
        pause
        exit /b 1
    )
    echo [OK] Redis service started
    set DATABASE_URL=sqlite:///db.sqlite3
    set REDIS_URL=redis://127.0.0.1:6379/0
    echo [INFO] SQLite mode enabled
) else (
    echo [3/5] Starting Docker services - PostgreSQL + Redis...
    docker-compose -f docker-compose-dev.yml up -d
    if errorlevel 1 (
        echo [ERROR] Failed to start Docker services!
        pause
        exit /b 1
    )
    echo [OK] Docker services started
)

if %SQLITE_MODE%==0 (
    REM Wait for PostgreSQL (max 30 seconds)
    echo [INFO] Waiting for PostgreSQL to be ready...
    call :wait_postgres_ready
    if errorlevel 1 (
        echo [ERROR] PostgreSQL failed to start after 30 seconds!
        pause
        exit /b 1
    )
    echo [OK] PostgreSQL ready
)

REM Wait for Redis (auto-recover on failure)
echo [INFO] Waiting for Redis to be ready...
set REDIS_ATTEMPT=0
:wait_redis_outer
set /a REDIS_ATTEMPT+=1
if %REDIS_ATTEMPT% GTR 2 (
    echo [ERROR] Redis failed after 2 recovery attempts!
    pause
    exit /b 1
)
set REDIS_RETRIES=0
:wait_redis
timeout /t 1 >nul
docker exec agomtradepro_redis_dev redis-cli ping >nul 2>&1
if not errorlevel 1 goto redis_ready
set /a REDIS_RETRIES+=1
if %REDIS_RETRIES% GEQ 15 (
    echo [WARN] Redis not responding, auto-recovering...
    call :recover_redis
    goto wait_redis_outer
)
goto :wait_redis
:redis_ready
echo [OK] Redis ready
echo.

REM ========== 4. Database Migration ==========
echo [4/5] Running database migrations...
"%PYTHON_EXEC%" manage.py migrate
if errorlevel 1 (
    echo [WARN] Migration issues, retrying...
    "%PYTHON_EXEC%" manage.py migrate --skip-checks
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

REM ========== 5. Start Celery Worker ==========
if %START_CELERY%==1 (
    call :kill_existing_celery_worker
    echo [5/5] Starting Celery Worker...
    start "Celery Worker" cmd /k "%PYTHON_EXEC% -m celery -A core worker -l info --pool=solo"
    timeout /t 2 >nul
    echo [OK] Celery Worker started
)

REM ========== 6. Start Celery Beat ==========
if %START_BEAT%==1 (
    call :kill_existing_celery_beat
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
if %SQLITE_MODE%==1 (
    echo   - Redis:              Docker container
    echo   - SQLite DB:          local file ^(db.sqlite3^)
) else (
    echo   - PostgreSQL + Redis: Docker containers
)
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

goto :eof

:wait_postgres_ready
set PG_RETRIES=0
:wait_pg_loop
timeout /t 2 >nul
docker exec agomtradepro_postgres_dev pg_isready -U agomtradepro -d agomtradepro >nul 2>&1
if not errorlevel 1 exit /b 0
set /a PG_RETRIES+=1
if %PG_RETRIES% GEQ 15 (
    echo [WARN] PostgreSQL not responding, attempting recovery...
    docker rm -f agomtradepro_postgres_dev >nul 2>&1
    docker-compose -f docker-compose-dev.yml up -d postgres
    set PG_RETRIES=0
    set /a PG_RECOVER+=1
    if !PG_RECOVER! GEQ 2 exit /b 1
)
goto :wait_pg_loop

:cleanup_stale_containers
REM Remove containers stuck in Created/Exited state to free ports
for %%C in (agomtradepro_redis_dev agomtradepro_postgres_dev) do (
    for /f "tokens=*" %%S in ('docker inspect -f "{{.State.Status}}" %%C 2^>nul') do (
        if "%%S"=="created" (
            echo [INFO] Removing stale container %%C ^(status: created^)
            docker rm -f %%C >nul 2>&1
        )
        if "%%S"=="exited" (
            echo [INFO] Removing exited container %%C
            docker rm -f %%C >nul 2>&1
        )
    )
)
exit /b 0

:recover_redis
echo [INFO] Stopping and removing Redis container...
docker rm -f agomtradepro_redis_dev >nul 2>&1
timeout /t 2 >nul
echo [INFO] Restarting Redis container...
docker-compose -f docker-compose-dev.yml up -d redis
timeout /t 2 >nul
exit /b 0

:kill_existing_celery_worker
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $all=Get-CimInstance Win32_Process; foreach($p in $all){ if($p.Name -eq 'python.exe' -and $p.CommandLine -like '*celery -A core worker*'){ Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } }" >nul 2>&1
taskkill /f /t /fi "IMAGENAME eq cmd.exe" /fi "WINDOWTITLE eq Celery Worker" >nul 2>&1
echo [INFO] Cleared existing Celery Worker processes
exit /b 0

:kill_existing_celery_beat
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $all=Get-CimInstance Win32_Process; foreach($p in $all){ if($p.Name -eq 'python.exe' -and $p.CommandLine -like '*celery -A core beat*'){ Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } }" >nul 2>&1
taskkill /f /t /fi "IMAGENAME eq cmd.exe" /fi "WINDOWTITLE eq Celery Beat" >nul 2>&1
echo [INFO] Cleared existing Celery Beat processes
exit /b 0
