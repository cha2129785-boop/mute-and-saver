# -*- coding: utf-8 -*-
"""
main_window — ScreesaverApp: 메인 윈도우 + 탭 통합 (mixin 조합)
"""
import sys
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox

LOG = logging.getLogger("MuteAndSaver")

from .window_utils import center_window
from .. import bootstrap
from ..i18n import t
from ..constants import (APP_VERSION, APP_DISPLAY, DEFAULT_CONFIG, ICON_PATH)
from ..persistence import load_config, save_config, load_favorites, save_favorites
from ..services import SystemAudioController
from ..platform.windows import IdleMonitor, TrayHotkeySystem
from ..platform.windows.monitor import _get_monitors_info
from .tabs.settings_tab import SettingsTabMixin
from .tabs.media_tab import MediaTabMixin
from .tabs.hotkey_tab import HotkeyTabMixin
from .tabs.memo_tab import MemoTabMixin
from .tabs.license_lang_tab import LicenseLangTabMixin
from .lifecycle import LifecycleMixin


class ScreesaverApp(
    SettingsTabMixin,
    MediaTabMixin,
    HotkeyTabMixin,
    MemoTabMixin,
    LicenseLangTabMixin,
    LifecycleMixin,
):
    def __init__(self, mode: str = "normal"):
        self.mode      = mode  # "normal" | "screensaver" | "config"
        LOG.info(f"[App.__init__] 시작 (mode={mode})")

        LOG.info("[App.__init__] 설정 로드 중...")
        self.config    = load_config()
        self.favorites = load_favorites()
        self._migrate_legacy_hotkey()   # 레거시 "hotkey" → "hotkey_screensaver" 마이그레이션
        self._seed_default_media()      # 첫 실행 시 사용설명서를 기본 미디어로 시드
        LOG.info("[App.__init__] 설정 로드 완료")

        LOG.info("[App.__init__] Tkinter 루트 창 생성 중...")
        self.root = tk.Tk()
        self.root.withdraw()
        try:
            self.root.tk.call('tk', 'scaling', 1.0)
        except Exception:
            pass
        LOG.info("[App.__init__] Tkinter 루트 창 생성 완료")

        # ── Tk 콜백 예외 포착: <Configure> 등 위젯 콜백 오류 로그화 ──
        # (기본 Tk는 콜백 예외를 stderr로만 출력 → pythonw에선 유실. 리사이즈 크래시 진단용)
        import traceback as _tb_cb
        def _tk_callback_exc(_e, _v, _t):
            LOG.critical("[TkCallback] 위젯 콜백 예외:\n"
                         + "".join(_tb_cb.format_exception(_e, _v, _t)))
        self.root.report_callback_exception = _tk_callback_exc

        # ── Tk 변수 (설정 탭용) ─────────────────────
        self.var_ss_enabled  = tk.BooleanVar(value=self.config["screensaver_enabled"])
        self.var_ps_enabled  = tk.BooleanVar(value=self.config["power_save_enabled"])
        self.var_mute_enabled = tk.BooleanVar(value=self.config.get("mute_on_screensaver", False))
        self.var_timeout     = tk.IntVar(   value=max(1, self.config["timeout_seconds"] // 60))
        self.var_timeout_entry = tk.StringVar(value=str(max(1, self.config["timeout_seconds"] // 60)))
        # ── 단축키 StringVar: 최초 1회만 생성 (재빌드 시 재사용) ──
        self.var_hotkey      = tk.StringVar(value="")
        self.var_hotkey_disp = tk.StringVar(value=self._fmt_hotkey(self.config.get("hotkey_screensaver", "ctrl+shift+l")))
        # 퀵 메모 3대 UI 변수
        self.var_qm_hk_mode     = tk.StringVar(value=self.config.get("qm_hotkey_mode", "default"))
        self.var_qm_hotkey_disp = tk.StringVar(value=self._fmt_hotkey(self.config.get("hotkey_quick_memo", "ctrl+m")))
        self.var_qm_hotkey      = tk.StringVar()
        # 메모 카드 투명도 UI 변수
        _init_op = self.config.get("memo_opacity", 0.0)
        self.var_memo_opacity     = tk.DoubleVar(value=_init_op)
        self.var_memo_opacity_str = tk.StringVar(value=str(int(_init_op * 100)))
        self.temp_new_hotkey = None
        self.config["_draft_hotkey"] = ""  # 불멸 대기실 초기화
        self.audio_controller = SystemAudioController()
        LOG.info("[App.__init__] 오디오 컨트롤러 완료. _build_main_window 진입...")
        self.var_slide_mode = tk.StringVar(value=self.config["slide_mode"])
        self.var_interval   = tk.IntVar(   value=self.config["media_interval_seconds"])

        # PIN 실패 카운터 (메모리 기반, 재시작 시 초기화)
        self._pin_fail_count  = 0
        self._pin_locked_until = 0.0

        # Stage 7 v7 — 단축키 캡처 UI 상태
        self._hk_capture_fail = 0
        self._hk_capture_top  = None

        # Stage 8 v7 — 트레이 + 단축키 통합 시스템
        self._tray_hk     = None   # TrayHotkeySystem 인스턴스
        self._exiting_proc        = False   # 종료 프로세스 중복 진입 방지
        self._theme_switching_now = False   # 테마 전환 중복 진입 방지
        self._is_toggling_memo    = False   # 퀵 메모 연타 방지 디바운스
        self._updating_qm_ui_now  = False   # 퀵 메모 UI 연쇄 발동 차단 가드
        self._is_locking          = False   # 화면보호기 생성 중 단축키 연타 방지 락
        self._updating_opacity    = False   # 투명도 슬라이더 핑퐁 방지 가드

        # 관리자 키 히든 언락 — 세션 메모리에만 유지 (config 저장 안 함)
        self._admin_secret_buf    = ""      # 타이핑 감지 버퍼
        self._admin_unlock_armed  = False   # 시크릿 문자열 입력 완료 상태
        self._admin_section_shown = False   # 관리자 키 입력칸 노출 여부

        # Stage 9 v7 — 유휴 감지 / 절전 제어 (IdleMonitor 위임)
        self._idle_monitor = None
        self._ss_closed_at = 0.0

        self._build_main_window()

        # Stage 11 v7 — 모드별 동작 분기
        if self.mode == "screensaver":
            # /s 인수: 트레이/메인창 없이 즉시 전체화면 실행 후 종료
            self.root.withdraw()
            self.root.after(100, self._lock_screen_immediate)
            return
        elif self.mode == "config":
            # /c 인수: 설정 창만 표시 (트레이/단축키/idle 모니터 없음)
            self.root.deiconify()
            return

        # normal 모드: 전체 시스템 시작
        self.root.deiconify()
        self._start_tray()              # Stage 8 v7
        self._register_console_ctrl_handler()   # CMD X 버튼 강제 종료 방어
        self.root.after(500, self._setup_quick_memo_hotkey)  # hwnd 안정화 후 퀵 메모 단축키 등록
        self._start_idle_monitor()      # Stage 9 v7
        # FIX (단축키 스코프): 메인 스레드에서도 메시지 펌핑 (이중 안전)
        self._start_message_pump()

    # ── 메인 창 구성 ────────────────────────────────
    def _build_main_window(self):
        L = self.config.get("language", "ko")
        self.root.title(f"{APP_DISPLAY} v{APP_VERSION}")
        self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        # 창 크기·위치 기억: normal 상태 변화만 메모리 기록(종료 시 config 저장)
        self.root.bind("<Configure>", self._remember_geometry, add="+")
        try:
            if ICON_PATH.exists():
                self.root.iconbitmap(str(ICON_PATH))
        except Exception:
            pass

        # ── 상단 바 제거 (제작자 이메일·PIN 표시 삭제) ──────────────
        # PIN 설정은 설정 탭에서 가능. PIN 상태 변수/라벨은 _refresh_pin_label
        # 호환을 위해 화면에 표시하지 않는 숨김 위젯으로만 유지.
        self.var_pin_status = tk.StringVar()
        self.lbl_pin = tk.Label(self.root, textvariable=self.var_pin_status)  # pack 안 함(숨김)
        self._refresh_pin_label()

        # 관리자 키 히든 언락 — 앱 내 어디서 타이핑해도 시크릿 문자열 감지
        # (시스템 전역 키후킹 아님, Tkinter 포커스가 앱 안에 있을 때만 동작)
        self.root.bind_all("<Key>", self._on_admin_secret_keypress, add="+")

        # ── 전역 기본 폰트 최소 10pt ─────────────────
        # ttk/tk 미지정 위젯(LabelFrame 헤더·버튼·라벨·체크·콤보 등)은
        # 명명 폰트/ttk 스타일을 따르므로 인라인 font= 로는 안 잡힘 → 여기서 일괄 상향
        import tkinter.font as _tkfont
        for _fn in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                _f = _tkfont.nametofont(_fn)
                _sz = _f.cget("size")
                # size>0=포인트, size<0=픽셀. 10pt 미만이면 10으로 상향
                if 0 < _sz < 10 or -13 < _sz < 0:
                    _f.configure(size=10)
            except Exception:
                pass
        # ── 탭 노트북 ────────────────────────────────
        _tab_style = ttk.Style()
        for _st_name in ("TLabelframe.Label", "TButton", "TLabel",
                         "TCheckbutton", "TRadiobutton", "TEntry",
                         "TCombobox", "TSpinbox"):
            try:
                _tab_style.configure(_st_name, font=("Malgun Gothic", 13))
            except Exception:
                pass
        # 탭 라벨 폰트: Malgun Gothic 14pt bold (전 탭 일괄)
        _tab_style.configure("TNotebook.Tab", font=("Malgun Gothic", 14, "bold"), padding=(12, 5))
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=6)

        self.tab_setting = ttk.Frame(self.nb, padding=4)
        self.tab_media   = ttk.Frame(self.nb, padding=4)   # Stage A: 미디어 탭
        self.tab_hotkey  = ttk.Frame(self.nb, padding=4)
        self.tab_memo    = ttk.Frame(self.nb, padding=4)
        self.tab_license = ttk.Frame(self.nb, padding=4)   # 라이선스 탭
        self.tab_lang    = ttk.Frame(self.nb, padding=4)

        self.nb.add(self.tab_setting, text=t("tab_setting", L))
        self.nb.add(self.tab_media,   text=t("tab_media", L))
        self.nb.add(self.tab_hotkey,  text=t("tab_hotkey", L))
        self.nb.add(self.tab_memo,    text=t("tab_memo", L))
        self.nb.add(self.tab_license, text=t("tab_license", L))
        self.nb.add(self.tab_lang,    text=t("tab_lang_about", L))

        # Stage D — 탭 키 ↔ 위젯 매핑 (드래그앤드롭 재배치·순서 영속화용)
        self._tab_widgets = {
            "setting": self.tab_setting,
            "media":   self.tab_media,
            "hotkey":  self.tab_hotkey,
            "memo":    self.tab_memo,
            "license": self.tab_license,
            "lang":    self.tab_lang,
        }
        self.nb.bind("<ButtonPress-1>", self._on_tab_drag_start)
        self.nb.bind("<B1-Motion>",     self._on_tab_drag_motion)
        self.nb.bind("<ButtonRelease-1>", self._on_tab_drag_end)

        self._editor: "DashboardEditor | None" = None
        LOG.info("[App] 탭 빌드 시작...")
        self._build_tab_setting()
        LOG.info("[App] ⚙ 설정 탭 완료")
        self._build_tab_media()
        LOG.info("[App] 🎬 미디어 탭 완료")
        self._build_tab_hotkey()
        LOG.info("[App] ⌨ 단축키 탭 완료")
        self._build_tab_memo()
        LOG.info("[App] 📝 메모보드 탭 완료")
        self._build_tab_license()
        LOG.info("[App] 💎 라이선스 탭 완료")
        self._build_tab_lang()
        LOG.info("[App] 🌐 언어·정보 탭 완료")

        self._apply_tab_order()
        LOG.info("[App] 🗂 탭 순서 복원 완료")

        # 라이선스 탭은 관리자 전용 → 평소 숨김 (세션 언락 시에만 노출)
        # 언락: 앱에서 시크릿 타이핑 후 언어·정보 탭 작성자 이메일 클릭
        if not getattr(self, "_admin_section_shown", False):
            try:
                self.nb.hide(self.tab_license)
            except Exception:
                pass

        # 첫 실행 창 높이를 설정탭 내용 높이에 맞춤(스크롤바 없이 딱 떨어지게) → center_window 측정 직전
        try:
            self.fit_settings_canvas_to_content()
        except Exception:
            pass
        center_window(self.root, min_w=420, min_h=480, resizable=True)
        self._restore_window_geometry()   # 저장된 크기·위치 복원(화면 밖이면 중앙 유지)
        try:
            self._update_settings_scrollbar()   # 초기 스크롤바 상태 확정
        except Exception:
            pass
        self.root.after(60000, self._periodic_gc)   # 유휴 안전지점 주기 GC(A)
        LOG.info("메인 창 초기화 완료")

    def _periodic_gc(self):
        """자동 GC off(A) 상태에서 메인스레드 유휴에만 사이클 수거.
        단독 gc.collect → COM 채널 살아있는 안전 시점에 comtypes Release 수행."""
        try:
            import gc as _gc
            _gc.collect()
        except Exception:
            pass
        try:
            if self.root.winfo_exists():
                self.root.after(60000, self._periodic_gc)
        except Exception:
            pass

    # ── 창 크기·위치 기억/복원 ───────────────────────
    def _remember_geometry(self, event=None):
        """root가 normal 상태일 때의 geometry만 메모리 기록. 종료 시 config에 반영."""
        try:
            if event is not None and event.widget is not self.root:
                return
            if self.root.state() == "normal":
                self._last_normal_geo = self.root.geometry()
        except Exception:
            pass

    def _geometry_on_screen(self, x, y, w, h):
        """창 사각형이 어떤 모니터와 충분히 겹치면 True(드래그 가능 영역 보장). 멀티모니터 음수 좌표 정상 처리."""
        try:
            from ..platform.windows.monitor import _get_monitors_info
            mons = _get_monitors_info()
        except Exception:
            mons = []
        if not mons:
            return True   # 감지 불가 → 허용
        for (mx, my, mw, mh, _p) in mons:
            ix, iy = max(x, mx), max(y, my)
            ax, ay = min(x + w, mx + mw), min(y + h, my + mh)
            if (ax - ix) > 100 and (ay - iy) > 50:
                return True
        return False

    def _restore_window_geometry(self):
        import re
        geo = self.config.get("win_geometry", "") or ""
        m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geo)
        if not m:
            return
        w, h, x, y = map(int, m.groups())
        w, h = max(w, 420), max(h, 700)   # 설계 최소치 하한(답답함 방지)
        # 화면 상한 클램핑 (작은 화면 보호)
        try:
            w = min(w, self.root.winfo_screenwidth() - 40)
            h = min(h, self.root.winfo_screenheight() - 80)
        except Exception:
            pass
        if not self._geometry_on_screen(x, y, w, h):
            return   # 화면 밖 복원 방지 → center_window 결과 유지
        try:
            self.root.geometry(f"{w}x{h}+{x}+{y}")
            self._last_normal_geo = f"{w}x{h}+{x}+{y}"
        except Exception:
            pass

    # ── Stage D: 탭 순서 복원 ────────────────────────
    def _apply_tab_order(self):
        """config["tab_order"] 순서대로 nb.insert() 재배치. 키 집합 불일치 시 기본 순서로 안전 폴백."""
        default_order = list(DEFAULT_CONFIG["tab_order"])
        order = self.config.get("tab_order", default_order)
        if sorted(order) != sorted(default_order):
            LOG.warning(f"[TabOrder] 저장된 tab_order 불일치({order}) → 기본 순서로 폴백")
            order = default_order
            self.config["tab_order"] = default_order
        for idx, key in enumerate(order):
            self.nb.insert(idx, self._tab_widgets[key])

    # ── Stage D: 탭 드래그앤드롭 ──────────────────────
    def _on_tab_drag_start(self, event):
        try:
            self._drag_start_idx = self.nb.index(f"@{event.x},{event.y}")
        except tk.TclError:
            self._drag_start_idx = None
        self._drag_reordered = False

    def _on_tab_drag_motion(self, event):
        if getattr(self, '_drag_start_idx', None) is None:
            return
        try:
            target_idx = self.nb.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        if target_idx != self._drag_start_idx:
            child = self.nb.tabs()[self._drag_start_idx]
            self.nb.insert(target_idx, child)
            self._drag_start_idx = target_idx
            self._drag_reordered = True

    def _on_tab_drag_end(self, event):
        if getattr(self, '_drag_start_idx', None) is not None and getattr(self, '_drag_reordered', False):
            self._save_tab_order()
        self._drag_start_idx  = None
        self._drag_reordered  = False

    def _save_tab_order(self):
        """현재 nb.tabs() 물리 순서 → 탭 키 리스트로 변환해 config 저장."""
        order = []
        for tab_id in self.nb.tabs():
            for key, child in self._tab_widgets.items():
                if str(child) == tab_id:
                    order.append(key)
                    break
        self.config["tab_order"] = order
        save_config(self.config)
        LOG.info(f"[TabOrder] 순서 저장: {order}")

    # ── PIN 라벨 갱신 ────────────────────────────────
    def _refresh_pin_label(self):
        L = self.config.get("language", "ko")
        if self.config.get("pin_set"):
            self.var_pin_status.set(t("pin_set_label", L))
            self.lbl_pin.config(fg="#27ae60")
        else:
            self.var_pin_status.set(t("pin_no_label", L))
            self.lbl_pin.config(fg="#aaaaaa")

    def _on_close(self):
        # ── Debounce 2차 방어선: 중복 진입 차단 ────────────────
        if getattr(self, '_exiting_proc', False):
            LOG.warning("[Main_Exit] ⚠️ 중복 종료 요청 차단!")
            return
        self._exiting_proc = True

        LOG.info("[Main_Exit] 🛑🛑🛑 시스템 완전 종료 장갑차 가동 🛑🛑🛑")

        # 1. FSEditor grab 선제 해제
        fs = getattr(self, '_fs_editor', None)
        if fs:
            try:
                fs._release_grab()
                fs.overlay.destroy()
            except Exception:
                pass
            self._fs_editor = None

        # 2. 설정/즐겨찾기 저장 (최우선)
        # 마지막 normal 창 geometry 반영 (withdraw/최소화 상태 값은 배제)
        _geo = getattr(self, "_last_normal_geo", None)
        if _geo:
            self.config["win_geometry"] = _geo
        try:
            LOG.info("[Main_Exit] 2. save_config() 파일 쓰기 시작...")
            save_config(self.config)
            LOG.info("[Main_Exit] 2. ✅ save_config() 디스크 쓰기 완료")
        except Exception as e:
            LOG.error(f"[Main_Exit] 🚨 설정 저장 실패: {e}")
        try:
            save_favorites(self.favorites)
        except Exception as e:
            LOG.error(f"[Main_Exit] 🚨 favorites 저장 실패: {e}")

        # 3. 유휴 감지 + 전원 원복
        try:
            LOG.info("[Main_Exit] 3. 유휴 모니터 및 전원 복구 절차 진입...")
            self._stop_idle_monitor()
            self._restore_power_state()
            LOG.info("[Main_Exit] 3. 하드웨어 복구 완료")
        except Exception as e:
            LOG.error(f"[Main_Exit] 🚨 복구 절차 예외: {e}")

        # 3-b. 오디오 COM 인터페이스 명시 해제 (메인스레드, 채널 살아있는 안전 시점)
        try:
            if getattr(self, "audio_controller", None):
                self.audio_controller.close()
        except Exception as e:
            LOG.error(f"[Main_Exit] 오디오 COM 해제 오류: {e}")

        # 4. 폰트 핸들 해제
        try:
            if bootstrap.font_engine is not None:
                bootstrap.font_engine.unload_all()
        except Exception as e:
            LOG.error(f"[Main_Exit] 폰트 해제 오류: {e}")

        # 5. 활성 화면보호기 정리
        if hasattr(self, '_screensaver') and self._screensaver:
            try:
                self._screensaver.close()
            except Exception:
                pass
            self._screensaver = None

        # 6. 트레이 정리
        LOG.info("[Main_Exit] 6. 트레이 스레드 및 알림 영역 아이콘 삭제 연동...")
        self._stop_tray()
        self._unregister_global_hotkey()

        # 7. Tkinter root 파괴
        try:
            if hasattr(self, 'root') and self.root:
                LOG.info("[Main_Exit] 7. root.destroy() 요청")
                self.root.destroy()
                LOG.info("[Main_Exit] 7. UI 리소스 반환 완료")
        except Exception as e:
            LOG.error(f"[Main_Exit] 🚨 UI 파괴 오류: {e}")

        # 8. 파일 시스템 I/O 최종 동기화 (150ms) 후 안전 종료
        LOG.info("[Main_Exit] 8. 파일 시스템 I/O 최종 동기화 150ms 슬립...")
        import time as _time
        _time.sleep(0.15)
        LOG.info("[Main_Exit] 🏁 모든 절차 완수 — sys.exit(0) 호출")
        import sys as _sys
        try:
            _sys.exit(0)
        except SystemExit:
            pass
        import os as _os
        _os._exit(0)

    def run(self):
        self.root.mainloop()
