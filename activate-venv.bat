@echo off
chcp 65001 >nul
cd /d %~dp0
:: ============================================================
::  正式版：激活 backend\venv312 虚拟环境（不隔离 CUDA / 环境，
::  使用用户系统已安装的 CUDA）。激活后停留在交互式命令行。
:: ============================================================
if not exist "backend\venv312\Scripts\activate.bat" (
    echo [错误] 未找到 backend\venv312 虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)
call "backend\venv312\Scripts\activate.bat"
echo.
echo VideoLingoLc venv 已激活（使用系统 CUDA 环境）
cmd /k
