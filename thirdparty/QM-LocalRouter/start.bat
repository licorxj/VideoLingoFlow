@echo off
title LocalRouter Startup
cd /d "%~dp0"

echo ========================================
echo   LocalRouter - Starting Services
echo ========================================

REM Resolve project root (directory of this script) and locate venv Python
set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "PYTHON="
if exist "%BACKEND_DIR%\venv\Scripts\python.exe" (
    set "PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if !ERRORLEVEL! EQU 0 set "PYTHON=python"
)
if "%PYTHON%"=="" (
    echo ERROR: Python not found. Please run scripts\init_db.bat first to create the venv.
    pause
    exit /b 1
)

REM Start Service Manager in background
echo [1/3] Starting Service Manager...
start "ServiceManager" /min "%PYTHON%" service_manager.py
timeout /t 2 /nobreak >nul

REM Start Backend
echo [2/3] Starting Backend...
cd backend
start "Backend" /min "%PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 12002
cd ..
timeout /t 3 /nobreak >nul

REM Start Frontend
echo [3/3] Starting Frontend...
cd frontend
start "Frontend" npm run dev
cd ..

echo ========================================
echo   All services started!
echo   Frontend: http://localhost:12001
echo   Backend:  http://localhost:12002
echo   Manager:  http://localhost:12003
echo ========================================
echo.
echo Press any key to exit...
pause >nul
