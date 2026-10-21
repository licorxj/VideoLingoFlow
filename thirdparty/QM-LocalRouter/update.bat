@echo off
setlocal enabledelayedexpansion
title LocalRouter - Update Code
cd /d "%~dp0"

echo ========================================
echo   LocalRouter - Update Code
echo ========================================
echo.

REM Windows counterpart of update.sh.
REM Pulls the latest code, then incrementally applies what changed:
REM   - backend/requirements.txt changed -> pip install
REM   - frontend package files changed   -> npm install
REM   - frontend source changed          -> npm run build
REM The database schema is upgraded automatically when the backend starts.

where git >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] git not found. Please install Git for Windows first.
    pause
    exit /b 1
)
if not exist ".git" (
    echo [ERROR] Run this script inside the repository directory.
    pause
    exit /b 1
)

for /f %%i in ('git rev-parse HEAD') do set "OLD_HEAD=%%i"
if not defined OLD_HEAD (
    echo [ERROR] Could not determine current commit. Is this a valid git repository?
    pause
    exit /b 1
)

echo [1/3] Pulling latest code (git pull --ff-only^)...
git pull --ff-only
if !ERRORLEVEL! NEQ 0 (
    echo [ERROR] git pull failed. Commit or stash your local changes ^(git stash^), then re-run.
    pause
    exit /b 1
)

for /f %%i in ('git rev-parse HEAD') do set "NEW_HEAD=%%i"
if "!OLD_HEAD!"=="!NEW_HEAD!" (
    echo Already up to date, nothing to do.
    pause
    exit /b 0
)
echo Code updated: !OLD_HEAD! -^> !NEW_HEAD!

REM ---- [2/3] Backend dependencies ----
if not exist "backend\venv\Scripts\python.exe" (
    echo Python venv not found - falling back to full setup...
    call "%~dp0install.bat"
    exit /b !ERRORLEVEL!
)
git diff --name-only !OLD_HEAD! !NEW_HEAD! -- backend/requirements.txt | findstr . >nul
if !ERRORLEVEL! EQU 0 (
    echo [2/3] requirements.txt changed - installing backend dependencies...
    "backend\venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] pip install failed.
        pause
        exit /b 1
    )
) else (
    echo [2/3] Backend dependencies unchanged.
)

REM ---- [3/3] Frontend ----
set "NEED_NPM=0"
if not exist "frontend\node_modules" set "NEED_NPM=1"
git diff --name-only !OLD_HEAD! !NEW_HEAD! -- frontend/package.json frontend/package-lock.json | findstr . >nul
if !ERRORLEVEL! EQU 0 set "NEED_NPM=1"

if "!NEED_NPM!"=="1" (
    echo [3/3] Frontend dependencies changed - npm install...
    pushd frontend
    call npm install
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
    popd
) else (
    echo [3/3] Frontend dependencies unchanged.
)

set "NEED_BUILD=0"
if not exist "frontend\dist\index.html" set "NEED_BUILD=1"
if "!NEED_NPM!"=="1" set "NEED_BUILD=1"
git diff --name-only !OLD_HEAD! !NEW_HEAD! -- frontend/src frontend/index.html frontend/vite.config.ts frontend/public frontend/tailwind.config.js frontend/postcss.config.js | findstr . >nul
if !ERRORLEVEL! EQU 0 set "NEED_BUILD=1"

if "!NEED_BUILD!"=="1" (
    echo Rebuilding frontend (npm run build^)...
    pushd frontend
    call npm run build
    if !ERRORLEVEL! NEQ 0 (
        popd
        echo [ERROR] Frontend build failed.
        pause
        exit /b 1
    )
    popd
) else (
    echo Frontend build unchanged.
)

echo.
echo Update complete! Database schema is upgraded automatically on next start.
echo Restart running services to apply the update:
echo   Production: stop-prod.bat + start-prod.bat
echo   Dev:        close the dev service windows, then run start.bat
echo.
pause
exit /b 0
