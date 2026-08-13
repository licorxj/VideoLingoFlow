@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Cloudflare Tunnel 一键配置
set "CF=C:\Program Files (x86)\cloudflared\cloudflared.exe"
set "CFDIR=%USERPROFILE%\.cloudflared"
set "HOST=vlflow.licorai.dpdns.org"

if not exist "%CFDIR%" mkdir "%CFDIR%"

echo ============================================================
echo   Cloudflare Tunnel 一键配置（单入口 vlflow.licorai.dpdns.org）
echo   目标: http://127.0.0.1:11001 （后端+前端+WS 同端口）
echo ============================================================

echo.
echo [1/5] 登录 Cloudflare（会自动打开浏览器，请点击 Authorize/Allow）
"%CF%" tunnel login
if errorlevel 1 (
    echo [错误] 登录失败，请重试。
    pause
    exit /b 1
)
echo [OK] 登录成功

echo.
echo [2/5] 创建隧道 videolingo
"%CF%" tunnel create videolingo
if errorlevel 1 echo [提示] 隧道可能已存在，继续执行。

echo.
echo [3/5] 生成配置文件 config.yml
set "TID="
for /f "delims=" %%i in ('dir /b "%CFDIR%\*.json" 2^>nul') do set "TID=%%~ni"
if "%TID%"=="" (
    echo [错误] 未找到隧道凭据文件，请确认第 2 步成功。
    pause
    exit /b 1
)
(
echo tunnel: %TID%
echo credentials-file: %CFDIR%\%TID%.json
echo ingress:
echo   - hostname: %HOST%
echo     service: http://127.0.0.1:11001
echo   - service: http_status:404
) > "%CFDIR%\config.yml"
echo [OK] 已生成 %CFDIR%\config.yml（tunnel=%TID%）

echo.
echo [4/5] 绑定 DNS 路由 %HOST%
"%CF%" tunnel route dns videolingo %HOST%
if errorlevel 1 (
    echo [错误] DNS 路由失败，请检查域名是否在 Cloudflare 托管。
    pause
    exit /b 1
)
echo [OK] DNS 已绑定

echo.
echo [5/5] 启动隧道（此窗口保持开启即在线；Ctrl+C 可停止）
echo       提示：如需开机自启，可另开终端运行：
echo       "%CF%" service install
echo.
"%CF%" tunnel run videolingo
pause

