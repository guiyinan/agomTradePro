@echo off
REM AgomSAAF Virtual Environment Activation Script

echo ====================================
echo AgomSAAF Virtual Environment
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
echo [INFO] Activating virtual environment...
call agomsaaf\Scripts\activate.bat

echo.
echo ====================================
echo Virtual Environment Activated
echo ====================================
echo.
echo Common Commands:
echo   python manage.py runserver       - Start dev server
echo   python manage.py makemigrations  - Create migrations
echo   python manage.py migrate          - Run migrations
echo   python manage.py createsuperuser  - Create superuser
echo   python manage.py shell            - Django Shell
echo   pip install [package]             - Install package
echo   deactivate                        - Exit virtual environment
echo.
echo ====================================
echo.

REM Keep command prompt open
cmd /k
