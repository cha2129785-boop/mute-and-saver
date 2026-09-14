@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

echo === 사용설명서 이미지 생성기 ===
echo (개발용 - 배포 불필요. 설명서 문구/버전 바꿀 때만 실행)
echo.
where python >nul 2>nul || (echo [error] python 미설치 - Python 설치 후 PATH 등록 & pause & exit /b 1)

echo [1/3] playwright 설치 확인...
python -c "import playwright" 2>nul || python -m pip install playwright

echo [2/3] (선택) 번들 Chromium 다운로드 시도 - 막히면 건너뜀(시스템 Edge 사용)...
python -m playwright install chromium 2>nul || echo   다운로드 불가 - 시스템 Edge/Chrome 사용

echo [3/3] 설명서 이미지 생성...
python tools\make_manual.py || (echo [error] 생성 실패 - Edge/Chrome 미설치거나 위 메시지 확인 & pause & exit /b 1)

echo.
echo 완료: mute_and_saver\assets\default_media\manual.png / manual_en.png
echo.
pause
endlocal
