@echo off
setlocal enabledelayedexpansion
title LocalRouter - Installation
cd /d "%~dp0"

echo ========================================
echo   LocalRouter - Installation
echo ========================================
echo.

REM ---- [1/5] Find Python (3.10+) ----
set "PYTHON="
python --version >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    set "PYTHON=python"
) else (
    py -3 --version >nul 2>&1
    if !ERRORLEVEL! EQU 0 set "PYTHON=py -3"
)
if not defined PYTHON (
    echo [ERROR] Python 3 not found. Please install Python 3.10+ from https://www.python.org/downloads/
    goto :fail
)

for /f "tokens=2" %%v in ('!PYTHON! --version 2^>^&1') do set "PY_VER=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)
if not defined PY_MAJOR (
    echo [ERROR] Could not determine Python version.
    goto :fail
)
if !PY_MAJOR! LSS 3 (
    echo [ERROR] Python 3.10+ required, found !PY_VER!
    goto :fail
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 10 (
    echo [ERROR] Python 3.10+ required, found !PY_VER!
    goto :fail
)
echo [1/5] Python OK: Python !PY_VER!

REM ---- [2/5] Check Node.js (18+) and npm ----
where node >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Node.js not found. Please install Node.js 18+ from https://nodejs.org/
    goto :fail
)
where npm >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] npm not found. Please reinstall Node.js 18+ from https://nodejs.org/
    goto :fail
)
for /f %%v in ('node --version') do set "NODE_VER=%%v"
set "NODE_VER=!NODE_VER:v=!"
for /f "tokens=1 delims=." %%a in ("!NODE_VER!") do set "NODE_MAJOR=%%a"
if !NODE_MAJOR! LSS 18 (
    echo [ERROR] Node.js 18+ required, found v!NODE_VER!
    goto :fail
)
echo [2/5] Node.js OK: v!NODE_VER!

REM ---- [3/5] Backend: venv + dependencies + database ----
echo [3/5] Setting up backend (venv, dependencies, database)...
!PYTHON! scripts\init_db.py
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] Backend setup failed. Check the output above.
    goto :fail
)

REM ---- [4/5] Frontend: npm install ----
if exist "frontend\node_modules" (
    echo [4/5] Frontend dependencies already installed, skipping npm install.
) else (
    echo [4/5] Installing frontend dependencies (npm install^)...
    pushd frontend
    call npm install
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] npm install failed. Check the output above.
        goto :fail
    )
    popd
)

REM ---- [5/5] Root .env ----
if exist ".env" (
    echo [5/5] Root .env already exists, skipping.
) else (
    copy ".env.example" ".env" >nul
    echo [5/5] Created .env from .env.example.
)

echo.
echo ========================================
echo   Installation complete!
echo ========================================
echo.
echo Next steps:
echo   start.bat      Start all services
echo   scripts\manage.bat status     Show service status
echo.
echo   Frontend: http://localhost:12001
echo   Backend:  http://localhost:12002
echo   API docs: http://localhost:12002/docs
echo.
pause
exit /b 0

:fail
echo.
echo Installation failed. Fix the issues above and re-run install.bat.
pause
exit /b 1
