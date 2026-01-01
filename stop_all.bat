@echo off
REM AgomSAAF - 停止所有开发服务

setlocal enabledelayedexpansion

echo.
echo ====================================
echo   AgomSAAF 服务停止器
echo ====================================
echo.

REM 停止 Redis（如果通过此脚本启动）
echo [1/3] 查找 Redis 进程...
for /f "tokens=2" %%i in ('tasklist ^| findstr /i "redis-server.exe"') do (
    echo 停止 Redis 进程 PID: %%i
    taskkill /PID %%i /F >nul 2>&1
)

REM 停止 Celery Worker
echo [2/3] 查找 Celery Worker 进程...
for /f "tokens=2" %%i in ('tasklist ^| findstr /i "celery.exe"') do (
    echo 停止 Celery 进程 PID: %%i
    taskkill /PID %%i /F >nul 2>&1
)

REM 停止 Django（通常在当前终端运行，这里查不到）
echo [3/3] Django 服务器需在对应窗口按 Ctrl+C 停止

echo.
echo ====================================
echo   后台服务已停止
echo ====================================
echo.
echo 注意：Django 服务器请在运行窗口按 Ctrl+C
echo.

pause
