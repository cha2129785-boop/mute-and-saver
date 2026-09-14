@echo off
chcp 65001 >nul
setlocal

set NAME=MuteAndSaver

where python >nul 2>nul || (echo [error] python not found - install Python + add to PATH & goto :fail)
python -m PyInstaller --version >nul 2>nul || (echo [error] pyinstaller missing - run: python -m pip install pyinstaller pycaw comtypes pillow & goto :fail)

rem 버전을 constants.py에서 자동 읽기(단일 소스) — 파일명 버전 어긋남 방지
for /f "usebackq delims=" %%v in (`python -c "from mute_and_saver.constants import APP_VERSION;print(APP_VERSION)"`) do set APPVER=%%v
if not defined APPVER (echo [error] APP_VERSION read failed & goto :fail)
echo [ver] APPVER=%APPVER%

echo [1/4] clean previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/4] PyInstaller build (onedir)...
python -m PyInstaller build.spec --noconfirm || (echo [error] build failed - see messages above & goto :fail)

echo [3/4] zip packaging...
set ZIP=%NAME%_v%APPVER%_win64.zip
if exist "%ZIP%" del "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%NAME%\*' -DestinationPath '%ZIP%' -Force"

echo [4/4] SHA-256 checksum...
powershell -NoProfile -Command "(Get-FileHash '%ZIP%' -Algorithm SHA256).Hash + '  %ZIP%' | Tee-Object '%ZIP%.sha256.txt'"

echo.
echo DONE: %ZIP%
echo Test on clean Windows: dist\%NAME%\%NAME%.exe
echo.
pause
endlocal
exit /b 0

:fail
echo.
pause
endlocal
exit /b 1
