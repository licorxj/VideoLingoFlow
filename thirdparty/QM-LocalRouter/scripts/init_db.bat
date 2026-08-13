@echo off
title LocalRouter - Database Initialization
cd /d "%~dp0"

echo ======================================================
echo   LocalRouter - Database Initialization
echo ======================================================
echo.

python init_db.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Database initialization failed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
pause
