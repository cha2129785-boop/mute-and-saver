; ============================================================
;  Mute&Saver — Inno Setup 설치 스크립트
;  "프로그램 추가/제거" 등록 + 제거 시 관련 파일 삭제
;  컴파일: ISCC.exe installer\MuteAndSaver.iss
;         (버전 지정: ISCC /DMyAppVersion=1.4.10 installer\MuteAndSaver.iss)
; ============================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.4.10"
#endif
#define MyAppName "Mute&Saver"
#define MyAppExe  "MuteAndSaver.exe"
#define MyAppPublisher "슈글"

[Setup]
; AppId 고정 — 업그레이드·제거 추적 (변경 금지)
AppId={{9F3B2E7A-5C41-4D8E-A6B2-7C1D0E4F9A21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; 관리자 권한 불필요 — 사용자 폴더 설치 (UAC 없음, 사용자별 추가/제거 등록)
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\MuteAndSaver
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=.
OutputBaseFilename=MuteAndSaver_v{#MyAppVersion}_setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\mute_and_saver\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
; 사용권 계약 — 설치 시 동의/비동의 (미동의 시 설치 취소)
LicenseFile=EULA_installer.txt

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 아이콘:"; Flags: unchecked

[Files]
; PyInstaller onedir 산출 폴더 전체 (build.spec → dist\MuteAndSaver\)
Source: "..\dist\MuteAndSaver\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent

; 제거 시 설치 폴더 잔여물 삭제 (로그 등 실행 중 생성분)
[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
{ 제거 완료 후 사용자 데이터(메모·설정·로그) 삭제 여부 확인 }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\MuteAndSaver');
    if DirExists(DataDir) then
    begin
      if MsgBox('사용자 데이터(메모·설정·로그)도 함께 삭제할까요?' + #13#10 +
                DataDir + #13#10#13#10 +
                '삭제하면 저장한 메모·설정이 모두 사라집니다.',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
