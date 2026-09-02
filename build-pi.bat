@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d %~dp0
title VideoLingoLc 构建工具 - pi

echo ============================================================
echo   VideoLingoLc 第三方组件构建（pi）
echo   本脚本用于在分发版中重新安装依赖并构建 pi：
echo     - pi : npm install + npm run build (产出 coding-agent/dist/cli.js)
echo   说明：pi 的 cli.js 由 npm run build 生成，缺依赖时小派会提示。
echo   用法：build-pi.bat [--force]
echo ============================================================

rem ---- 参数解析 ----
set "FORCE="
:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--force" ( set "FORCE=1" & shift & goto :parse_args )
if /I "%~1"=="--help" ( goto :usage_exit )
if /I "%~1"=="-h" ( goto :usage_exit )
echo [WARN] 忽略未知参数: %~1
shift
goto :parse_args
:args_done

rem ---- 探测 node / npm ----
set "NODE_EXE="
for /f "tokens=*" %%i in ('where node 2^>nul') do if not defined NODE_EXE set "NODE_EXE=%%i"
set "NPM_EXE="
for /f "tokens=*" %%i in ('where npm 2^>nul') do if not defined NPM_EXE set "NPM_EXE=%%i"

set "NODE_VER=unknown"
if defined NODE_EXE (
  for /f "tokens=*" %%v in ('node --version 2^>nul') do set "NODE_VER=%%v"
)
set "NODE_MAJOR=0"
if defined NODE_EXE (
  set "NV=!NODE_VER:~1!"
  for /f "tokens=1 delims=." %%m in ("!NV!") do set "NODE_MAJOR=%%m"
)

echo.
echo [环境] node : !NODE_VER!  (pi 需要 ^>= 22.19)
echo [环境] npm  : !NPM_EXE!
echo.

set "PI_RC=0"

rem ---- pi ----
if not defined NODE_EXE (
  echo [ERROR] 未找到 node，pi 需要 Node.js ^>= 22.19
  set "PI_RC=1"
  goto :done
)
if not defined NPM_EXE (
  echo [ERROR] 未找到 npm，无法构建 pi
  set "PI_RC=1"
  goto :done
)
if !NODE_MAJOR! LSS 22 (
  echo [WARN] Node 主版本为 !NODE_MAJOR!（!NODE_VER!），pi 要求 ^>= 22.19，构建或运行可能失败，建议升级 Node。
)
if not exist "%~dp0thirdparty\pi" (
  echo [WARN] thirdparty\pi 不存在，跳过
  set "PI_RC=2"
  goto :done
)
pushd "%~dp0thirdparty\pi"
if defined FORCE (
  echo [pi] npm install --ignore-scripts --force ...
  call npm install --ignore-scripts --force
) else (
  echo [pi] npm install --ignore-scripts --prefer-offline ...
  call npm install --ignore-scripts --prefer-offline
)
if errorlevel 1 (
  echo [ERROR] pi 依赖安装失败
  popd
  set "PI_RC=1"
  goto :done
)
echo [pi] npm run build （重建各包 dist，含 coding-agent/dist/cli.js，可能耗时数分钟）...
call npm run build
set "PI_RC=!errorlevel!"
popd
if !PI_RC! neq 0 (
  echo [ERROR] pi 构建失败，请查看上方输出。
) else (
  echo [OK] pi 构建完成
)

goto :done

:usage_exit
echo 用法: build-pi.bat [--force]
echo   --force   强制重新安装依赖（忽略已存在的 node_modules）
pause
exit /b 0

:done
echo.
echo ============================================================
echo   构建结果汇总
echo     pi : %PI_RC%   (0=成功, 1=失败, 2=跳过/不存在)
echo ============================================================
echo 完成后可运行 start-prod.bat 启动（后端会自动启动 cutia 与 pi）。
pause
exit /b 0
