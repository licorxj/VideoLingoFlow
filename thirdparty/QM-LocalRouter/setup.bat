@echo off
setlocal enabledelayedexpansion
title LocalRouter - First-time Setup
cd /d "%~dp0"

echo ========================================
echo   LocalRouter - First-time Setup
echo ========================================
echo.

REM Windows counterpart of setup.sh.
REM Run right after cloning the repository: pulls the latest code and
REM performs the full environment installation (venv, backend deps,
REM database init, frontend npm install).

where git >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] git not found. Please install Git for Windows first.
    pause
    exit /b 1
)
if not exist ".git" (
    echo [ERROR] Run this script inside the cloned repository directory.
    pause
    exit /b 1
)

echo [1/2] Pulling latest code (git pull --ff-only^)...
git pull --ff-only
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] git pull failed. Check the output above.
    pause
    exit /b 1
)

echo.
echo [2/2] Installing environment and dependencies...
call "%~dp0install.bat"
exit /b !ERRORLEVEL!
