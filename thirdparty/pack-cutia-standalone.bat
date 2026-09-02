@echo off
chcp 65001 >nul 2>&1

rem ---- 自动提权：bun install 创建符号链接/硬链接需要管理员权限；管理员可直接创建 ----
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [INFO] 请求管理员权限（bun install 创建符号链接需要）...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
)

setlocal EnableDelayedExpansion
cd /d "%~dp0"

rem 仓库根 = 脚本所在目录（thirdparty）的上级
for %%r in ("%~dp0..") do set "REPO=%%~fr"

title Build cutia standalone (Windows native)
echo ============================================================
echo   Build cutia standalone (Windows native, shipped via git)
echo   Steps: ensure bun, bun install, bun run build:web,
echo           then assemble thirdparty\cutia\apps\web\standalone
echo   For Windows/integration users: run cutia without building.
echo   Do NOT commit on non-Windows (cross-platform binaries invalid).
echo   Arg: --no-git  build only, skip git add
echo ============================================================

rem ---- 选择 Python（优先 py，其次 python）----
set "PY="
for /f "tokens=*" %%i in ('where py 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY for /f "tokens=*" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
  echo [ERROR] 未找到 python / py。请先安装 Python 3.10+ 或运行 install.bat 创建 venv。
  pause
  exit /b 1
)

rem ---- 检查 node（build:web 需要 node）----
set "NODE_EXE="
for /f "tokens=*" %%i in ('where node 2^>nul') do if not defined NODE_EXE set "NODE_EXE=%%i"
if not defined NODE_EXE (
  echo [WARN] 未找到 node。build:web 需要 Node.js（^>= 18）；将尝试继续，
  echo        若构建失败，请先运行 install.bat 或安装 Node.js 后再试。
)

echo.
echo [1/1] 调用 install_thirdparty.ensure_cutia(force=True) 构建并整理 standalone ...
"%PY%" -c "import install_thirdparty; raise SystemExit(0 if install_thirdparty.ensure_cutia(True) else 1)"
if errorlevel 1 (
  echo [ERROR] cutia standalone 构建失败，请查看上方日志。
  pause
  exit /b 1
)

echo.
echo [OK] cutia standalone 已就绪: thirdparty\cutia\apps\web\standalone
echo.

rem ---- 加入 git（若存在仓库根 .git）----
if exist "%REPO%\.git" (
  if "%~1"=="--no-git" (
    echo [INFO] 已跳过 git add（--no-git）。请手动执行：
  ) else (
    echo [git] git add cutia standalone 产物 ...
    git -C "%REPO%" add thirdparty/cutia/apps/web/standalone
    echo [OK] 已 git add。请人工 review 后提交：
  )
  echo       git -C "%REPO%" commit -m "chore: 提交 cutia Windows standalone 产物"
) else (
  echo [INFO] 未在 %REPO% 检测到 .git，跳过 git add。请在主仓库手动执行：
  echo       git add thirdparty/cutia/apps/web/standalone
  echo       git commit -m "chore: 提交 cutia Windows standalone 产物"
)

echo.
echo 完成。Windows / 整合包用户安装后运行 install.bat 即可免构建使用 cutia。
pause
