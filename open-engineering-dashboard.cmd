@echo off
setlocal EnableExtensions DisableDelayedExpansion
title AgomTradePro Engineering Dashboard

pushd "%~dp0"
if errorlevel 1 goto directory_error

where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js 22 or newer is required on PATH.
    goto failed
)
where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: Git is required on PATH.
    goto failed
)

echo Refreshing the engineering dashboard from the latest commit...
node "scripts\engineering-dashboard\build.mjs"
if errorlevel 1 (
    echo ERROR: Dashboard generation failed. The previous HTML was not opened.
    goto failed
)

if not exist "reports\engineering-progress\index.html" (
    echo ERROR: The generated dashboard could not be found.
    goto failed
)

echo Opening the dashboard in your default browser...
start "" "%CD%\reports\engineering-progress\index.html"
if errorlevel 1 (
    echo ERROR: Could not open the dashboard. Open reports\engineering-progress\index.html manually.
    goto failed
)
popd
exit /b 0

:failed
popd
echo.
pause
exit /b 1

:directory_error
echo ERROR: Could not access the repository directory.
pause
exit /b 1
