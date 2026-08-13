@echo off
chcp 65001 >nul 2>&1
setlocal
rem ============================================================
rem  VideoLingoLc 安装入口（Windows）
rem  调用跨平台安装器 installer/install.py
rem  可传参：--skip-backend / --skip-thirdparty / --force-thirdparty 等
rem ============================================================
cd /d "%~dp0"

set "VENV_PY=backend\venv312\Scripts\python.exe"
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
    echo [错误] 未找到 Python，将尝试由安装器自动下载安装...
    echo [提示] 需要 Python 3.10+（推荐 3.12）。如自动安装失败，请手动安装后重跑。
    set "PY=python"
)

echo ============================================================
echo   VideoLingoLc 安装程序
echo ============================================================
"%PY%" installer\install.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [错误] 安装未完成，退出码: %RC%
    pause
    exit /b %RC%
)
echo [完成] 安装完成，可启动 start.bat
pause
exit /b 0
