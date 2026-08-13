@echo off
chcp 65001 >nul 2>&1
setlocal
rem ============================================================
rem  第三方扩展安装（CloakBrowser + 三个第三方项目）
rem  主安装程序调用方式（放在创建 venv 之后）：
rem      call "%~dp0thirdparty\install-thirdparty.bat"
rem  可传参：--force 强制重新下载/构建
rem ============================================================
cd /d "%~dp0.."

set "VENV_PY=backend\venv312\Scripts\python.exe"
set "PY="
if exist "%VENV_PY%" (
    set "PY=%VENV_PY%"
) else (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [错误] 未找到 Python。请先安装 Python 3.12 或创建 backend\venv312 虚拟环境。
    pause
    exit /b 1
)

echo ============================================================
echo   VideoLingoLc 第三方扩展安装
echo ============================================================
"%PY%" thirdparty\install_thirdparty.py %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [错误] 第三方扩展安装失败，退出码: %RC%
    pause
    exit /b %RC%
)
echo [完成] 第三方扩展安装完成
pause
exit /b 0
