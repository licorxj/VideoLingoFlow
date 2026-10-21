@echo off
title LocalRouter Startup
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo   LocalRouter - Starting Services
echo ========================================
echo.

REM Find Python (mirrors install.bat / start.sh)
set "PYTHON="
if exist "backend\venv\Scripts\python.exe" (
    set "PYTHON=backend\venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if !ERRORLEVEL! EQU 0 set "PYTHON=python"
)
if not defined PYTHON (
    echo [ERROR] Python not found. Please install Python 3.10+ and re-run.
    pause
    exit /b 1
)

REM First run: create venv, install deps, init database (parity with start.sh)
if not exist "backend\venv\Scripts\python.exe" (
    echo [setup] Python environment not found, running first-time setup...
    "%PYTHON%" scripts\init_db.py
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] First-time setup failed. Run install.bat for details.
        pause
        exit /b 1
    )
) else (
    echo [setup] Python environment ready, skipping setup.
)

REM Start all services in background via the shared manager (parity with start.sh -> manage.sh)
call "%~dp0scripts\manage.bat" start
pause
exit /b 0
