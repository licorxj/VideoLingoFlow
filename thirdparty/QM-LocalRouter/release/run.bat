@echo off
title LocalRouter - Run packaged executable
cd /d "%~dp0"

if "%HOST%"=="" set "HOST=127.0.0.1"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=12002"

start "" apirouter.exe
