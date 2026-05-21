@echo off
chcp 65001 > nul
title BPMS Bridge Server (localhost:8765)
cd /d "%~dp0"

set PLAYWRIGHT_BROWSERS_PATH=C:\playwright_browsers
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo.
echo ====================================================
echo   BPMS Bridge Server
echo ====================================================
echo.
echo   Address: http://localhost:8765
echo.
echo   Keep this window OPEN while using the web app.
echo   Close = automation disabled.
echo.
echo   First time login: run "run.bat" once to save session.
echo.
echo ====================================================
echo.

python server.py

echo.
echo Server stopped.
pause
