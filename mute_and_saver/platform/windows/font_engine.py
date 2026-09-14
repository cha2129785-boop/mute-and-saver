# -*- coding: utf-8 -*-
"""
font_engine — GDI 폰트 임시 등록/해제 (AddFontResourceExW)
"""
import ctypes
import logging
from pathlib import Path

LOG = logging.getLogger("MuteAndSaver")

FR_PRIVATE  = 0x10   # 다른 프로세스에 비공개

class FontEngine:
    """
    AddFontResourceExW로 .ttf를 GDI에 임시 등록.
    프로그램 종료 시 RemoveFontResourceExW로 핸들 해제 필수.
    """

    def __init__(self):
        self.loaded_fonts = []   # 등록된 .ttf 경로 목록

    def load_font(self, font_path: str) -> bool:
        """단일 .ttf 파일을 GDI에 등록"""
        try:
            # ctypes.windll.gdi32 API는 LPCWSTR을 받음 → unicode 버퍼 권장
            path_buf = ctypes.create_unicode_buffer(font_path)
            res = ctypes.windll.gdi32.AddFontResourceExW(path_buf, FR_PRIVATE, 0)
            if res > 0:
                self.loaded_fonts.append(font_path)
                return True
            return False
        except Exception:
            return False

    def load_directory(self, fonts_dir) -> int:
        """assets/fonts/*.ttf 일괄 등록 — 등록 성공 개수 반환"""
        if not fonts_dir or not Path(fonts_dir).exists():
            return 0
        count = 0
        for ttf in Path(fonts_dir).glob("*.ttf"):
            if self.load_font(str(ttf)):
                count += 1
        return count

    def unload_all(self):
        """종료 시 GDI 핸들 누수 방지 — 반드시 호출"""
        for path in self.loaded_fonts:
            try:
                path_buf = ctypes.create_unicode_buffer(path)
                ctypes.windll.gdi32.RemoveFontResourceExW(path_buf, FR_PRIVATE, 0)
            except Exception:
                pass
        self.loaded_fonts.clear()
