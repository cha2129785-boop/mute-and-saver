# -*- coding: utf-8 -*-
"""
tray — TrayHotkeySystem: 트레이 아이콘 + 전역 단축키 (Win32 메시지 루프)
"""
import logging
from pathlib import Path
import threading

LOG = logging.getLogger("MuteAndSaver")

_HAS_WIN32 = False
try:
    import win32api
    import win32con
    import win32gui
    _HAS_WIN32 = True
except ImportError:
    pass

try:
    from PIL import Image
except ImportError:
    pass

from ...constants import APP_DISPLAY
from ...i18n import t

class TrayHotkeySystem:
    """
    pywin32 기반 통합 시스템 — pystray(LGPL) + keyboard(권한 이슈) 대체.
    단일 hwnd / 단일 _wnd_proc / 단일 메시지 루프로
    트레이 아이콘 + 전역 단축키를 모두 처리.
    """

    # ── Windows API 상수 ──────────────────────
    WM_HOTKEY     = 0x0312
    WM_TRAYICON   = 0x8000 + 20    # WM_USER + 20
    WM_LBUTTONUP  = 0x0202
    WM_RBUTTONUP  = 0x0205
    WM_LBUTTONDBLCLK = 0x0203

    NIM_ADD       = 0x00000000
    NIM_MODIFY    = 0x00000001
    NIM_DELETE    = 0x00000002
    NIF_MESSAGE   = 0x00000001
    NIF_ICON      = 0x00000002
    NIF_TIP       = 0x00000004

    HOTKEY_ID     = 1
    MOD_NOREPEAT  = 0x4000
    WM_UPDATE_HOTKEY = 0x0400 + 100  # WM_USER=0x0400, win32con 의존 제거
    WM_ADD_HOTKEY2   = 0x0400 + 101  # 2번 채널 (퀵 메모)

    MOD_MAP = {
        "ctrl":    0x0002, "alt":     0x0001, "shift":   0x0004,
        "win":     0x0008, "windows": 0x0008, "cmd":     0x0008, "meta": 0x0008,
    }
    VK_MAP = {
        "space": 0x20, "tab": 0x09, "return": 0x0D, "enter": 0x0D,
        "esc": 0x1B, "escape": 0x1B,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
        "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
        "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "insert": 0x2D, "delete": 0x2E,
        # OEM 특수키 (Ctrl 전용 권장 조합)
        ";": 0xBA, "semicolon": 0xBA,
        "`": 0xC0, "grave": 0xC0,
        "\\": 0xDC, "backslash": 0xDC,
        "]": 0xDD, "bracketright": 0xDD,
        "[": 0xDB, "bracketleft": 0xDB,
        "-": 0xBD, "minus": 0xBD,
        "=": 0xBB, "equal": 0xBB,
        "'": 0xDE, "apostrophe": 0xDE,
        ",": 0xBC, "comma": 0xBC,
        ".": 0xBE, "period": 0xBE,
        "/": 0xBF, "slash": 0xBF,
    }

    def __init__(self, app, icon_path, tooltip=APP_DISPLAY):
        self.app       = app
        self.icon_path = icon_path
        self.tooltip   = tooltip
        self.hwnd      = None
        self._running  = False
        self._thread   = None

        # 트레이 메뉴 콜백 ID 풀
        self._cb_ids   = {}
        self._next_id  = 1000

        # 단축키 등록 상태
        self._hk_registered = False
        self._hk_current    = None
        self._pending_hotkeys: dict = {}   # 다중 단축키 채널 임시 보관 (ID → (mods, vk))

    # ══════════════════════════════════════
    # 시작 / 종료
    # ══════════════════════════════════════
    def start(self) -> bool:
        if not _HAS_WIN32:
            LOG.warning("pywin32 미설치 — Tray+Hotkey 시작 안 됨")
            return False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if not self._running:
            return
        LOG.info("[Tray] 🛑 TrayHotkeySystem.stop() 진입 — 종료 절차 개시")
        self.unregister_hotkey()
        self._running = False

        # 1. NIM_DELETE — 여기서만 1회
        try:
            LOG.info("[Tray] 1. 윈도우 시스템에 NIM_DELETE 요청 중...")
            self._remove_icon()
            LOG.info("[Tray] 1. NIM_DELETE 요청 완료")
        except Exception as e:
            LOG.error(f"[Tray] 🚨 NIM_DELETE 수행 오류: {e}")

        # 2. SendMessage(동기 블로킹) — 창 파괴 확인 후 반환
        if self.hwnd:
            try:
                LOG.info(f"[Tray] 2. HWND({self.hwnd})로 WM_CLOSE 동기 전송 시작...")
                win32gui.SendMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
                LOG.info("[Tray] 2. WM_CLOSE 처리 완료 — 메시지 루프 종료 확인")
            except Exception as e:
                LOG.error(f"[Tray] 🚨 SendMessage 오류: {e}")

    def _run_loop(self):
        try:
            wc = win32gui.WNDCLASS()
            wc.lpszClassName = "MuteAndSaver_Host"
            wc.lpfnWndProc   = self._wnd_proc
            wc.hInstance     = win32api.GetModuleHandle(None)
            class_atom = win32gui.RegisterClass(wc)

            self.hwnd = win32gui.CreateWindow(
                class_atom, "MuteAndSaverHost", 0, 0, 0, 0, 0,
                0, 0, wc.hInstance, None
            )
            self._add_icon()
            self._running = True
            LOG.info("Tray 시스템 시작")

            # 백그라운드 스레드 권한으로 초기 단축키 등록 (ID=1 화면보호기)
            hk = self.app.config.get("hotkey_screensaver", "ctrl+shift+l")
            self.register_hotkey(hk)

            win32gui.PumpMessages()
        except Exception as e:
            LOG.error(f"Tray+Hotkey 루프 오류: {e}")
            self._running = False

    # ══════════════════════════════════════
    # 통합 윈도우 프로시저
    # ══════════════════════════════════════
    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        # ── A. 전역 단축키 감지 (다중 ID 라우팅) ──
        if msg == self.WM_HOTKEY:
            hotkey_id = wparam
            if hotkey_id == 1:
                # ID=1: 화면보호기 잠금
                try:
                    self.app.root.after(0, self.app._lock_screen)
                except Exception as e:
                    LOG.error(f"WM_HOTKEY(ID=1) 콜백 오류: {e}")
            elif hotkey_id == 2:
                # ID=2: 퀵 메모 토글 (직통 릴레이)
                try:
                    self.app.root.after(0, self.app._execute_quick_memo_toggle)
                except Exception as e:
                    LOG.error(f"WM_HOTKEY(ID=2) 콜백 오류: {e}")
            return 0

        # ── B. 1번 채널 단축키 갱신 (메인→백그라운드 우편, _pending_hotkeys 방식) ──
        if msg == self.WM_UPDATE_HOTKEY:
            if 1 in self._pending_hotkeys:
                mods, vk = self._pending_hotkeys.pop(1)
                try:
                    win32gui.UnregisterHotKey(hwnd, 1)
                except Exception:
                    pass   # 최초 등록 시 아직 없음 → 무시
                ok = win32gui.RegisterHotKey(hwnd, 1, mods, vk)
                if ok:
                    self._hk_registered = True
                    LOG.info(f"[Tray] ID=1 화면보호기 단축키 갱신 완료 (VK:{hex(vk)})")
                else:
                    self._hk_registered = False
                    LOG.error("[Tray] ID=1 단축키 갱신 실패 (다른 앱 사용 중?)")
            return 0

        # ── B2. 2번 채널 단축키 등록 (퀵 메모 전용 채널) ──
        if msg == self.WM_ADD_HOTKEY2:
            if 2 in self._pending_hotkeys:
                mods, vk = self._pending_hotkeys.pop(2)
                try:
                    win32gui.UnregisterHotKey(hwnd, 2)
                except Exception:
                    pass   # 최초 등록 시 아직 없음 → 무시
                ok = win32gui.RegisterHotKey(hwnd, 2, mods, vk)
                if ok:
                    LOG.info(f"[Tray] ID=2 퀵 메모 단축키 등록 완료 (VK:{hex(vk)})")
                else:
                    LOG.error("[Tray] ID=2 퀵 메모 단축키 등록 실패 (다른 앱 사용 중?)")
            return 0

        # ── C. 트레이 아이콘 ──
        if msg == self.WM_TRAYICON:
            if lparam == self.WM_LBUTTONUP:
                self._on_left_click()
            elif lparam == self.WM_RBUTTONUP:
                self._show_menu()
            elif lparam == self.WM_LBUTTONDBLCLK:
                self._on_left_click()
            return 0

        # ── C. 메뉴 명령 ──
        if msg == win32con.WM_COMMAND:
            cmd_id = win32gui.LOWORD(wparam)
            if cmd_id in self._cb_ids:
                try:
                    cb = self._cb_ids[cmd_id]
                    self.app.root.after(0, cb)
                except Exception as e:
                    LOG.error(f"메뉴 콜백 오류: {e}")
            return 0

        # ── D. 종료 ──
        if msg == win32con.WM_DESTROY:
            self.unregister_hotkey()
            # stop()에서 이미 _remove_icon() 호출했을 수 있으므로 중복 방지
            if not getattr(self, '_icon_removed', False):
                self._remove_icon()
            win32gui.PostQuitMessage(0)
            return 0

        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ══════════════════════════════════════
    # 트레이 아이콘 관리
    # ══════════════════════════════════════
    def _build_tooltip(self) -> str:
        """현재 상태(화면보호기/절전)를 담은 툴팁 문자열. 아이콘 호버 시 상태 반영."""
        try:
            L = self.app.config.get("language", "ko")
            ss_on = self.app.config.get("screensaver_enabled", True)
            ps_on = self.app.config.get("power_save_enabled", False)
            status = t("tray_status_fmt", L).format(
                ss="ON" if ss_on else "OFF",
                ps="ON" if ps_on else "OFF",
            )
            return f"{APP_DISPLAY} — {status}"[:127]   # NIF_TIP 최대 127자
        except Exception:
            return self.tooltip

    def _add_icon(self):
        try:
            if Path(self.icon_path).exists():
                hicon = win32gui.LoadImage(
                    0, str(self.icon_path), win32con.IMAGE_ICON,
                    16, 16, win32con.LR_LOADFROMFILE
                )
            else:
                hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            flags = self.NIF_ICON | self.NIF_MESSAGE | self.NIF_TIP
            nid = (self.hwnd, 0, flags, self.WM_TRAYICON, hicon, self._build_tooltip())
            win32gui.Shell_NotifyIcon(self.NIM_ADD, nid)
            self._hicon = hicon
        except Exception as e:
            LOG.error(f"트레이 아이콘 추가 오류: {e}")

    def update_status(self):
        """상태 변경 시 툴팁 갱신(NIM_MODIFY). 메인/백그라운드 어느 스레드서 호출해도 무해."""
        if not _HAS_WIN32 or not self.hwnd or getattr(self, "_icon_removed", False):
            return
        try:
            nid = (self.hwnd, 0, self.NIF_TIP, self.WM_TRAYICON,
                   getattr(self, "_hicon", 0), self._build_tooltip())
            win32gui.Shell_NotifyIcon(self.NIM_MODIFY, nid)
        except Exception as e:
            LOG.debug(f"[Tray] 툴팁 갱신 실패: {e}")

    def _remove_icon(self):
        if getattr(self, '_icon_removed', False):
            return   # 중복 NIM_DELETE 방지
        self._icon_removed = True
        try:
            nid = (self.hwnd, 0)
            win32gui.Shell_NotifyIcon(self.NIM_DELETE, nid)
            LOG.info("트레이 아이콘 NIM_DELETE 완료")
        except Exception:
            pass

    # ══════════════════════════════════════
    # 좌클릭 / 우클릭
    # ══════════════════════════════════════
    def _on_left_click(self):
        try:
            self.app.root.after(0, self.app._show_main_window)
        except Exception as e:
            LOG.error(f"좌클릭 오류: {e}")

    def _show_menu(self):
        try:
            menu = win32gui.CreatePopupMenu()
            self._cb_ids.clear()

            ss_on = self.app.config.get("screensaver_enabled", True)
            ps_on = self.app.config.get("power_save_enabled", False)

            # 확장된 트레이 메뉴
            L = self.app.config.get("language", "ko")
            # 상태 헤더 (비클릭) — 현재 화면보호기/절전 상태 표시
            self._append_status(menu, t("tray_status_fmt", L).format(
                ss="ON" if ss_on else "OFF", ps="ON" if ps_on else "OFF"))
            self._append_separator(menu)
            self._append_item(menu, t("tray_edit", L),      self.app._open_fullscreen_editor)
            self._append_item(menu, t("tray_lock", L),      self.app._lock_screen)
            self._append_separator(menu)
            self._append_item(menu, t("tray_settings", L),  self.app._show_main_window)
            self._append_separator(menu)
            self._append_item(menu,
                t("tray_ss_on", L) if ss_on else t("tray_ss_off", L),
                self.app._toggle_ss_from_tray)
            self._append_item(menu,
                t("tray_ps_on", L) if ps_on else t("tray_ps_off", L),
                self.app._toggle_ps_from_tray)
            self._append_separator(menu)
            self._append_item(menu, t("tray_quit", L), self.app._on_close)

            self.update_status()   # 메뉴 열 때 툴팁도 최신 상태로 동기화
            pos = win32gui.GetCursorPos()
            win32gui.SetForegroundWindow(self.hwnd)
            win32gui.TrackPopupMenu(
                menu, win32con.TPM_LEFTALIGN | win32con.TPM_BOTTOMALIGN,
                pos[0], pos[1], 0, self.hwnd, None
            )
            win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        except Exception as e:
            LOG.error(f"메뉴 표시 오류: {e}")

    def _append_item(self, menu, text, callback):
        cmd_id = self._next_id
        self._next_id += 1
        self._cb_ids[cmd_id] = callback
        win32gui.AppendMenu(menu, win32con.MF_STRING, cmd_id, text)

    def _append_separator(self, menu):
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

    def _append_status(self, menu, text):
        """비클릭 상태 헤더 (회색 비활성 항목)."""
        win32gui.AppendMenu(
            menu,
            win32con.MF_STRING | win32con.MF_DISABLED | win32con.MF_GRAYED,
            0, text
        )

    def _notify_balloon(self, title: str, msg: str, timeout_ms: int = 3000):
        """
        win32 Shell_NotifyIcon Balloon 알림.
        win10toast 불필요 — pywin32만 사용 (이미 의존).
        """
        if not _HAS_WIN32:
            return
        try:
            nid = (
                self.hwnd, 0,
                win32gui.NIF_INFO,
                self.WM_TRAYICON,
                0, "",
                msg[:255], timeout_ms,
                title[:63],
                win32con.NIIF_INFO
            )
            win32gui.Shell_NotifyIcon(self.NIM_MODIFY, nid)
        except Exception as e:
            LOG.debug(f"[Notify] Balloon 실패: {e}")

    # ══════════════════════════════════════
    # 전역 단축키 — 트레이 hwnd + PostMessage
    # 등록: 백그라운드 스레드(_run_loop) 권한
    # 갱신: 메인→백그라운드 WM_UPDATE_HOTKEY 우편
    # ══════════════════════════════════════
    def _parse_hotkey(self, hk_str: str):
        """'ctrl+space' → (mods, vk_code)"""
        parts = [p.strip().lower() for p in hk_str.split("+") if p.strip()]
        mods = self.MOD_NOREPEAT
        vk = None
        for p in parts:
            if p in self.MOD_MAP:
                mods |= self.MOD_MAP[p]
            elif p in self.VK_MAP:
                vk = self.VK_MAP[p]
            elif len(p) == 1 and p.isalnum():
                vk = ord(p.upper())
            else:
                raise ValueError(f"알 수 없는 키: '{p}'")
        if vk is None:
            raise ValueError(f"주 키 없음: '{hk_str}'")
        return mods, vk

    def register_hotkey(self, hk_str: str) -> bool:
        """백그라운드 스레드(_run_loop)에서만 호출."""
        if not _HAS_WIN32 or not self.hwnd:
            return False
        self.unregister_hotkey()
        try:
            mods, vk = self._parse_hotkey(hk_str)
            ok = win32gui.RegisterHotKey(self.hwnd, self.HOTKEY_ID, mods, vk)
            if ok:
                self._hk_registered = True
                self._hk_current    = hk_str
                LOG.info(f"전역 단축키 등록: {hk_str}")
                return True
            LOG.error(f"단축키 등록 실패 (다른 앱 사용 중?): {hk_str}")
        except Exception as e:
            LOG.error(f"단축키 등록 오류 ({hk_str}): {e}")
        return False

    def unregister_hotkey(self):
        if not _HAS_WIN32 or not self._hk_registered or not self.hwnd:
            return
        try:
            win32gui.UnregisterHotKey(self.hwnd, self.HOTKEY_ID)
            LOG.info(f"전역 단축키 해제: {self._hk_current}")
        except Exception as e:
            LOG.error(f"단축키 해제 오류: {e}")
        self._hk_registered = False
        self._hk_current    = None

    def update_hotkey(self, hk_str: str) -> bool:
        """
        메인 스레드에서 안전하게 호출 — ID=1 화면보호기 단축키 갱신.
        PostMessage → _wnd_proc → _pending_hotkeys → RegisterHotKey(ID=1).
        mods 하드코딩 제거: _parse_hotkey로 동적 계산 (Ctrl+Shift+L 등 지원).
        """
        if not _HAS_WIN32 or not self.hwnd:
            return False
        try:
            mods, vk = self._parse_hotkey(hk_str)
        except Exception as e:
            LOG.error(f"[Tray] update_hotkey 파싱 실패: {hk_str} → {e}")
            return False
        if not vk:
            LOG.error(f"[Tray] update_hotkey: 주 키 없음 '{hk_str}'")
            return False
        self._pending_hotkeys[1] = (mods, vk)
        win32gui.PostMessage(self.hwnd, self.WM_UPDATE_HOTKEY, 0, 0)
        self._hk_current = hk_str
        LOG.info(f"[Tray] ID=1 단축키 갱신 우편 발송: {hk_str}")
        return True

    def register_quick_memo_hotkey(self, hk_str: str) -> bool:
        """
        메인 스레드에서 안전하게 호출 — ID=2 퀵 메모 단축키 등록.
        PostMessage → _wnd_proc(WM_ADD_HOTKEY2) → RegisterHotKey(ID=2).
        """
        if not _HAS_WIN32 or not self.hwnd:
            return False
        try:
            mods, vk = self._parse_hotkey(hk_str)
        except Exception as e:
            LOG.error(f"[Tray] register_quick_memo_hotkey 파싱 실패: {hk_str} → {e}")
            return False
        if not vk:
            LOG.error(f"[Tray] register_quick_memo_hotkey: 주 키 없음 '{hk_str}'")
            return False
        self._pending_hotkeys[2] = (mods, vk)
        win32gui.PostMessage(self.hwnd, self.WM_ADD_HOTKEY2, 0, 0)
        LOG.info(f"[Tray] ID=2 퀵 메모 단축키 등록 우편 발송: {hk_str}")
        return True
