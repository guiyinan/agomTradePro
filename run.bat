@echo off
REM AgomSAAF Development Server Launcher

echo ====================================
echo AgomSAAF Development Server
echo ====================================
echo.

REM Check if virtual environment exists
if not exist "agomsaaf\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv agomsaaf
    pause
    exit /b 1
)

REM Activate virtual environment
echo [1/4] Activating virtual environment...
call agomsaaf\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment!
    pause
    exit /b 1
)
echo [OK] Virtual environment activated
echo.

REM Check database migrations
echo [2/4] Checking database migrations...
python manage.py migrate --skip-checks
if errorlevel 1 (
    echo [WARNING] Migration issues, trying force migrate...
    python manage.py migrate
)
echo [OK] Database ready
echo.

REM Check if superuser exists
echo [3/4] Checking admin account...
python -c "from django.contrib.auth import get_user_model; User = get_user_model(); print(User.objects.filter(is_superuser=True).exists())" 2>nul
if errorlevel 1 (
    echo [INFO] First run, consider creating admin account
    echo Run: python manage.py createsuperuser
)
echo [OK] Admin check complete
echo.

REM Start development server
echo [4/4] Starting development server...
echo ====================================
echo Access URLs:
echo   - Home: http://127.0.0.1:8000/
echo   - Admin: http://127.0.0.1:8000/admin/
echo ====================================
echo Press Ctrl+C to stop server
echo.

python manage.py runserver

REM Server stopped
echo.
echo Server stopped
pause
