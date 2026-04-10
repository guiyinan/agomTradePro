@echo off
REM AgomTradePro Local Environment Installer
REM Usage:
REM   install.bat
REM   install.bat --help

setlocal enabledelayedexpansion

if /I "%~1"=="--help" goto help
if /I "%~1"=="-h" goto help
if /I "%~1"=="/?" goto help

set VENV_DIR=agomtradepro
set PYTHON_CMD=
set INSTALL_MODE=runtime

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--dev" (
    set INSTALL_MODE=dev
    shift
    goto parse_args
)
echo [ERROR] Unknown option: %~1
echo Use install.bat --help
exit /b 1

:args_done
if /I "%INSTALL_MODE%"=="dev" (
    set REQUIREMENTS_FILE=requirements-dev.txt
    set INSTALL_LABEL=development dependencies
) else (
    set REQUIREMENTS_FILE=requirements-prod.txt
    set INSTALL_LABEL=runtime dependencies
)

echo.
echo ====================================
echo   AgomTradePro Local Installer
echo ====================================
echo.

call :detect_python
if not defined PYTHON_CMD (
    echo [ERROR] Python 3.11+ was not found in PATH.
    echo Install Python 3.11+ first, then rerun this script.
    exit /b 1
)

echo [1/5] Using Python: %PYTHON_CMD%

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [2/5] Creating virtual environment: %VENV_DIR%
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo [2/5] Virtual environment already exists: %VENV_DIR%
)

echo [3/5] Upgrading pip, setuptools, and wheel...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip toolchain.
    exit /b 1
)

echo [4/5] Installing %INSTALL_LABEL% from %REQUIREMENTS_FILE%...
"%VENV_DIR%\Scripts\python.exe" -m pip install -r "%REQUIREMENTS_FILE%"
if errorlevel 1 (
    echo [ERROR] Failed to install project requirements.
    exit /b 1
)

echo [5/5] Preparing local .env and secure keys...
"%VENV_DIR%\Scripts\python.exe" manage.py bootstrap_local_env
if errorlevel 1 (
    echo [ERROR] Failed to prepare local environment.
    exit /b 1
)

echo.
echo ====================================
echo   Installation Complete
echo ====================================
echo.
echo Next steps:
echo   1. Run start.bat
echo   2. Choose Quick Start
if /I "%INSTALL_MODE%"=="runtime" (
    echo.
    echo Tip:
    echo   For contributor tooling ^(pytest, Playwright, mypy, etc.^), run:
    echo   install.bat --dev
)
echo.
exit /b 0

:detect_python
for %%P in (py python) do (
    call :try_python %%P
    if defined PYTHON_CMD exit /b 0
)
exit /b 0

:try_python
set CANDIDATE=%~1
if /I "%CANDIDATE%"=="py" (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=py -3
        exit /b 0
    )
)

if /I "%CANDIDATE%"=="python" (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=python
        exit /b 0
    )
)
exit /b 0

:help
echo AgomTradePro Local Installer
echo.
echo This script:
echo   - creates the local virtual environment at agomtradepro\
echo   - upgrades pip, setuptools, and wheel
echo   - installs runtime dependencies by default ^(requirements-prod.txt^)
echo   - creates .env and generates secure local keys
echo.
echo Options:
echo   --dev    Install development dependencies ^(pytest, Playwright, mypy, etc.^)
echo.
echo After it finishes, run start.bat and choose Quick Start.
exit /b 0
