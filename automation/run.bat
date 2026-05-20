@echo off
chcp 65001 > nul
title BPMS Automation - Run
cd /d "%~dp0"
python bpms_download.py
pause
