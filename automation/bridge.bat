@echo off
chcp 65001 > nul
title BPMS Bridge Server (localhost:8765)
cd /d "%~dp0"

REM Korean username path issue 회피
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
echo   웹앱(bpms.html)의 [BPMS 불러오기] 버튼이
echo   이 서버를 통해 자동화를 실행합니다.
echo.
echo   * 이 창을 닫으면 자동화 기능이 비활성화됩니다.
echo   * 처음에 한 번은 run.bat 으로 수동 로그인 권장.
echo.
echo ====================================================
echo.

python server.py

echo.
echo 서버가 종료되었습니다.
pause
