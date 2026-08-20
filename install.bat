@echo off
chcp 65001 >nul 2>&1
setlocal
rem ============================================================
rem  VideoLingoLc installer entry (Windows)
rem  Invokes the cross-platform installer: installer/install.py
rem  Options: --skip-backend / --skip-thirdparty / --force-thirdparty
rem ============================================================
cd /d "%~dp0"

set "VENV_PY=venv312\Scripts\python.exe"
set "PY="
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
) else (
    where python >nul 2>&1 && set "PY=python"
    if not defined PY (
        where py >nul 2>&1 && set "PY=py"
    )
)
if not defined PY (
    echo [ERROR] Python not found. The installer will try to download it automatically.
    echo [HINT] Python 3.10+ is required (3.12 recommended). If auto-install fails,
    echo        please install Python manually and re-run this installer.
    set "PY=python"
)

echo ============================================================
echo   VideoLingoLc Installer
echo ============================================================
"%PY%" installer\install.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [ERROR] Installation incomplete, exit code: %RC%
    pause
    exit /b %RC%
)
echo [DONE] Installation complete. You can now run start.bat
pause
exit /b 0
