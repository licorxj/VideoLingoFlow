@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d %~dp0
title VideoLingoLc 主后端（独立启动）

:: 加载本地覆盖配置（如有；含 LAN 模式开关）
if exist "%cd%\.runtime\local_env.bat" call "%cd%\.runtime\local_env.bat"

if not exist "backend\venv312\Scripts\python.exe" (
    echo [错误] 未找到 backend\venv312 虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)
call "backend\venv312\Scripts\activate.bat"

echo ============================================
echo   主后端: http://127.0.0.1:11001
echo   说明: 仅启动主后端（FastAPI），不含 Manager 的
echo   进程管理 / Redis / Celery 等。完整环境请用 start.bat
echo ============================================
python backend\main.py
if errorlevel 1 (
    echo.
    echo [ERROR] backend\main.py 异常退出，退出码: !errorlevel!
)
pause
