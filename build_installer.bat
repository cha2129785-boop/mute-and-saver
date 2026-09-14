@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set "ISCC="

if not exist "dist\MuteAndSaver\MuteAndSaver.exe" (echo [error] dist\MuteAndSaver missing - run build.bat first & goto :fail)

rem 버전을 constants.py에서 자동 읽기(단일 소스) — 파일명 버전 어긋남 방지
where python >nul 2>nul || (echo [error] python not found - needed to read APP_VERSION & goto :fail)
for /f "usebackq delims=" %%v in (`python -c "from mute_and_saver.constants import APP_VERSION;print(APP_VERSION)"`) do set APPVER=%%v
if not defined APPVER (echo [error] APP_VERSION read failed & goto :fail)
echo [ver] APPVER=%APPVER%

REM 1) PATH
for %%I in (ISCC.exe) do if not defined ISCC if exist "%%~$PATH:I" set "ISCC=%%~$PATH:I"

REM 2) 공통 상위폴더 아래 'Inno Setup*' 전 버전 와일드카드 탐색
if not defined ISCC for %%R in (
  "%ProgramFiles(x86)%"
  "%ProgramFiles%"
  "%LOCALAPPDATA%\Programs"
) do if not defined ISCC for /d %%D in ("%%~R\Inno Setup*") do if not defined ISCC if exist "%%~D\ISCC.exe" set "ISCC=%%~D\ISCC.exe"

REM 3) .iss 파일연결 Compile 명령에서 폴더 추출 (버전 무관)
if not defined ISCC for /f "tokens=2,*" %%a in ('reg query "HKCR\InnoSetupScriptFile\Shell\Compile\Command" /ve 2^>nul ^| find "REG_"') do (
  set "CMD=%%b"
  set "CMD=!CMD:"=!"
  for %%P in ("!CMD!") do if exist "%%~dpPISCC.exe" set "ISCC=%%~dpPISCC.exe"
)

REM 4) 레지스트리 Uninstall 키 'Inno Setup*' 열거 → InstallLocation
if not defined ISCC for /f "delims=" %%K in ('reg query "HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" 2^>nul ^| find /i "Inno Setup"') do if not defined ISCC for /f "tokens=2,*" %%a in ('reg query "%%K" /v InstallLocation 2^>nul ^| find "InstallLocation"') do if exist "%%b\ISCC.exe" set "ISCC=%%b\ISCC.exe"
if not defined ISCC for /f "delims=" %%K in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall" 2^>nul ^| find /i "Inno Setup"') do if not defined ISCC for /f "tokens=2,*" %%a in ('reg query "%%K" /v InstallLocation 2^>nul ^| find "InstallLocation"') do if exist "%%b\ISCC.exe" set "ISCC=%%b\ISCC.exe"

if not defined ISCC (echo [error] Inno Setup ISCC.exe not found & goto :manual)

echo [found] !ISCC!
echo [build] creating installer (v%APPVER%)...
"!ISCC!" /DMyAppVersion=%APPVER% installer\MuteAndSaver.iss || (echo [error] installer build failed - see messages above & goto :fail)

echo.
echo DONE: installer\MuteAndSaver_v%APPVER%_setup.exe
echo.
pause
endlocal
exit /b 0

:manual
echo.
echo 수동 지정: ISCC.exe 전체경로 입력 후 Enter (취소=그냥 Enter)
set /p "MANUAL=ISCC.exe path: "
if defined MANUAL if exist "!MANUAL!" ("!MANUAL!" /DMyAppVersion=%APPVER% installer\MuteAndSaver.iss & echo. & echo DONE & pause & endlocal & exit /b 0)
echo [error] 경로 없음 또는 취소
:fail
echo.
pause
endlocal
exit /b 1
