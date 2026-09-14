[English](README_EN.md) | **한국어**

# 뮤트세이버 (Mute&Saver)

여러 모니터에 메모·이미지를 띄우는 **화면보호기 + 시스템 음소거** 데스크톱 유틸리티 (Windows).
오픈소스 · 무설치(포터블) · 네트워크 전송 없음.

**Mute&Saver** — a multi-monitor **screensaver with memo board & system mute** for Windows.
Open-source, portable (no installer), no network access.

---

## 주요 기능 / Features
- 🖥️ 멀티모니터 화면보호기 (모니터별 미디어/메모/분할 모드)
- 📝 실제 해상도 메모 편집기 — 드래그·리사이즈·글꼴/크기/색·투명도
- ▦ 표 + 🗓 달력 템플릿 (셀 배경색·글자색, 월 이동 시 내용 보존)
- 🎨 서식 리본 메뉴 · 사용자 커스텀 양식 저장/즐겨찾기
- 🔇 화면보호기 진입 시 시스템 음소거 (해제 시 복원)
- 🌐 다국어 (한/영/중/일/러)

## 요구 사양 / Requirements
- Windows 10 / 11 (64-bit)
- 추가 설치 불필요 (Python 포함 번들)

## 설치 & 실행 / Install
1. [Releases](../../releases)에서 `MuteAndSaver_vX.Y.Z_win64.zip` 다운로드
2. 압축 해제 후 `MuteAndSaver.exe` 실행
3. SmartScreen "알 수 없는 게시자" 경고 시 → **추가 정보 → 실행**
   (코드 서명 인증서 미적용으로 인한 표준 경고이며, 소스는 공개되어 있습니다.)

## 데이터 저장 위치 / Data
- 설정·메모·로그: `%LOCALAPPDATA%\MuteAndSaver\`
- **외부로 전송되는 데이터 없음** — 모두 로컬에만 저장됩니다.

## 개인정보 / Privacy
- 네트워크 통신 없음. 파일·시스템 음소거만 로컬에서 처리.

## 소스에서 빌드 / Build from source
```bat
python -m pip install pyinstaller pycaw comtypes pillow
pyinstaller build.spec --noconfirm
REM 또는 한 번에:
build.bat
```
개발 실행: `pythonw run.pyw`

## 라이선스 / License
MIT — [LICENSE](LICENSE) 참조. 서드파티 고지는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## 스크린샷 / Screenshots
<!-- TODO: docs/ 에 스크린샷·GIF 추가 후 링크
![멀티모니터](docs/multimonitor.png)
![메모/표/달력](docs/memo.png)
-->
