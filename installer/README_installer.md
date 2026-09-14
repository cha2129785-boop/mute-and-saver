# 설치본(Installer) 빌드 안내

포터블 zip과 별개로, **"프로그램 추가/제거"에 등록되고 제거 시 파일을 삭제**하는 설치본(.exe)을 만든다.

## 절차
1. `build.bat` 실행 → `dist\MuteAndSaver\` 생성
2. [Inno Setup](https://jrsoftware.org/isdl.php) 설치 (무료)
3. `build_installer.bat` 실행
   → `installer\MuteAndSaver_v1.4.10_setup.exe` 생성

수동 컴파일:
```bat
ISCC /DMyAppVersion=1.4.10 installer\MuteAndSaver.iss
```

## 동작
- **설치**: 관리자 권한 불필요. `%LOCALAPPDATA%\Programs\MuteAndSaver`에 설치 → UAC 없음, **사용자별** "프로그램 추가/제거" 등록.
- **설치 시 동의**: 사용권 계약(EULA 1.1) 동의/취소 화면. 미동의 시 설치 종료.
- **제거**: "프로그램 추가/제거"에서 제거 → 설치 폴더 전체 삭제 + 사용자 데이터(메모·설정·로그, `%LOCALAPPDATA%\MuteAndSaver`) 삭제 여부 확인 팝업.
- 바탕화면 아이콘: 선택(기본 해제), 시작 메뉴 등록.

## 버전 갱신
`build_installer.bat`의 `APPVER`과 `constants.py`의 `APP_VERSION` 일치시킬 것.

## 참고
- 코드 서명 미적용 → 최초 실행/설치 시 SmartScreen "알 수 없는 게시자" 경고(정상). [추가 정보 → 실행].
- 포터블 zip 배포는 그대로 병행 가능(둘 중 택1 또는 병행).
