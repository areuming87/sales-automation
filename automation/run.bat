@echo off
chcp 65001 > nul
title BPMS Automation - Run
cd /d "%~dp0"

REM Korean username path issue 회피용 환경 변수 설정
set PLAYWRIGHT_BROWSERS_PATH=C:\playwright_browsers

python bpms_download.py
pause
