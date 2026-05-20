@echo off
chcp 65001 > nul
title BPMS Automation - Install
cd /d "%~dp0"

echo.
echo ====================================================
echo   BPMS Automation - Setup
echo ====================================================
echo.

echo [1/2] Installing Python package (Playwright)...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. Is Python installed?
    pause
    exit /b 1
)
echo OK - Playwright library installed
echo.

echo [2/2] Downloading Chromium browser (~5 min)...
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo ERROR: Chromium install failed.
    pause
    exit /b 1
)
echo OK - Chromium installed
echo.

if not exist downloads mkdir downloads

echo ====================================================
echo   All done! Run run.bat to start downloading.
echo ====================================================
echo.
pause
