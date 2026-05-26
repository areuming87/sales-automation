@echo off
chcp 65001 > nul
title BPMS Master Launcher

echo.
echo ====================================================
echo   BPMS Master Launcher
echo ====================================================
echo.
echo   This will start BOTH servers in separate windows:
echo.
echo   [1] Backend API     (port 8000) - 5-user shared DB
echo   [2] Automation Bridge (port 8765) - Salesforce download
echo.
echo   Keep BOTH windows open while working.
echo ====================================================
echo.

echo Starting Backend API...
start "BPMS Backend" "\\GSChargev_NAS\EV사업실\[영업현황 자동화_NAS]\backend\start.bat"

timeout /t 2 /nobreak > nul

echo Starting Automation Bridge...
start "BPMS Bridge" "\\GSChargev_NAS\EV사업실\[영업현황 자동화_NAS]\automation\bridge.bat"

echo.
echo ====================================================
echo   Both servers launching in separate windows.
echo   This launcher window will close in 5 seconds.
echo ====================================================
timeout /t 5 /nobreak > nul
exit
