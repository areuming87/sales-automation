@echo off
chcp 65001 >nul
title BPMS 자동화 - 실행
cd /d "%~dp0"
python bpms_download.py
pause
