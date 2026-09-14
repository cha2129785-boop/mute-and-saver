# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — Mute & Saver (onedir, 백신 오탐 최소화).
빌드:  pyinstaller build.spec --noconfirm
결과:  dist/MuteAndSaver/MuteAndSaver.exe  (폴더째 zip 배포)
"""
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 아이콘: mute_and_saver/assets/app.ico 가 있으면 사용, 없으면 기본 아이콘
_icon = os.path.join("mute_and_saver", "assets", "app.ico")
ICON = _icon if os.path.exists(_icon) else None

# 에셋: 런타임 BASE_DIR(_MEIPASS) 루트의 'assets' 로 복사되어야 함
#  (constants.ASSETS_DIR = BASE_DIR / "assets")
datas = [
    ("mute_and_saver/assets", "assets"),
]

# COM/음소거(pycaw·comtypes)·이미지(PIL) 동적 로딩 누락 방지
hiddenimports = (
    collect_submodules("comtypes")
    + collect_submodules("pycaw")
    + ["PIL._tkinter_finder"]
)

a = Analysis(
    ["run.pyw"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MuteAndSaver",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX 압축 비활성 → 백신 오탐 추가 감소
    console=False,          # GUI 앱(콘솔 숨김)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MuteAndSaver",
)
