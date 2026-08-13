@echo off
title LocalRouter Service Manager
cd /d "%~dp0"
setlocal enabledelayedexpansion

set "PROJECT_ROOT=%~dp0.."
set "RUN_DIR=%PROJECT_ROOT%\run"
set "BACKEND_DIR=%PROJECT_ROOT%\backend"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"
set "BACKEND_PORT=%BACKEND_PORT%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=12002"
set "FRONTEND_PORT=%FRONTEND_PORT%"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=12001"
set "MANAGER_PORT=%MANAGER_PORT%"
if "%MANAGER_PORT%"=="" set "MANAGER_PORT=12003"

set "BACKEND_PIDFILE=%RUN_DIR%\backend.pid"
set "FRONTEND_PIDFILE=%RUN_DIR%\frontend.pid"
set "MANAGER_PIDFILE=%RUN_DIR%\manager.pid"

if not exist "%RUN_DIR%" mkdir "%RUN_DIR%"

:: Find venv Python
set "PYTHON="
if exist "%BACKEND_DIR%\venv\Scripts\python.exe" (
    set "PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "PYTHON=python"
    )
)

goto :main

::------------------------------------------------------
:is_running <pidfile>
::------------------------------------------------------
setlocal
set "pid_file=%~1"
if not exist "%pid_file%" exit /b 1
set /p pid=<"%pid_file%"
if "%pid%"=="" exit /b 1
tasklist /FI "PID eq %pid%" 2>nul | findstr /C:"%pid%" >nul
exit /b %ERRORLEVEL%

::------------------------------------------------------
:write_pid <pidfile>
::------------------------------------------------------
echo %2 > %1
exit /b 0

::------------------------------------------------------
:cleanup_pid <pidfile>
::------------------------------------------------------
if exist "%~1" del /f "%~1"
exit /b 0

::------------------------------------------------------
:backend_start
::------------------------------------------------------
call :is_running "%BACKEND_PIDFILE%"
if !ERRORLEVEL! EQU 0 (
    set /p pid=<"%BACKEND_PIDFILE%"
    echo Backend is already running (PID: !pid!)
    exit /b 0
)
echo Starting Backend (uvicorn) on port %BACKEND_PORT%...
cd "%BACKEND_DIR%"
start "Backend" /min "%PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT%
cd "%PROJECT_ROOT%"
echo   Backend started
exit /b 0

::------------------------------------------------------
:backend_stop
::------------------------------------------------------
call :is_running "%BACKEND_PIDFILE%"
if !ERRORLEVEL! NEQ 0 (
    echo Backend is not running
    call :cleanup_pid "%BACKEND_PIDFILE%"
    exit /b 0
)
set /p pid=<"%BACKEND_PIDFILE%"
echo Stopping Backend (PID: !pid!)...
taskkill /F /PID !pid! >nul 2>&1
call :cleanup_pid "%BACKEND_PIDFILE%"
echo   Backend stopped
exit /b 0

::------------------------------------------------------
:frontend_start
::------------------------------------------------------
cd "%FRONTEND_DIR%"
if not exist "%FRONTEND_DIR%\node_modules" (
    echo Installing frontend dependencies...
    call npm install
)
cd "%PROJECT_ROOT%"

call :is_running "%FRONTEND_PIDFILE%"
if !ERRORLEVEL! EQU 0 (
    set /p pid=<"%FRONTEND_PIDFILE%"
    echo Frontend is already running (PID: !pid!)
    exit /b 0
)
echo Starting Frontend (Vite) on port %FRONTEND_PORT%...
cd "%FRONTEND_DIR%"
start "Frontend" /min cmd /c "set FRONTEND_PORT=%FRONTEND_PORT% && npm run dev"
cd "%PROJECT_ROOT%"
echo   Frontend started
exit /b 0

