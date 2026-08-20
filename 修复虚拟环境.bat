@echo off
chcp 65001 >nul 2>&1
setlocal
rem ============================================================
rem  分发包首次运行：venv312 重定位自愈
rem  把随包 venv312 适配到本机路径（重写 pyvenv.cfg /
rem  activate / shebang，并重新生成全部控制台启动器）。
rem  仅需运行一次，之后用 start-prod.bat 启动。
rem ============================================================
cd /d "%~dp0"

set "PY="
if exist "python-base\python.exe" set "PY=python-base\python.exe"
if not defined PY (where py >nul 2>&1 && set "PY=py -3.12")
if not defined PY (where python >nul 2>&1 && set "PY=python")
if not defined PY (
    echo [错误] 未找到 Python，请先安装 Python 3.12 或随包携带 python-base\
    pause
    exit /b 1
)

set "SCRIPT=installer\fix_venv_relocate.py"
if not exist "%SCRIPT%" set "SCRIPT=fix_venv_relocate.py"
if not exist "%SCRIPT%" (
    echo [错误] 未找到 fix_venv_relocate.py（源码未拉取时请将脚本副本放在本目录）
    pause
    exit /b 1
)

%PY% "%SCRIPT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [错误] venv 修复失败，退出码: %RC%
    pause
    exit /b %RC%
)
pause
