@echo off
setlocal enabledelayedexpansion
title LocalRouter - Production Stop
cd /d "%~dp0"

set "PIDFILE=%~dp0run\prod-backend.pid"

if not exist "%PIDFILE%" (
    echo Production server is not running ^(no pid file^).
    exit /b 0
)

set /p PID=<"%PIDFILE%"
if "%PID%"=="" (
    echo Production server is not running ^(stale pid file^).
    del /f "%PIDFILE%" >nul 2>&1
    exit /b 0
)

tasklist /FI "PID eq %PID%" 2>nul | findstr /C:"%PID%" >nul
if !ERRORLEVEL! NEQ 0 (
    echo Production server is not running ^(stale pid %PID%^).
    del /f "%PIDFILE%" >nul 2>&1
    exit /b 0
)

echo Stopping production server ^(PID: %PID%^)...
taskkill /F /PID %PID% >nul 2>&1
del /f "%PIDFILE%" >nul 2>&1
echo Production server stopped.
exit /b 0