::------------------------------------------------------
:frontend_stop
::------------------------------------------------------
call :is_running "%FRONTEND_PIDFILE%"
if !ERRORLEVEL! NEQ 0 (
    echo Frontend is not running
    call :cleanup_pid "%FRONTEND_PIDFILE%"
    exit /b 0
)
set /p pid=<"%FRONTEND_PIDFILE%"
echo Stopping Frontend (PID: !pid!)...
taskkill /F /PID !pid! >nul 2>&1
call :cleanup_pid "%FRONTEND_PIDFILE%"
echo   Frontend stopped
exit /b 0

::------------------------------------------------------
:manager_start
::------------------------------------------------------
call :is_running "%MANAGER_PIDFILE%"
if !ERRORLEVEL! EQU 0 (
    set /p pid=<"%MANAGER_PIDFILE%"
    echo Service Manager is already running (PID: !pid!)
    exit /b 0
)
if "%PYTHON%"=="" (
    echo ERROR: Python not found
    exit /b 1
)
echo Starting Service Manager on port %MANAGER_PORT%...
start "ServiceManager" /min "%PYTHON%" "%PROJECT_ROOT%\service_manager.py"
echo   Service Manager started
exit /b 0

::------------------------------------------------------
:manager_stop
::------------------------------------------------------
call :is_running "%MANAGER_PIDFILE%"
if !ERRORLEVEL! NEQ 0 (
    echo Service Manager is not running
    call :cleanup_pid "%MANAGER_PIDFILE%"
    exit /b 0
)
set /p pid=<"%MANAGER_PIDFILE%"
echo Stopping Service Manager (PID: !pid!)...
taskkill /F /PID !pid! >nul 2>&1
call :cleanup_pid "%MANAGER_PIDFILE%"
echo   Service Manager stopped
exit /b 0

::------------------------------------------------------
:main
::------------------------------------------------------
if "%1"=="" goto help

if /I "%1"=="start" (
    echo Starting all services...
    call :manager_start
    call :backend_start
    call :frontend_start
    echo.
    echo All services started!
    echo   Backend:  http://localhost:%BACKEND_PORT%
    echo   Frontend: http://localhost:%FRONTEND_PORT%
    echo   Manager:  http://localhost:%MANAGER_PORT%
    echo   Docs:     http://localhost:%BACKEND_PORT%/docs
    goto end
)

if /I "%1"=="stop" (
    echo Stopping all services...
    call :frontend_stop
    call :backend_stop
    call :manager_stop
    echo All services stopped
    goto end
)

if /I "%1"=="restart" (
    call :main stop
    timeout /t 2 >nul
    call :main start
    goto end
)

if /I "%1"=="status" (
    echo Service status:
    set "name=Backend"
    set "file=%BACKEND_PIDFILE%"
    call :is_running "!file!" && echo   !name! RUNNING || echo   !name! STOPPED
    set "name=Frontend"
    set "file=%FRONTEND_PIDFILE%"
    call :is_running "!file!" && echo   !name! RUNNING || echo   !name! STOPPED
    set "name=Manager"
    set "file=%MANAGER_PIDFILE%"
    call :is_running "!file!" && echo   !name! RUNNING || echo   !name! STOPPED
    goto end
)

if /I "%1"=="backend-start" call :backend_start&goto end
if /I "%1"=="backend-stop" call :backend_stop&goto end
if /I "%1"=="backend-restart" (
    call :backend_stop
    timeout /t 1 >nul
    call :backend_start
    goto end
)
if /I "%1"=="frontend-start" call :frontend_start&goto end
if /I "%1"=="frontend-stop" call :frontend_stop&goto end
if /I "%1"=="logs" (
    type "%RUN_DIR%\backend.log" 2>nul || echo No logs found
    goto end
)

:help
echo LocalRouter - Service Management (Windows)
echo.
echo Usage: %~nx0 ^<command^>
echo.
echo Commands:
echo   start              Start all services
echo   stop               Stop all services
echo   restart            Restart all services
echo   status             Show service status
echo   backend-start      Start only backend
echo   backend-stop       Stop only backend
echo   backend-restart    Restart only backend
echo   frontend-start     Start only frontend
echo   frontend-stop      Stop only frontend
echo   logs               Show backend log
echo.

:end
endlocal
