@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d %~dp0
title VideoLingoLc 一键启动（正式版）

:: --- 加载本地覆盖配置（如有；含 LAN 模式开关 VIDEOLINGO_LAN_MODE）---
if exist "%cd%\.runtime\local_env.bat" call "%cd%\.runtime\local_env.bat"

:: ============================================================
::  正式版一键启动（Windows）：不隔离 CUDA / 环境，
::  直接使用用户系统已安装的 CUDA 运行时。
::  使用前请先运行 install.bat 完成 Python / 依赖 / 第三方扩展安装。
:: ============================================================

:: --- 探测 npm / node / bun / redis（仅提示，不重置 PATH）---
set NPM_CMD=
set NODE_DIR=
set BUN_CMD=
set REDIS_CMD=
for /f "tokens=*" %%i in ('where npm 2^>nul') do if not defined NPM_CMD set NPM_CMD=%%i
for /f "tokens=*" %%i in ('where node 2^>nul') do if not defined NODE_DIR set NODE_DIR=%%~dpi
for /f "tokens=*" %%i in ('where bun 2^>nul') do if not defined BUN_CMD set BUN_CMD=%%i
for /f "tokens=*" %%i in ('where redis-server 2^>nul') do if not defined REDIS_CMD set REDIS_CMD=%%i
if defined NPM_CMD (echo npm: !NPM_CMD!) else (echo WARNING: npm not found)
if defined BUN_CMD (echo bun: !BUN_CMD!) else (echo WARNING: bun not found)
if defined REDIS_CMD (echo redis: !REDIS_CMD!) else (echo WARNING: redis-server not found)
if defined NODE_DIR set NODE_EXE=%NODE_DIR%node.exe

:: --- 清除系统代理（避免 httpx/cloakbrowser 读取不支持的 socks:// 代理）---
set http_proxy=
set https_proxy=
set all_proxy=
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=

:: --- venv（仅激活，不隔离 CUDA）---
set "VENV_ROOT=%cd%\backend\venv312"
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

:: --- 数据目录 ---
if not exist "%cd%\data" mkdir "%cd%\data"
if not exist "%cd%\data\assets" mkdir "%cd%\data\assets"
if not exist "%cd%\data\workspace" mkdir "%cd%\data\workspace"
if not exist "%cd%\data\checkpoints" mkdir "%cd%\data\checkpoints"
if not exist "%cd%\data\backups" mkdir "%cd%\data\backups"
if not exist "%cd%\logs" mkdir "%cd%\logs"

:: --- Manager 端口检查 ---
echo [Manager] 检查端口 18001...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":18001" ^| findstr "LISTENING"') do (
    echo [ERROR] Manager 端口 18001 已被占用（PID: %%p），请先停止已运行的 Manager
    pause
    exit /b 1
)

:: --- 前端：清理残留 vite 后，新窗口等待主后端(11001)就绪再启动 Vite（后端先、前端后）---
set VITE_DEPRECATION_SILENT=1
if exist "%cd%\frontend\node_modules" (
    echo [Frontend] 清理 11003/11004 残留前端进程...
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":11003" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":11004" ^| findstr "LISTENING"') do taskkill /f /pid %%p >nul 2>&1
    echo [Frontend] 主后端就绪后将在新窗口启动 Vite dev server（http://127.0.0.1:11003）...
    start "VideoLingoLc Frontend" cmd /c "for /L %%i in (1,1,180) do @((netstat -ano | findstr ":11001" | findstr "LISTENING" >nul 2>&1 && (cd /d "%cd%\frontend" && npx vite --port 11003 --strictPort --open && exit)) & ping -n 2 127.0.0.1 >nul)"
) else (
    echo [提示] frontend\node_modules 不存在，跳过前端 dev server；可使用构建产物 frontend/dist
)

:: --- 当前窗口运行 Manager（全部后端服务与 worker 在此输出）---
echo [Backend] 启动 Manager（worker 输出在当前窗口）...
python backend\manager.py
if errorlevel 1 (
    echo.
    echo [ERROR] backend\manager.py 异常退出，退出码: !errorlevel!
)

echo.
echo 已退出（Manager 停止即全部后端服务停止）
pause
