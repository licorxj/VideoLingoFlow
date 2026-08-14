@echo off
setlocal enabledelayedexpansion
title Cloudflare Tunnel Setup
set "CF=C:\Program Files (x86)\cloudflared\cloudflared.exe"
set "CFDIR=%USERPROFILE%\.cloudflared"
set "HOST=vlflow.licorai.dpdns.org"

if not exist "%CFDIR%" mkdir "%CFDIR%"

echo ============================================================
echo   Cloudflare Tunnel Setup (single entry vlflow.licorai.dpdns.org)
echo   Target: http://127.0.0.1:11001 (backend + frontend + WS)
echo ============================================================

echo.
echo [1/5] Login to Cloudflare (browser will open, click Authorize/Allow)
"%CF%" tunnel login
if errorlevel 1 (
    echo [ERROR] Login failed, please retry.
    pause
    exit /b 1
)
echo [OK] Login succeeded

echo.
echo [2/5] Create tunnel "videolingo"
"%CF%" tunnel create videolingo
if errorlevel 1 echo [HINT] Tunnel may already exist, continuing.

echo.
echo [3/5] Generate config.yml
set "TID="
for /f "delims=" %%i in ('dir /b "%CFDIR%\*.json" 2^>nul') do set "TID=%%~ni"
if "%TID%"=="" (
    echo [ERROR] Tunnel credential file not found, please check step 2.
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
echo [OK] Generated %CFDIR%\config.yml (tunnel=%TID%)

echo.
echo [4/5] Bind DNS route %HOST%
"%CF%" tunnel route dns videolingo %HOST%
if errorlevel 1 (
    echo [ERROR] DNS route failed, please make sure the domain is hosted on Cloudflare.
    pause
    exit /b 1
)
echo [OK] DNS bound

echo.
echo [5/5] Start tunnel (keep this window open to stay online; Ctrl+C to stop)
echo       Tip: for auto-start on boot, run in another terminal:
echo       "%CF%" service install
echo.
"%CF%" tunnel run videolingo
pause
