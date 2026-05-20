@echo off
chcp 65001 >nul
title BPMS 자동화 - 설치
echo.
echo ══════════════════════════════════════════════════════════════
echo   BPMS 자동화 환경 설치
echo ══════════════════════════════════════════════════════════════
echo.

echo [1/3] Python 패키지 (Playwright) 설치 중...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ❌ pip install 실패! Python이 설치되어 있는지 확인하세요.
    pause
    exit /b 1
)
echo ✓ Playwright 라이브러리 설치 완료
echo.

echo [2/3] Chromium 브라우저 다운로드 중... (5분 정도 소요)
python -m playwright install chromium
if errorlevel 1 (
    echo.
    echo ❌ Chromium 설치 실패!
    pause
    exit /b 1
)
echo ✓ Chromium 설치 완료
echo.

echo [3/3] downloads 폴더 생성...
if not exist downloads mkdir downloads
echo ✓ 완료
echo.

echo ══════════════════════════════════════════════════════════════
echo   ✅ 모든 설치 완료!
echo ══════════════════════════════════════════════════════════════
echo.
echo  다음부터는 run.bat 더블클릭으로 실행하세요.
echo.
pause
