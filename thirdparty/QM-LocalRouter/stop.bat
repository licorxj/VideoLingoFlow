@echo off
title LocalRouter Stop
cd /d "%~dp0"

REM Windows counterpart of stop.sh.
REM Stops the frontend, backend and Service Manager started by start.bat.

call "%~dp0scripts\manage.bat" stop
exit /b 0
