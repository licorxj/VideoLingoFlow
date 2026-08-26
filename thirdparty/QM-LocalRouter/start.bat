@echo off
title LocalRouter Startup
cd /d "%~dp0"

echo ========================================
echo   LocalRouter - Starting Services
echo ========================================

REM Start Service Manager in background
echo [1/3] Starting Service Manager...
start "ServiceManager" /min "Y:\ApiRouteManeger\backend\venv\Scripts\python.exe" service_manager.py
timeout /t 2 /nobreak >nul

REM Start Backend
echo [2/3] Starting Backend...
cd backend
start "Backend" /min "Y:\ApiRouteManeger\backend\venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 12002
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
