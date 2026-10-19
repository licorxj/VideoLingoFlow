@echo off
chcp 65001 >nul 2>&1
setlocal
rem ============================================================
rem  Third-party extensions installer (Windows)
rem  CloakBrowser + pi + QM-LocalRouter + social-auto-upload-web-ui
rem  Invoked by the main installer after the venv is created:
rem      call "%~dp0thirdparty\install-thirdparty.bat"
rem  Options: --force  force re-download / rebuild
rem ============================================================
cd /d "%~dp0.."

set "VENV_PY=venv312\Scripts\python.exe"
set "PY="
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
) else (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python not found. Please install Python 3.12 or create the
    echo        venv312 virtual environment first.
    pause
    exit /b 1
)

echo ============================================================
echo   VideoLingoLc Third-party Extensions Installer
echo ============================================================
"%PY%" thirdparty\install_thirdparty.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [ERROR] Third-party installation failed, exit code: %RC%
    pause
    exit /b %RC%
)
echo [DONE] Third-party extensions installed.
pause
exit /b 0
