@echo off
setlocal
cd /d "%~dp0frontend"
echo [Frontend] Waiting for main backend (11001) to be ready, then starting Vite on http://127.0.0.1:11003 ...
for /L %%i in (1,1,180) do (
    netstat -ano | findstr ":11001" | findstr "LISTENING" >nul 2>&1
    if not errorlevel 1 (
        cd /d "%~dp0frontend"
        npx vite --port 11003 --strictPort --open
        exit /b
    )
    ping -n 2 127.0.0.1 >nul
)
echo [Frontend] Timed out waiting for backend on 11001; Vite not started.
