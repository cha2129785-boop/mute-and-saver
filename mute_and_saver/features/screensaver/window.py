# -*- coding: utf-8 -*-
"""
window — ScreensaverWindow: 화면보호기 창 (미디어 재생 + PIN 오버레이 + 블러)
"""
import logging
from pathlib import Path
import time
import threading
import queue
import random
import tkinter as tk
from tkinter import ttk, messagebox

LOG = logging.getLogger("MuteAndSaver")

try:
    from PIL import Image, ImageTk, ImageFilter, ImageGrab
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from ...constants import IMG_EXTS, VIDEO_EXTS, TIER_CONFIG
from ...i18n import t
from ...media.image_rendering import _safe_font
from ...persistence import load_favorites, save_config
from ...services import verify_pin, clear_pin, _verify_master
from ...platform.windows.monitor import _get_monitors_info
from ..memo.viewer import MemoBoardViewer

class ScreensaverWindow:
    """전체화면 화면보호기 — 미디어 재생 (소리 없음)"""

    def __init__(self, app):
        self.app = app
        self.stop_event = threading.Event()
        self.frame_queue = queue.Queue(maxsize=2)
        self._decode_thr = None
        self._current_idx = 0
        self._after_id = None
        self._extra_wins = []
        self._monitor_watch_id = None
        self._reclaim_id = None
        self._focus_guard_id = None
        self.pin_top = None
        self._memo_viewer     = None   # 주 모니터 MemoBoardViewer
        self._secondary_viewers: list = []  # 보조 모니터 뷰어 목록
        self._secondary_img_lbls: list = []  # 보조 모니터 이미지 라벨(동영상 제외)
        # 보조 모니터 영상(격리 플레이어, 동시 1개 · 주 디코더 미사용 시에만)
        self._sec_video_active = False
        self._sec_after_id = None
        self._sec_decode_thr = None
        self._sec_video_lbl = None
        self._is_split = False   # 분할 모드 여부 — _fit_frame 스케일 방식 결정

        self.playlist = self._build_playlist()

        # ── 모니터 정보 수집 ─────────────────────
        self._monitors = _get_monitors_info()
        # 주 모니터: is_primary=True인 첫 번째, 없으면 목록 첫 번째
        primary = next((m for m in self._monitors if m[4]), self._monitors[0])
        px, py, pw, ph, _ = primary

        # ── 주 모니터 창 (미디어 + PIN 오버레이) ─
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self._setup_window(px, py, pw, ph)

        # ── 보조 모니터 검은 덮개 창 생성 ────────
        for mon in self._monitors:
            mx, my, mw, mh, is_primary = mon
            if is_primary:
                continue
            self._create_cover_window(mx, my, mw, mh)

        self.win.deiconify()
        for cw in self._extra_wins:
            cw.deiconify()

        # 모니터별 콘텐츠 맵 결정
        self._content_map = self._build_content_map()
        # 보조 모니터 콘텐츠 렌더링 (1회)
        self._render_secondary_windows()
        # 보조 창 초기 페인트 강제 — 주 모니터 media 모드에서 영상 프레임 after 루프가
        #  이벤트 루프를 포화시켜 보조 memo/이미지가 미표시되던 문제 방지(주모드 무관 표시)
        try:
            for cw in self._extra_wins:
                cw.update_idletasks()
                cw.lift()
        except Exception:
            pass

        self._play_current()
        self._watch_monitor_changes()
        self._start_focus_guard()

    def _capture_blur_bg(self):
        """
        백그라운드 스레드에서 현재 화면 캡처 + Gaussian Blur.
        lbl_bg는 이미 검은색 → 원본 화면 노출 없음.
        캡처 전 self.win.withdraw() → deiconify()로 자기 창 제외.
        """
        try:
            from PIL import ImageGrab, ImageFilter
            # 잠금 창을 잠깐 숨기고 캡처 (자기 창 제외)
            self.win.after(0, self.win.withdraw)
            time.sleep(0.08)   # 숨김 반영 대기
            screenshot = ImageGrab.grab(
                bbox=(self.sx_off, self.sy_off,
                      self.sx_off + self.sw, self.sy_off + self.sh)
                if hasattr(self, 'sx_off') else None
            )
            self.win.after(0, self.win.deiconify)
            blurred = screenshot.filter(
                ImageFilter.GaussianBlur(radius=12)
            ).resize((self.sw, self.sh))
            # 메인 스레드에서 교체
            self.win.after(0, lambda: self._apply_blur_bg(blurred))
        except Exception as e:
            LOG.debug(f"[BlurBG] 블러 생성 실패: {e}")
            try:
                self.win.after(0, self.win.deiconify)
            except Exception:
                pass

    def _apply_blur_bg(self, pil_img):
        """메인 스레드에서 호출 — 블러 이미지로 lbl_bg 교체."""
        try:
            if not self.lbl_bg.winfo_exists():
                return
            # memo 모드에서는 lbl_bg가 place_forget 상태 → config 스킵
            if not self.lbl_bg.winfo_ismapped():
                LOG.debug("[BlurBG] lbl_bg 미표시 상태(memo 모드) → 블러 적용 스킵")
                return
            # ⚠️ FIX: media/split 모드는 lbl_bg가 미디어(영상·이미지) 표시용 →
            #    블러 스크린샷으로 덮으면 미디어가 사라짐. 미디어 모드에선 블러 스킵.
            _mode = self._content_map.get(0, self.app.config.get("screensaver_mode", "media"))
            if _mode in ("media", "split"):
                LOG.debug("[BlurBG] media/split 모드 → 미디어 보존 위해 블러 스킵")
                return
            photo = ImageTk.PhotoImage(pil_img)
            self.lbl_bg.config(image=photo, bg="black")
            self.lbl_bg._blur_ref = photo   # GC 방지
        except Exception as e:
            LOG.debug(f"[BlurBG] 적용 실패: {e}")
            # 실패해도 검은 배경 유지 → 보안 안전

    # ── 주 모니터 창 설정 ────────────────────────
    def _setup_window(self, x: int, y: int, w: int, h: int):
        self.win.configure(bg="black")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

        # ── geometry() 확정 후 실제 픽셀 크기 재측정 ────
        # DPI Aware 선언 후에도 Tkinter가 내부적으로 논리 픽셀을 쓸 수 있으므로
        # update() → winfo_width/height()로 실제 크기를 다시 읽어 sw/sh 보정.
        self.win.update()
        actual_w = self.win.winfo_width()
        actual_h = self.win.winfo_height()
        # 실측값이 유효하면(>1) 우선, 아니면 파라미터 값 사용
        self.sw = actual_w if actual_w > 1 else w
        self.sh = actual_h if actual_h > 1 else h
        self._media_w = self.sw
        self._media_h = self.sh
        LOG.info(f"창 크기 확정: 파라미터({w}×{h}) / 실측({actual_w}×{actual_h}) → 사용({self.sw}×{self.sh})")

        self.lbl_bg = tk.Label(self.win, bg="black")
        self.lbl_bg.place(x=0, y=0, width=self.sw, height=self.sh)

        # ── 배경 블러 (검은 선제 + 백그라운드 교체) ──────────
        # 리뷰 지적: 블러 완성 전 원본 화면 노출 = 보안 결함
        # 해결:
        #   1단계: 즉시 검은 레이어 (원본 화면 즉시 차단, 0ms)
        #   2단계: 백그라운드 스레드에서 스크린샷 캡처 + Gaussian Blur
        #   3단계: 완성 시 검은 레이어 → 블러 이미지로 교체
        if _HAS_PIL and self.app.config.get("blur_lock_bg", True):
            threading.Thread(
                target=self._capture_blur_bg,
                daemon=True
            ).start()

        self.lbl_clock = tk.Label(
            self.win, text="", fg="#cccccc", bg="black",
            font=("Consolas", 48)
        )
        # PIN 오버레이 (기본 숨김, ESC로 토글)
        self._pin_visible    = False
        self._lockout_after  = None
        self._build_pin_overlay()
        self.win.bind("<Escape>", self._on_escape)
        self.win.bind("<FocusOut>", self._on_focus_lost)
        self.win.bind("<Tab>", self._on_manual_next)   # 수동 전환: Tab으로 다음 항목
        self.win.focus_force()

    # ── 보조 모니터 검은 덮개 창 ────────────────
    def _create_cover_window(self, x: int, y: int, w: int, h: int) -> tk.Toplevel:
        """보조 모니터 전체를 덮는 검은 창 생성 (ESC·FocusOut 연동)."""
        cw = tk.Toplevel(self.app.root)
        cw.withdraw()
        cw.configure(bg="black")
        cw.overrideredirect(True)
        cw.attributes("-topmost", True)
        cw.geometry(f"{w}x{h}+{x}+{y}")
        cw.bind("<Escape>", self._on_escape)
        cw.bind("<FocusOut>", self._on_focus_lost)
        self._extra_wins.append(cw)
        return cw

    # ── 포커스 이탈 방지 ─────────────────────────
    def _on_focus_lost(self, event=None):
        """FocusOut 발생 시 100ms 뒤 포커스 강제 복구"""
        if self._reclaim_id:
            try:
                self.win.after_cancel(self._reclaim_id)
            except Exception:
                pass
        self._reclaim_id = self.win.after(100, self._reclaim_focus)

    def _reclaim_focus(self):
        self._reclaim_id = None
        if self.stop_event.is_set():
            return
        # PIN 창이 표시 중이면 메인 창이 포커스를 뺏지 않도록 차단
        if self._pin_visible:
            return
        try:
            for cw in self._extra_wins:
                cw.lift()
            self.win.lift()
            self.win.focus_force()
        except Exception:
            pass

    # ── 200ms 주기 포커스 방어 루프 ─────────────
    def _start_focus_guard(self):
        """상시 방어 루프 — topmost 재선언 + lift() 주기적 수행"""
        self._focus_guard_id = None
        self._focus_guard_tick()

    def _focus_guard_tick(self):
        if self.stop_event.is_set():
            return
        try:
            if self._pin_visible and self.pin_top:
                # ── PIN 표시 중: 메인 창 lift 중단 (Z-order 쟁탈 방지) ──
                # win.lift() + pin_top.lift()를 동시에 하면 200ms마다 깜빡임 발생.
                # PIN 창만 최상위 유지하고 메인 창은 건드리지 않는다.
                try:
                    if self.pin_top.winfo_exists():
                        self.pin_top.attributes("-topmost", True)
                        self.pin_top.lift()
                except Exception:
                    pass
            else:
                # ── 일반 모드: 모든 창 topmost 유지 ──────────────────────
                for cw in self._extra_wins:
                    cw.attributes("-topmost", True)
                    cw.lift()
                self.win.attributes("-topmost", True)
                self.win.lift()
        except Exception:
            pass
        self._focus_guard_id = self.win.after(200, self._focus_guard_tick)

    # ── 마우스 위치 → 해당 모니터 반환 ─────────
    def _get_monitor_at_cursor(self, mx: int, my: int) -> tuple:
        """(mx, my) 좌표가 속한 모니터 (x,y,w,h,is_primary) 반환.
        어느 모니터에도 없으면 주 모니터 반환."""
        for mon in self._monitors:
            x, y, w, h, _ = mon
            if x <= mx < x + w and y <= my < y + h:
                return mon
        return next((m for m in self._monitors if m[4]), self._monitors[0])

    # ── 핫플러그 감지 (5초 폴링) ─────────────────
    def _watch_monitor_changes(self):
        if self.stop_event.is_set():
            return
        current = _get_monitors_info()
        if len(current) != len(self._monitors):
            LOG.info(f"모니터 구성 변경 ({len(self._monitors)}대→{len(current)}대) — 보조 창 재생성")
            self.win.after(200, self._restart_cover)
            return
        self._monitor_watch_id = self.win.after(5000, self._watch_monitor_changes)

    def _restart_cover(self):
        """모니터 추가/제거 시 보조 창 전체 재생성"""
        for cw in self._extra_wins:
            try:
                cw.destroy()
            except Exception:
                pass
        self._extra_wins.clear()
        self._monitors = _get_monitors_info()
        primary = next((m for m in self._monitors if m[4]), self._monitors[0])
        px, py, pw, ph, _ = primary
        try:
            self.win.geometry(f"{pw}x{ph}+{px}+{py}")
            self.sw = pw
            self.sh = ph
        except Exception:
            pass
        for mon in self._monitors:
            mx, my, mw, mh, is_primary = mon
            if is_primary:
                continue
            cw = self._create_cover_window(mx, my, mw, mh)
            cw.deiconify()
        self._monitor_watch_id = self.win.after(5000, self._watch_monitor_changes)
        LOG.info("보조 창 재생성 완료")
        # 콘텐츠 맵 + 보조 뷰어 재생성
        self._content_map = self._build_content_map()
        self._render_secondary_windows()

    # ── 재생 목록 ────────────────────────────
    def _build_playlist(self):
        sel = self.app.config.get("selected_media", [])
        pl  = [f for f in sel if Path(f).exists()]
        if not pl:
            # 선택 없으면 즐겨찾기 전체 사용
            favs = load_favorites()
            pl = [f["path"] for f in favs if Path(f.get("path","")).exists()]
        is_premium  = self.app.config.get("is_premium", False)
        can_random  = TIER_CONFIG["premium" if is_premium else "free"]["random_play"]
        if can_random and self.app.config.get("slide_mode") == "random" and len(pl) > 1:
            random.shuffle(pl)
        return pl

    # ── 현재 미디어 재생 ─────────────────────
    # ── 모드 전환 전 UI 완전 초기화 ─────────────────
    def _cleanup_ui(self):
        """
        모드 전환 시 이전 모드의 UI 잔상을 완전히 제거.
        _play_current에서 모드가 변경될 때만 호출 (_prev_mode 비교).
        ① 메모 뷰어 destroy (메모 캔버스 잔존 방지)
        ② lbl_bg 전체화면 복원 (분할 모드 크기 잔존 방지)
        ③ _is_split / _prev_mode 초기화
        """
        # 메모 뷰어 제거
        if self._memo_viewer:
            try:
                self._memo_viewer.destroy()
            except Exception:
                pass
            self._memo_viewer = None

        # lbl_bg: 전체화면 크기로 복원
        try:
            self.lbl_bg.place(x=0, y=0, width=self.sw, height=self.sh)
        except Exception:
            pass

        # 상태 초기화
        self._is_split = False
        self._media_w  = self.sw
        self._media_h  = self.sh
        self._prev_mode = None   # 다음 _play_current에서 무조건 재초기화 허용

    def _play_current(self):
        if self.stop_event.is_set():
            return

        # 주 모니터(index 0) 콘텐츠 모드
        mode = self._content_map.get(0, self.app.config.get("screensaver_mode","media"))

        # ── _cleanup_ui: 모드가 실제로 바뀔 때만 호출 ──────────────
        # 이전: 매 _play_current 호출 시 실행 → 영상 전환마다 memo_viewer 파괴
        # 이후: 이전 모드와 다를 때만 실행 → 불필요한 파괴/재생성 제거
        prev_mode = getattr(self, '_prev_mode', None)
        if prev_mode != mode:
            self._cleanup_ui()
            self._prev_mode = mode
        if mode == "memo":
            try:
                self.lbl_bg.place_forget()
                self.lbl_bg.config(image="")   # 이미지 참조 명시 제거
                if self.win.winfo_exists():
                    self.win.update()
            except Exception:
                pass
            self._render_memo_board(self.win, self.sw, self.sh)
            return
        if mode == "split":
            # _cleanup_ui가 lbl_bg를 전체 크기로 복원해두었음
            # _render_split_mode에서 media_w 크기로 재설정
            self._render_split_mode()
            return
        # media 모드 — _cleanup_ui에서 이미 _is_split=False, lbl_bg 전체화면 복원됨
        if not self.playlist:
            self._show_clock()
            return
        if self._current_idx >= len(self.playlist):
            self._current_idx = 0
            if self.app.config.get("slide_mode") == "random":
                random.shuffle(self.playlist)
        fp  = self.playlist[self._current_idx]
        ext = Path(fp).suffix.lower()
        if ext in VIDEO_EXTS and _HAS_CV2 and _HAS_PIL:
            self._play_video(fp)
        elif ext in IMG_EXTS and _HAS_PIL:
            self._play_image(fp)
        else:
            self._advance()

    # ── 콘텐츠 맵 구성 ─────────────────────────
    def _build_content_map(self) -> dict:
        """
        monitor index → content 타입 매핑.
        주 모니터: 항상 global_mode (assignments 무시).
        보조 모니터: assignments 우선, 없으면 media 기본값.
                    split 값은 media로 보정 (보조에서 split 미지원).
        """
        assignments = {
            a["mon_key"]: a["content"]
            for a in self.app.config.get("monitor_assignments", [])
        }
        global_mode = self.app.config.get("screensaver_mode", "media")
        result = {}
        for i, mon in enumerate(self._monitors):
            mx, my, mw, mh, is_primary = mon
            mon_key = f"{mw}x{mh}+{mx}+{my}"
            if is_primary:
                # 주 모니터: 항상 글로벌 모드
                result[i] = global_mode
            else:
                # 보조 모니터: assignments 우선, 기본값=black(검은화면), split은 media로 보정
                content = assignments.get(mon_key, "black")
                if content == "split":
                    content = "media"
                result[i] = content
        return result

    # ── 주 모니터 메모 보드 렌더링 ─────────────
    def _render_memo_board(self, win: tk.Misc, sw: int, sh: int,
                           x: int = 0, y: int = 0):
        """주 모니터 창에 MemoBoardViewer 생성."""
        LOG.info(f"[MemoBoard] 1. 기존 메모 뷰어 정리 시작 (sw={sw} sh={sh})")
        if self._memo_viewer:
            try:
                self._memo_viewer.destroy()
                LOG.info("[MemoBoard] 2. 기존 메모 뷰어 완전 파괴 완료")
            except Exception as e:
                LOG.warning(f"[MemoBoard] 2. viewer destroy 오류: {e}")
            self._memo_viewer = None
        LOG.info("[MemoBoard] 3. 새 MemoBoardViewer 캔버스 생성 시작")
        self._memo_viewer = MemoBoardViewer(win, sw, sh, self.app, x=x, y=y)
        LOG.info("[MemoBoard] 4. MemoBoardViewer 생성 완료 — render() 호출")
        self._memo_viewer.render()
        # 캔버스를 최상위로 올림 + 즉시 박제
        try:
            if self._memo_viewer and self._memo_viewer.canvas:
                self._memo_viewer.canvas.lift()
                if self.win.winfo_exists():
                    self.win.update()
        except Exception:
            pass
        LOG.info("메모 보드 렌더링 완료")

    # ── split 모드 ──────────────────────────────
    def _render_split_mode(self):
        """미디어 + 메모 보드 분할 렌더링."""
        ratio = self.app.config.get("split_ratio", 0.65)
        direc = self.app.config.get("split_direction", "h")

        # 실제 창 크기 재측정 (DPI 환경에서 self.sw/sh와 다를 수 있음)
        actual_w = self.win.winfo_width()  or self.sw
        actual_h = self.win.winfo_height() or self.sh

        if direc == "h":    # 좌우 분할
            media_w = max(100, int(actual_w * ratio))
            media_h = actual_h
            memo_x, memo_y = media_w + 2, 0
            memo_w, memo_h = max(10, actual_w - media_w - 2), actual_h
        else:               # 상하 분할
            media_w = actual_w
            media_h = max(80, int(actual_h * ratio))
            memo_x, memo_y = 0, media_h + 2
            memo_w, memo_h = actual_w, max(10, actual_h - media_h - 2)

        LOG.info(f"[split] actual=({actual_w}×{actual_h}) "
                 f"media=({media_w}×{media_h}) "
                 f"memo=({memo_w}×{memo_h}) at ({memo_x},{memo_y})")

        # ① 미디어 변수 확정
        self._media_w  = media_w
        self._media_h  = media_h
        self._is_split = True

        # ② lbl_bg: 영상 영역에만 배치
        self.lbl_bg.place(x=0, y=0, width=media_w, height=media_h)

        # ── lbl_bg 실측 크기로 _media_w/h 재보정 ─────────────────────
        # Tkinter는 place() 직후 winfo_width()가 1을 반환할 수 있음.
        # update_idletasks()로 배치를 확정한 뒤 실측값을 읽어
        # _decode_loop의 _fit_frame에서 사용하는 _media_w/h를 정확히 맞춤.
        self.lbl_bg.update_idletasks()
        real_lbl_w = self.lbl_bg.winfo_width()
        real_lbl_h = self.lbl_bg.winfo_height()
        if real_lbl_w > 1:
            self._media_w = real_lbl_w
        if real_lbl_h > 1:
            self._media_h = real_lbl_h
        LOG.info(f"[split] lbl_bg 실측: {self._media_w}×{self._media_h}")

        # ③ 구분선
        sep = tk.Frame(self.win, bg="#444444")
        sep.place(
            x=media_w if direc == "h" else 0,
            y=0        if direc == "h" else media_h,
            width=2    if direc == "h" else actual_w,
            height=actual_h if direc == "h" else 2
        )

        # ④ 메모 뷰어: 메모 영역에만 배치 (영상 영역과 좌표 비침범)
        if self._memo_viewer:
            try:
                self._memo_viewer.destroy()
            except Exception:
                pass
        self._memo_viewer = MemoBoardViewer(
            self.win, memo_w, memo_h, self.app,
            x=memo_x, y=memo_y
        )
        self._memo_viewer.render()
        # ── z-order 개입 없음 ──────────────────────────────────────
        # 영상(lbl_bg)과 메모(canvas)의 place 좌표가 완전 분리되어 겹치지 않음.
        # lift()/lower()/after()는 오히려 배경 프레임 뒤로 숨기는 부작용 유발.
        # 좌표 분리만으로 두 위젯이 독립적으로 표시됨.

        # ⑥ 미디어 재생
        if not self.playlist:
            self._show_clock()
        else:
            if self._current_idx >= len(self.playlist):
                self._current_idx = 0
            fp  = self.playlist[self._current_idx]
            ext = Path(fp).suffix.lower()
            if ext in VIDEO_EXTS and _HAS_CV2 and _HAS_PIL:
                self._play_video(fp)
            elif ext in IMG_EXTS and _HAS_PIL:
                self._play_image(fp)
            else:
                self._advance()

    # ── 보조 모니터 콘텐츠 렌더링 (1회 호출) ────
    def _render_secondary_windows(self):
        """
        _extra_wins에 보조 모니터 배정 콘텐츠를 렌더링.
        media: 검은 창 유지.
        memo:  MemoBoardViewer 렌더링.
        split: _build_content_map에서 media로 보정됨.
        """
        for v in self._secondary_viewers:
            try:
                v.destroy()
            except Exception:
                pass
        self._secondary_viewers.clear()

        # 이미지 라벨 정리 (재생성 대비)
        for lbl in getattr(self, "_secondary_img_lbls", []):
            try:
                lbl.destroy()
            except Exception:
                pass
        self._secondary_img_lbls = []
        # 보조 영상 플레이어 정리 (재생성 대비)
        self._stop_secondary_video()

        secondary = [(i, m) for i, m in enumerate(self._monitors) if not m[4]]
        for j, (i, mon) in enumerate(secondary):
            if j >= len(self._extra_wins):
                break
            cw = self._extra_wins[j]
            _, _, mw, mh, _ = mon
            content = self._content_map.get(i, "media")
            if content == "memo":
                v = MemoBoardViewer(cw, mw, mh, self.app, is_secondary=True)
                v.render()
                self._secondary_viewers.append(v)
                LOG.info(f"보조 모니터 {i} → MemoBoardViewer 렌더링")
            elif content == "black":
                LOG.info(f"보조 모니터 {i} → 검은화면(사용자 지정)")
            elif content == "video":
                # 영상: 주 모니터가 영상 미사용(memo/black/clock 등)일 때만 + 동시 1개
                prim = self._content_map.get(
                    0, self.app.config.get("screensaver_mode", "media"))
                if prim in ("media", "split"):
                    LOG.info(f"보조 모니터 {i} → 영상 요청이나 주 모니터 영상 사용 중 → 검은화면(디코더 1개 제한)")
                elif self._sec_video_active:
                    LOG.info(f"보조 모니터 {i} → 영상은 동시 1개만 → 검은화면")
                elif self._start_secondary_video(cw, mw, mh):
                    LOG.info(f"보조 모니터 {i} → 영상 재생")
                else:
                    LOG.info(f"보조 모니터 {i} → 영상 파일 없음 → 검은화면")
            else:
                # media 배정 = 이미지만 렌더(동영상 제외 — 보조 미지원). 이미지 없으면 검은 창.
                if self._render_secondary_image(cw, mw, mh):
                    LOG.info(f"보조 모니터 {i} → 이미지 렌더링(영상 제외)")
                else:
                    LOG.info(f"보조 모니터 {i} → 이미지 없음, 검은 창 유지")

    def _render_secondary_image(self, cw, w: int, h: int) -> bool:
        """보조 모니터에 정적 이미지 1장 렌더(동영상은 제외). 성공 시 True."""
        if not _HAS_PIL:
            return False
        sel = [f for f in self.app.config.get("selected_media", [])
               if Path(f).exists() and Path(f).suffix.lower() in IMG_EXTS]
        if not sel:
            favs = load_favorites()
            sel = [f["path"] for f in favs
                   if Path(f.get("path", "")).exists()
                   and Path(f.get("path", "")).suffix.lower() in IMG_EXTS]
        if not sel:
            return False
        try:
            with Image.open(sel[0]) as img:
                img.load()
                work = img.copy()
            work.thumbnail((w, h), Image.LANCZOS)
            bg = Image.new('RGB', (w, h), (0, 0, 0))
            bg.paste(work, ((w - work.width) // 2, (h - work.height) // 2))
            photo = ImageTk.PhotoImage(bg)
            lbl = tk.Label(cw, image=photo, bg="black", borderwidth=0)
            lbl.image = photo
            lbl.place(x=0, y=0, width=w, height=h)
            self._secondary_img_lbls.append(lbl)
            return True
        except Exception as e:
            LOG.error(f"보조 이미지 렌더 실패: {e}")
            return False

    # ── 보조 모니터 영상(격리 플레이어) ──────────
    def _start_secondary_video(self, cw, w: int, h: int) -> bool:
        """보조 모니터에 영상 1개 반복 재생(격리 스레드/큐). 성공 시 True.
        주 디코더 미사용 시에만 호출됨(동시 디코더 1개 보장)."""
        if not (_HAS_CV2 and _HAS_PIL):
            return False
        sel = [f for f in self.app.config.get("selected_media", [])
               if Path(f).exists() and Path(f).suffix.lower() in VIDEO_EXTS]
        if not sel:
            favs = load_favorites()
            sel = [f["path"] for f in favs
                   if Path(f.get("path", "")).exists()
                   and Path(f.get("path", "")).suffix.lower() in VIDEO_EXTS]
        if not sel:
            return False
        self._sec_video_path = sel[0]
        self._sec_video_w, self._sec_video_h = w, h
        self._sec_video_win = cw
        self._sec_stop = threading.Event()
        self._sec_q = queue.Queue(maxsize=2)
        lbl = tk.Label(cw, bg="black", borderwidth=0)
        lbl.place(x=0, y=0, width=w, height=h)
        self._sec_video_lbl = lbl
        self._sec_decode_thr = threading.Thread(
            target=self._sec_decode_loop, daemon=True)
        self._sec_decode_thr.start()
        self._sec_video_active = True
        self._sec_poll_video()
        return True

    def _sec_fit(self, frame, tw: int, th: int):
        """Aspect Fill(center crop) — 보조 영상 전용 numpy 합성."""
        import numpy as _np
        fh, fw = frame.shape[:2]
        if tw <= 0 or th <= 0:
            return frame
        scale = max(tw / fw, th / fh)
        nw, nh = max(1, int(fw * scale)), max(1, int(fh * scale))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        pad_x, pad_y = (tw - nw) // 2, (th - nh) // 2
        canvas = _np.zeros((th, tw, 3), dtype=_np.uint8)
        dst_y0 = max(0, pad_y);  dst_y1 = min(th, pad_y + nh)
        dst_x0 = max(0, pad_x);  dst_x1 = min(tw, pad_x + nw)
        src_y0 = max(0, -pad_y); src_y1 = src_y0 + (dst_y1 - dst_y0)
        src_x0 = max(0, -pad_x); src_x1 = src_x0 + (dst_x1 - dst_x0)
        canvas[dst_y0:dst_y1, dst_x0:dst_x1] = resized[src_y0:src_y1, src_x0:src_x1]
        return canvas

    def _sec_decode_loop(self):
        cap = cv2.VideoCapture(self._sec_video_path)
        if not cap.isOpened():
            LOG.error(f"보조 영상 열기 실패: {self._sec_video_path}")
            return
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            delay = 1.0 / fps
            fail = 0
            while not self._sec_stop.is_set():
                ret, frame = cap.read()
                if not ret:          # 단일 영상 반복
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    fail += 1
                    if fail > 3:
                        LOG.error(f"보조 영상 손상 추정: {self._sec_video_path}")
                        break
                    continue
                fail = 0
                rgb = cv2.cvtColor(
                    self._sec_fit(frame, self._sec_video_w, self._sec_video_h),
                    cv2.COLOR_BGR2RGB)
                try:
                    self._sec_q.put(rgb, timeout=0.05)
                except queue.Full:
                    pass
                time.sleep(delay)
        finally:
            cap.release()

    def _sec_poll_video(self):
        if getattr(self, "_sec_stop", None) is None or self._sec_stop.is_set():
            return
        lbl = getattr(self, "_sec_video_lbl", None)
        if not lbl or not lbl.winfo_exists():
            return
        try:
            rgb = self._sec_q.get_nowait()
            if rgb is not None:
                photo = ImageTk.PhotoImage(Image.fromarray(rgb))
                lbl.config(image=photo)
                lbl.image = photo
        except queue.Empty:
            pass
        except tk.TclError:
            return
        except Exception as e:
            LOG.error(f"보조 영상 프레임 오류: {e}")
        if not self._sec_stop.is_set():
            interval = 200 if self._pin_visible else 33
            self._sec_after_id = self._sec_video_win.after(
                interval, self._sec_poll_video)

    def _stop_secondary_video(self):
        ev = getattr(self, "_sec_stop", None)
        if ev:
            ev.set()
        aid = getattr(self, "_sec_after_id", None)
        if aid:
            try:
                self._sec_video_win.after_cancel(aid)
            except Exception:
                pass
            self._sec_after_id = None
        thr = getattr(self, "_sec_decode_thr", None)
        if thr and thr.is_alive():
            thr.join(timeout=0.5)
        self._sec_decode_thr = None
        lbl = getattr(self, "_sec_video_lbl", None)
        if lbl:
            try:
                lbl.destroy()
            except Exception:
                pass
            self._sec_video_lbl = None
        q = getattr(self, "_sec_q", None)
        if q:
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
        self._sec_video_active = False

    # ══════════════════════════════════════
    # 동영상 재생 (디코드 스레드 + queue)
    # ══════════════════════════════════════
    def _play_video(self, filepath):
        self.stop_event.clear()
        self._decode_thr = threading.Thread(
            target=self._decode_loop, args=(filepath,), daemon=True
        )
        self._decode_thr.start()
        self._poll_video()

    def _decode_loop(self, filepath):
        cap = cv2.VideoCapture(filepath)
        if not cap.isOpened():
            LOG.error(f"영상 열기 실패: {filepath}")
            return
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            delay = 1.0 / fps
            single = len(self.playlist) <= 1
            fail_count = 0

            while not self.stop_event.is_set():
                ret, frame = cap.read()
                if not ret:
                    if single:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        fail_count += 1
                        if fail_count > 3:
                            LOG.error(f"영상 손상 추정: {filepath}")
                            break
                        continue
                    break
                fail_count = 0
                frame = self._fit_frame(frame)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                try:
                    self.frame_queue.put(rgb, timeout=0.05)
                except queue.Full:
                    pass
                time.sleep(delay)
        finally:
            cap.release()
        if not self.stop_event.is_set():
            try:
                self.frame_queue.put(None, timeout=0.1)
            except queue.Full:
                pass

    def _fit_frame(self, frame):
        """
        조건부 스케일링 — 모드에 따라 자동 전환:
          split 모드  → Aspect Fit  (min 스케일): 영상 전체 노출 + 검은 여백(letterbox)
          media 모드  → Aspect Fill (max 스케일): 화면 꽉 채움 + 가장자리 잘림 허용
        numpy 기반 합성으로 PIL bg_img 단계 제거 → _poll_video에 최종 배열 반환.
        """
        h, w  = frame.shape[:2]
        tw, th = self._media_w, self._media_h

        # _media_w/h가 아직 확정되지 않은 경우 lbl_bg 실측값으로 폴백
        # (스레드 시작 직후 Tkinter 배치 미완료 타이밍 방어)
        if tw <= 1 or th <= 1:
            try:
                tw = self.lbl_bg.winfo_width()
                th = self.lbl_bg.winfo_height()
            except Exception:
                pass
        if tw <= 0 or th <= 0:
            return frame

        if self._is_split:
            # ── Aspect Fit: min 스케일, letterbox ────────────
            scale = min(tw / w, th / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            pad_x = (tw - nw) // 2
            pad_y = (th - nh) // 2
        else:
            # ── Aspect Fill: max 스케일, center crop ─────────
            scale = max(tw / w, th / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            pad_x = (tw - nw) // 2   # 음수 → crop 오프셋
            pad_y = (th - nh) // 2

        # numpy 검은 캔버스 위에 영상 합성 (양수 pad → letterbox, 음수 → crop)
        canvas = __import__('numpy').zeros((th, tw, 3), dtype=__import__('numpy').uint8)
        dst_y0 = max(0,  pad_y);  dst_y1 = min(th, pad_y + nh)
        dst_x0 = max(0,  pad_x);  dst_x1 = min(tw, pad_x + nw)
        src_y0 = max(0, -pad_y);  src_y1 = src_y0 + (dst_y1 - dst_y0)
        src_x0 = max(0, -pad_x);  src_x1 = src_x0 + (dst_x1 - dst_x0)
        canvas[dst_y0:dst_y1, dst_x0:dst_x1] = resized[src_y0:src_y1, src_x0:src_x1]
        return canvas

    def _poll_video(self):
        if self.stop_event.is_set():
            return
        # 퀵 메모 전환 등으로 lbl_bg가 파괴된 경우 메모리 접근 차단
        if not hasattr(self, 'lbl_bg') or not self.lbl_bg.winfo_exists():
            return
        try:
            rgb = self.frame_queue.get_nowait()
            if rgb is None:
                self._advance()
                return
            photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.lbl_bg.config(image=photo)
            self.lbl_bg.image = photo
        except queue.Empty:
            pass
        except tk.TclError:
            return
        except Exception as e:
            LOG.error(f"프레임 표시 오류: {e}")
        if not self.stop_event.is_set():
            interval = 200 if self._pin_visible else 33
            self._after_id = self.win.after(interval, self._poll_video)

    # ══════════════════════════════════════
    # 이미지 표시
    # ══════════════════════════════════════
    def _play_image(self, filepath):
        try:
            with Image.open(filepath) as img:
                img.load()
                work = img.copy()
            work.thumbnail((self._media_w, self._media_h), Image.LANCZOS)
            bg_img = Image.new('RGB', (self._media_w, self._media_h), (0, 0, 0))
            ofs = ((self._media_w - work.width) // 2, (self._media_h - work.height) // 2)
            bg_img.paste(work, ofs)
            photo = ImageTk.PhotoImage(bg_img)
            self.lbl_bg.config(image=photo)
            self.lbl_bg.image = photo
        except Exception as e:
            LOG.error(f"이미지 표시 실패: {e}")
            self._advance()
            return
        # 자동 모드에서만 초 간격 자동 전환. 수동 모드는 Tab 대기.
        if len(self.playlist) > 1 and self.app.config.get("slide_auto", True):
            sec = self.app.config.get("media_interval_seconds", 10)
            interval = max(1, int(sec)) * 1000
            self._after_id = self.win.after(interval, self._advance)

    # ══════════════════════════════════════
    # 시계 (미디어 없을 때)
    # ══════════════════════════════════════
    def _show_clock(self):
        self.lbl_bg.config(image="", bg="black")
        self.lbl_bg.image = None
        self.lbl_clock.place(relx=0.5, rely=0.5, anchor="center")
        self._tick_clock()

    def _tick_clock(self):
        if self.stop_event.is_set():
            return
        self.lbl_clock.config(text=time.strftime("%H:%M:%S\n%Y-%m-%d"))
        self._after_id = self.win.after(1000, self._tick_clock)

    # ══════════════════════════════════════
    # 다음 미디어 / 종료
    # ══════════════════════════════════════
    def _on_manual_next(self, event=None):
        """Tab: 다음 항목으로 즉시 전환(수동/자동 공통 — 진행 중 자동 타이머 취소 후 advance)."""
        if len(self.playlist) > 1:
            if self._after_id:
                try: self.win.after_cancel(self._after_id)
                except Exception: pass
                self._after_id = None
            self._advance()
        return "break"

    def _advance(self):
        self.stop_event.set()
        if self._decode_thr and self._decode_thr.is_alive():
            self._decode_thr.join(timeout=0.5)
        self._decode_thr = None
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        self._current_idx += 1
        self.stop_event.clear()
        self.win.after(50, self._play_current)

    # ══════════════════════════════════════
    # Stage 6 — PIN 오버레이 (ESC 토글)
    # ══════════════════════════════════════

    def _build_pin_overlay(self):
        """PIN Toplevel 상태 초기화 (실제 창은 _show_pin_overlay에서 생성)."""
        self.pin_top          = None
        self.pin_var          = tk.StringVar()
        self.pin_entry        = None
        self.pin_err          = None
        self._pin_clock_after  = None
        self._lbl_pin_time    = None   # 시간 라벨 (HH:MM:SS)
        # self._lbl_pin_clock는 날짜 라벨 — 기존 이름 유지

    # ── ESC 키 처리 ─────────────────────────
    def _on_escape(self, event=None):
        # 일반 보안 잠금 모드: PIN 오버레이 토글
        if not self.app.config.get("pin_set"):
            self.close()
            return
        if self._pin_visible:
            self._hide_pin_overlay()
        else:
            self._show_pin_overlay()

    def _show_pin_overlay(self):
        L = self.app.config.get("language", "ko")
        # 이미 표시 중이면 최상위로 올리고 포커스 강제 탈환
        if self.pin_top:
            try:
                if self.pin_top.winfo_exists():
                    self.pin_top.attributes("-topmost", True)
                    self.pin_top.lift()
                    self.pin_top.grab_set()
                    if self.pin_entry:
                        self.pin_entry.focus_force()
                    return
                else:
                    # 외부(OS/예외)에 의해 파괴됨 — 좀비 상태 정리
                    self.pin_top = None
                    self._pin_visible = False
            except Exception:
                self.pin_top = None
                self._pin_visible = False

        # ── 마우스 좌표 → 대상 모니터 중앙 계산 ──
        try:
            mx, my = self.win.winfo_pointerxy()
        except Exception:
            mx, my = 0, 0
        mon = self._get_monitor_at_cursor(mx, my)
        mon_x, mon_y, mon_w, mon_h, _ = mon
        # ── 창 크기 + 스케일 ──────────────────────────
        pin_msg       = self.app.config.get("pin_message", "").strip()
        msg_font_size = self.app.config.get("pin_message_font_size", 12)

        # 모니터 너비 기준 스케일 (폰트 크기 계산용)
        scale   = mon_w / 1000.0
        time_fs = max(14, min(48, int(22 * scale)))
        date_fs = max(9,  min(22, int(11 * scale)))

        # ── 패러다임 전환: 글자 크기 → 창 크기 역산 ──
        # "창을 먼저 만들고 글자를 넣는 것"이 아니라
        # "글자의 크기를 먼저 재고 그에 맞춰 창을 재단"
        import tkinter.font as _tkfont_pin
        f_time = _tkfont_pin.Font(font=_safe_font("Malgun Gothic", time_fs, "bold"))
        f_date = _tkfont_pin.Font(font=_safe_font("Malgun Gothic", date_fs))
        f_msg  = _tkfont_pin.Font(font=_safe_font("Malgun Gothic", msg_font_size, "italic"))

        # 너비(DW): 시간/날짜 중 더 긴 텍스트 + 좌우 여백
        sample_date  = "2026년 12월 31일 (수)"   # 가장 긴 날짜 예시
        sample_time  = "00:00:00"
        max_text_w   = max(f_time.measure(sample_time), f_date.measure(sample_date))
        DW = max(320, max_text_w + int(80 * scale))   # 최소 320px 보장
        DW = min(700, DW)   # 최대 700px 상한

        # 헤더 높이: 시간 linespace + 날짜 linespace + 상하 여백
        PAD_TOP = max(8,  int(10 * scale))
        PAD_BTW = max(2,  int(4  * scale))   # 시간-날짜 사이 간격
        PAD_BOT = max(10, int(14 * scale))   # 하단 여백 (오차 흡수용 +8)
        HDR_H   = PAD_TOP + f_time.metrics("linespace") + PAD_BTW \
                           + f_date.metrics("linespace") + PAD_BOT
        HDR_H   = max(48, HDR_H)

        # 높이(DH): 각 영역 높이를 블록 쌓듯 합산 (고정값 110 제거)
        import math as _math

        # ── 고정 상수 (각 위젯 실측 근사) ────────
        PAD_INNER     = 8    # 헤더-카드 간격
        PAD_MSG_TOP   = 14   # 메시지 상단 pady
        ENTRY_CARD_H  = 55   # entry_card Frame (pin_row + 내부 패딩)
        PIN_ERR_H     = 22   # 오류 라벨 (비어있어도 공간 점유)
        BTN_ROW_H     = 44   # 버튼 행 (pady=10+4 포함)
        HINT_H        = 18   # ESC 힌트 라벨 (pady=10 포함)
        PAD_BOTTOM    = 8    # 카드 하단 여백

        # ── 메시지 높이 정밀 계산 ─────────────────
        if pin_msg:
            try:
                msg_linespace = f_msg.metrics("linespace")
                display_sample = f'"{pin_msg[:30]}"'
                msg_px_w = f_msg.measure(display_sample)
                wrap_w   = max(1, DW - 36)
                n_lines  = _math.ceil(msg_px_w / wrap_w)
                h_msg    = PAD_MSG_TOP + (msg_linespace * n_lines) + 10
            except Exception:
                h_msg = 40   # 측정 실패 시 폴백
        else:
            h_msg = 0

        # ── 카드 영역 합계 ────────────────────────
        pad_top_entry_val = 10 if pin_msg else 20   # entry_card 상단 여백
        h_entry_fixed     = ENTRY_CARD_H + PIN_ERR_H + BTN_ROW_H + HINT_H + PAD_BOTTOM
        h_card_content    = h_msg + pad_top_entry_val + h_entry_fixed

        # ── 전체 높이 역산 ────────────────────────
        DH_required = HDR_H + PAD_INNER + h_card_content
        # 하한 280px 보장 / 상한 모니터 높이 80% 적용
        DH = max(280, min(int(mon_h * 0.8), DH_required))

        dlg_x = mon_x + (mon_w - DW) // 2
        dlg_y = mon_y + (mon_h - DH) // 2

        # ── PIN Toplevel ───────────────────────
        BG      = "#16181d"
        HDR_BG  = "#1f2330"
        CARD_BG = "#22263a"
        ACCENT  = "#5b8dee"
        GOLD    = "#f0c040"
        FG_DIM  = "#6b7280"
        FG_MID  = "#9ca3af"
        FG_MAIN = "#e5e7eb"

        top = tk.Toplevel(self.win)
        top.transient(self.win)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=BG)
        top.geometry(f"{DW}x{DH}+{dlg_x}+{dlg_y}")
        top.grab_set()
        top.protocol("WM_DELETE_WINDOW", self._hide_pin_overlay)
        self.pin_top = top

        # ── 바깥 테두리 (Canvas 1px) ─────────
        # geometry 적용 직후 update_idletasks로 실제 크기 확정 후 그리기
        top.update_idletasks()
        real_w = top.winfo_width()  or DW
        real_h = top.winfo_height() or DH
        bd_canvas = tk.Canvas(top, width=real_w, height=real_h,
                              highlightthickness=0, bd=0, bg=BG)
        bd_canvas.place(x=0, y=0)
        bd_canvas.create_rectangle(0, 0, real_w-1, real_h-1,
                                   outline=ACCENT, width=1)

        # ── 헤더 영역 (동적 높이) ─────────────
        hdr = tk.Frame(top, bg=HDR_BG, height=HDR_H)
        hdr.place(x=1, y=1, width=DW-2, height=HDR_H)

        # 시간 라벨 (크고 굵게 — 주인공)
        pady_top = max(6, int(10 * scale))
        self._lbl_pin_time = tk.Label(
            hdr, text="",
            font=_safe_font("Malgun Gothic", time_fs, "bold"),
            fg=FG_MAIN, bg=HDR_BG
        )
        self._lbl_pin_time.place(relx=0.5, y=pady_top, anchor="n")

        # 날짜 라벨 (작고 흐리게 — 보조)
        time_lbl_h = time_fs + 8   # 시간 라벨 높이 근사
        self._lbl_pin_clock = tk.Label(
            hdr, text="",
            font=_safe_font("Malgun Gothic", date_fs),
            fg=FG_MID, bg=HDR_BG
        )
        self._lbl_pin_clock.place(relx=0.5, y=pady_top + time_lbl_h + 2, anchor="n")

        # 헤더 하단 구분선 (ACCENT 1px)
        tk.Frame(top, bg=ACCENT, height=1).place(x=1, y=HDR_H + 1, width=DW-2)

        # ── 카드 배치 좌표 (PAD_INNER 기반으로 DH 계산과 일치) ──
        card_y = HDR_H + PAD_INNER
        card_h = DH - card_y - 4   # 하단 4px 여백
        card = tk.Frame(top, bg=BG)
        card.place(x=1, y=card_y, width=DW-2, height=card_h)

        # 사용자 메시지 — config의 폰트 크기 적용
        if pin_msg:
            display_msg = pin_msg[:30] + ("…" if len(pin_msg) > 30 else "")
            tk.Label(
                card, text=f'"{display_msg}"',
                font=_safe_font("Malgun Gothic", msg_font_size, "italic"),
                fg=FG_MID, bg=BG, wraplength=DW - 36
            ).pack(pady=(PAD_MSG_TOP, 0))
        entry_pack_pady = pad_top_entry_val

        # ── PIN 입력 카드 프레임 ──────────────
        entry_card = tk.Frame(card, bg=CARD_BG,
                              highlightbackground=ACCENT,
                              highlightthickness=1)
        entry_card.pack(pady=(entry_pack_pady, 0), padx=28)

        pin_row = tk.Frame(entry_card, bg=CARD_BG)
        pin_row.pack(padx=12, pady=8)

        tk.Label(
            pin_row, text="🔒",
            font=("Arial", 12), fg=GOLD, bg=CARD_BG
        ).pack(side="left", padx=(0, 8))

        self.pin_var.set("")
        self.pin_entry = ttk.Entry(
            pin_row, show="\u25CF", width=14,
            justify="center", textvariable=self.pin_var,
            font=("Arial", 15)
        )
        self.pin_entry.pack(side="left")
        self.pin_entry.bind("<Return>", lambda e: self._verify_pin_unlock())

        # ── 오류 메시지 ──────────────────────
        self.pin_err = tk.Label(
            card, text="", fg="#f87171", bg=BG,
            font=_safe_font("Malgun Gothic", 9)
        )
        self.pin_err.pack(pady=(6, 0))

        # ── 버튼 행 (커스텀 Canvas 버튼) ─────
        btn_row = tk.Frame(card, bg=BG)
        btn_row.pack(pady=(10, 0))

        def _make_btn(parent, text, cmd, primary=False):
            """호버 효과 있는 커스텀 버튼."""
            c_bg   = ACCENT  if primary else "#2d3148"
            c_fg   = "#ffffff" if primary else FG_MID
            c_hov  = "#7aa3f5" if primary else "#3d4160"
            btn_f  = tk.Frame(parent, bg=c_bg, cursor="hand2")
            lbl    = tk.Label(btn_f, text=text, bg=c_bg, fg=c_fg,
                              font=_safe_font("Malgun Gothic", 10, "bold" if primary else "normal"),
                              padx=18, pady=6)
            lbl.pack()
            for w in (btn_f, lbl):
                w.bind("<Enter>",  lambda e, f=btn_f, l=lbl, h=c_hov: (
                    f.config(bg=h), l.config(bg=h)))
                w.bind("<Leave>",  lambda e, f=btn_f, l=lbl, b=c_bg: (
                    f.config(bg=b), l.config(bg=b)))
                w.bind("<Button-1>", lambda e, fn=cmd: fn())
            return btn_f

        _make_btn(btn_row, t("btn_confirm", L),   self._verify_pin_unlock, primary=True
                  ).pack(side="left", padx=(0, 8))
        _make_btn(btn_row, t("btn_hide", L), self._hide_pin_overlay, primary=False
                  ).pack(side="left")

        # ── 힌트 ─────────────────────────────
        tk.Label(card, text=t("lbl_esc_hide", L),
                 fg=FG_DIM, bg=BG, font=("Arial", 8)).pack(pady=(10, 0))

        top.bind("<Escape>", self._on_escape)

        self._pin_visible = True
        try:
            self.pin_entry.focus_force()
        except Exception:
            pass
        LOG.debug("[PIN] 위젯 생성 완료 — 시계 루프 시작")
        try:
            self._tick_pin_clock()
        except Exception as e:
            LOG.error(f"[PIN] _tick_pin_clock 초기 호출 실패: {e}")
        try:
            self._update_lockout_display()
        except Exception as e:
            LOG.error(f"[PIN] _update_lockout_display 초기 호출 실패: {e}")
        LOG.debug(f"PIN 오버레이 표시: 모니터({mon_x},{mon_y}) 중앙 ({dlg_x},{dlg_y})")

    # ── PIN 시계 갱신 루프 ─────────────────
    def _tick_pin_clock(self):
        """PIN 창이 열린 동안 시간·날짜 라벨 실시간 갱신.
        시간: 1초 주기 (HH:MM:SS), 날짜: 1초 주기 함께 갱신."""
        L = self.app.config.get("language", "ko")
        if not self._pin_visible or not self.pin_top:
            return
        try:
            if not self.pin_top.winfo_exists():
                return
            import datetime as _dt
            now  = _dt.datetime.now()
            wd   = t("lbl_weekdays", L).split(",")[now.weekday()]

            # 시간 라벨 (HH:MM:SS — 초단위 표시)
            if hasattr(self, '_lbl_pin_time') and self._lbl_pin_time:
                try:
                    self._lbl_pin_time.config(
                        text=now.strftime("%H:%M:%S")
                    )
                except Exception:
                    pass

            # 날짜 라벨 (YYYY년 M월 D일 (요))
            if hasattr(self, '_lbl_pin_clock') and self._lbl_pin_clock:
                try:
                    self._lbl_pin_clock.config(
                        text=t("lbl_date_fmt", L).format(y=now.year, m=now.month, d=now.day, wd=wd)
                    )
                except Exception:
                    pass
        except Exception:
            return
        # 1초마다 갱신 (시·분·초 모두 표시하므로 1000ms 고정)
        self._pin_clock_after = self.win.after(1000, self._tick_pin_clock)

    def _hide_pin_overlay(self):
        # 시계 after 콜백 정리
        if self._pin_clock_after:
            try:
                self.win.after_cancel(self._pin_clock_after)
            except Exception:
                pass
            self._pin_clock_after = None
        if self._lockout_after:
            try:
                self.win.after_cancel(self._lockout_after)
            except Exception:
                pass
            self._lockout_after = None
        if self.pin_top:
            try:
                self.pin_top.destroy()
            except Exception:
                pass
            self.pin_top = None
        self.pin_entry = None
        self.pin_err   = None
        self._lbl_pin_time  = None   # 시간 라벨 참조 해제
        self._pin_visible = False
        self.pin_var.set("")
        # ── 포커스 메인 창 반환 ─────────────────────
        # pin_top.destroy() 후 포커스가 허공으로 사라지면
        # 다음 ESC 이벤트가 self.win에 도달하지 못해 재소환 불가.
        try:
            self.win.focus_force()
        except Exception:
            pass

    # ── 잠금 카운트다운 표시 ────────────────
    def _update_lockout_display(self):
        L = self.app.config.get("language", "ko")
        if not self._pin_visible:
            return
        # PIN Toplevel이 파기된 경우 방어
        if not self.pin_top or not self.pin_entry or not self.pin_err:
            return
        try:
            if not self.pin_top.winfo_exists():
                return
        except Exception:
            return
        locked_until = self.app._pin_locked_until
        if locked_until > time.time():
            remaining = int(locked_until - time.time()) + 1
            self.pin_err.config(text=t("pin_5fail_timer", L).format(remaining=remaining))
            try:
                self.pin_entry.config(state="disabled")
            except Exception:
                pass
            self._lockout_after = self.win.after(1000, self._update_lockout_display)
        else:
            try:
                self.pin_entry.config(state="normal")
                self.pin_entry.focus_set()
            except Exception:
                pass
            cur = self.pin_err.cget("text")
            if cur:
                self.pin_err.config(text="")

    # ── PIN 검증 후 잠금 해제 ───────────────
    def _verify_pin_unlock(self):
        L = self.app.config.get("language", "ko")
        # 잠금 중이면 무시
        if self.app._pin_locked_until > time.time():
            return
        pin_input = self.pin_var.get()
        if not pin_input:
            return

        if verify_pin(pin_input, self.app.config):
            was_master = _verify_master(pin_input)
            self.app._pin_fail_count = 0
            LOG.info(f"화면보호기 잠금 해제 (마스터키: {was_master})")
            self._unlock_done(was_master)
        else:
            self.app._pin_fail_count += 1
            self.pin_var.set("")
            LOG.warning(f"잠금 해제 실패 {self.app._pin_fail_count}/5")
            if self.app._pin_fail_count >= 5:
                self.app._pin_locked_until = time.time() + 30
                self.app._pin_fail_count = 0
                self._update_lockout_display()
            else:
                remaining = 5 - self.app._pin_fail_count
                self.pin_err.config(text=t("pin_fail_count", L).format(remaining=remaining))

    def _unlock_done(self, was_master):
        L = self.app.config.get("language", "ko")
        # close() 먼저 실행 → 이후 main 창에서 마스터키 안내
        app = self.app
        self.close()
        if was_master and app.config.get("pin_set"):
            try:
                if messagebox.askyesno(
                    t("pin_master_use", L),
                    t("pin_master_msg", L),
                    parent=app.root
                ):
                    clear_pin(app.config)
                    save_config(app.config)
                    app._refresh_pin_label()
                    LOG.info("마스터키 사용 후 PIN 초기화")
            except Exception as e:
                LOG.error(f"마스터키 안내 오류: {e}")

    def close(self):
        self.stop_event.set()
        # 모든 pending after 콜백 정리
        for attr in ('_after_id', '_lockout_after', '_monitor_watch_id',
                     '_reclaim_id', '_focus_guard_id', '_pin_clock_after'):
            aid = getattr(self, attr, None)
            if aid:
                try:
                    self.win.after_cancel(aid)
                except Exception:
                    pass
                setattr(self, attr, None)
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break
        # PIN Toplevel 파기
        if getattr(self, 'pin_top', None):
            try:
                self.pin_top.destroy()
            except Exception:
                pass
            self.pin_top = None
        # 메모 뷰어 파기
        if getattr(self, '_memo_viewer', None):
            try:
                self._memo_viewer.destroy()
            except Exception:
                pass
            self._memo_viewer = None
        # 보조 영상 플레이어 정지(스레드/after/라벨)
        self._stop_secondary_video()
        for v in getattr(self, '_secondary_viewers', []):
            try:
                v.destroy()
            except Exception:
                pass
        self._secondary_viewers = []
        # 보조 모니터 창 일괄 파기
        for cw in getattr(self, '_extra_wins', []):
            try:
                cw.destroy()
            except Exception:
                pass
        self._extra_wins = []
        try:
            self.win.destroy()
        except Exception:
            pass
        self.app._screensaver = None
        self.app._ss_closed_at = time.time()
        self.app.audio_controller.restore_audio(
            self.app.config.get("mute_on_screensaver", False)
        )
        LOG.info("화면보호기 종료")
