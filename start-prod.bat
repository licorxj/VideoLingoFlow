@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d %~dp0
title VideoLingoLc 一键启动（正式版 · 生产模式）

:: --- 加载本地覆盖配置（如有；含 LAN 模式开关 VIDEOLINGO_LAN_MODE）---
if exist "%cd%\.runtime\local_env.bat" call "%cd%\.runtime\local_env.bat"

:: ============================================================
::  正式版一键启动·生产模式（Windows）：不隔离 CUDA / 环境，
::  不启动 Vite dev server；前端由后端同源托管构建产物 frontend/dist，
::  访问 http://127.0.0.1:11001/ 即为生产版前端。
::  使用前请先运行 install.bat 完成 Python / 依赖 / 第三方扩展安装。
::  用法：start-prod.bat [--rebuild]
::        --rebuild  强制重新构建前端（默认：dist 已存在时直接复用）
:: ============================================================

:: --- 探测 npm / node（仅提示，不重置 PATH）---
set NPM_CMD=
set NODE_DIR=
for /f "tokens=*" %%i in ('where npm 2^>nul') do if not defined NPM_CMD set NPM_CMD=%%i
for /f "tokens=*" %%i in ('where node 2^>nul') do if not defined NODE_DIR set NODE_DIR=%%~dpi
if defined NPM_CMD (echo npm: !NPM_CMD!) else (echo WARNING: npm not found)
if defined NODE_DIR set NODE_EXE=%NODE_DIR%node.exe

:: --- 清除系统代理（避免 httpx/cloakbrowser 读取不支持的 socks:// 代理）---
set http_proxy=
set https_proxy=
set all_proxy=
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=

:: --- venv（仅激活，不隔离 CUDA）---
set "VENV_ROOT=%cd%\venv312"
if not exist "%VENV_ROOT%\Scripts\python.exe" (
    echo [ERROR] 未找到 Python 虚拟环境: %VENV_ROOT%
    echo         请先运行 install.bat 完成安装
    pause
    exit /b 1
)
call "%VENV_ROOT%\Scripts\activate.bat"

:: --- 依赖自检 ---
python -c "import sqlite3, alembic, celery, redis, sqlalchemy" >nul 2>&1
if !errorlevel! neq 0 (
    echo [ERROR] Python 依赖不完整，请先运行 install.bat
    pause
    exit /b 1
)

:: --- 生产模式：主后端隐藏窗口，仅保留 Manager 一个窗口 ---
set VIDEOLINGO_PROD_MODE=1

:: --- 数据目录 ---
if not exist "%cd%\data" mkdir "%cd%\data"
if not exist "%cd%\data\assets" mkdir "%cd%\data\assets"
if not exist "%cd%\data\workspace" mkdir "%cd%\data\workspace"
if not exist "%cd%\data\checkpoints" mkdir "%cd%\data\checkpoints"
if not exist "%cd%\data\backups" mkdir "%cd%\data\backups"
if not exist "%cd%\logs" mkdir "%cd%\logs"

:: --- 前端：生产构建（由后端同源托管 frontend/dist）---
if /I "%~1"=="--rebuild" goto :build_frontend
if exist "%cd%\frontend\dist\index.html" (
    echo [Frontend] 使用现有构建产物 frontend\dist（如需重建请运行 start-prod.bat --rebuild）
    goto :frontend_done
)

:build_frontend
if not exist "%cd%\frontend\node_modules" (
    echo [ERROR] frontend\node_modules 不存在，无法构建前端
    echo         请先运行 install.bat 或在前端目录执行 npm install
    pause
    exit /b 1
)
echo [Frontend] 构建生产版本（npm run build）...
pushd "%cd%\frontend"
call npm run build
set BUILD_RC=!errorlevel!
popd
if !BUILD_RC! neq 0 (
    echo [ERROR] 前端构建失败，退出码: !BUILD_RC!
    pause
    exit /b 1
)
:frontend_done

:: --- Manager 端口检查 ---
echo [Manager] 检查端口 18001...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":18001" ^| findstr "LISTENING"') do (
    echo [ERROR] Manager 端口 18001 已被占用（PID: %%p），请先停止已运行的 Manager
    pause
    exit /b 1
)

:: --- 启动 Manager（后端全部服务，同源托管生产版前端）---
echo.
echo [生产模式] 前端: http://127.0.0.1:11001/  （后端同源托管 frontend\dist）
echo.
rem 端口就绪后自动打开默认浏览器（每 2 秒轮询一次，就绪即开）
start "" cmd /c "for /L %%i in (1,1,120) do @((netstat -ano | findstr ":11001" | findstr "LISTENING" >nul 2>&1 && (start http://127.0.0.1:11001 & exit /b)) & ping -n 2 127.0.0.1 >nul)"
python backend\manager.py
if errorlevel 1 (
    echo.
    echo [ERROR] backend\manager.py 异常退出，退出码: !errorlevel!
)

pause
