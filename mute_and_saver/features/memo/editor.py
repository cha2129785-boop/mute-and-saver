# -*- coding: utf-8 -*-
"""
editor — FullscreenMemoEditor: 전체화면 메모 편집기 (드래그/리사이즈/편집/우클릭)
"""
import copy
import logging
import time
import tkinter as tk
from tkinter import simpledialog, colorchooser, messagebox, filedialog

LOG = logging.getLogger("MuteAndSaver")

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from ...constants import (
    MEMO_BG_THEMES, MEMO_TEMPLATES, OPACITY_PRESETS, TIER_CONFIG, _CANVAS_BG,
    _blend_color, TEXT_COLORS, _darken,
)
from ...i18n import t
from ...media.image_rendering import _safe_font, _render_canvas_bg
from ...persistence import load_memos, save_memos, get_all_themes, save_config
from ...platform.windows.monitor import _get_monitors_info
from .coordinates import _abs_to_rel
from .models import (new_memo_template, new_table, build_calendar_table,
                     _get_visible_memos, _is_scheduled_now, _memo_text_color,
                     resolve_text_color, TABLE_MAX_ROWS, TABLE_MAX_COLS)

class FullscreenMemoEditor:
    """
    실제 모니터 해상도 위에서 메모를 직접 편집하는 전체화면 에디터.

    v2 기능:
      - 드래그 (위치) — 제목/본문 모두 잡고 이동
      - 리사이즈 (크기) — 우하단 핸들 드래그
      - 더블클릭 (내용 편집) — 제목 Entry / 본문 Text 인라인 편집
      - ESC 계층: 편집 모드 → 드래그 모드 → 창 닫기

    DPI 보정: _get_monitors_info() 물리 픽셀 기반.
    grab_set/release: try-finally로 어떤 경로에서도 반드시 해제.
    Singleton: _open_fullscreen_editor에서 중복 인스턴스 방어.
    IME 한계: overrideredirect 창에서 IME 위치 부정확 — 알려진 Tkinter 한계.
    """

    MIN_W      = 80
    MIN_H      = 50
    HANDLE_SZ  = 14   # 리사이즈 핸들 크기

    # FSEditor 카드 색상 — (헤더색, 배경색, 그림자배경색)
    # MEMO_COLORS와 색상 키 동기화 (MemoBoardViewer와 동일 key 사용)
    COLORS = {
        "yellow": ("#f0c040", "#1a1a0a", "#111100"),
        "blue":   ("#5b8dee", "#0a0a1a", "#000011"),
        "green":  ("#34d399", "#0a1a0a", "#001100"),
        "pink":   ("#f472b6", "#1a0a0f", "#110008"),
        "white":  ("#e5e7eb", "#1a1a1a", "#111111"),
        # 신규 7색
        "orange": ("#fb923c", "#1a0e00", "#110800"),
        "purple": ("#a78bfa", "#0f0a1a", "#080011"),
        "red":    ("#f87171", "#1a0808", "#110000"),
        "teal":   ("#2dd4bf", "#0a1a18", "#001110"),
        "indigo": ("#818cf8", "#0a0a1a", "#080011"),
        "amber":  ("#fbbf24", "#1a1400", "#111000"),
        "rose":   ("#fb7185", "#1a0a0e", "#110008"),
    }
    # 우클릭 글꼴 메뉴 기본 5종 (시스템 글꼴은 다이얼로그로 추가)
    _BASE_FONTS = ["Malgun Gothic", "NanumGothic"]

    def __init__(self, app, monitors_info):
        self.app       = app
        L = app.config.get("language", "ko")
        self._memos    = load_memos()
        self._cards    = {}    # mid → dict
        self._drag     = {}    # mid → 드래그 상태
        self._OVERLAY_ALPHA = 0.90   # 오버레이 반투명 목표값 (페이드인·드래그 복귀 공용)
        self._drag_origin = None     # 드래그 중 canvas 원점 캐시 (winfo 매프레임 조회 제거)
        self._ghosts = {}            # mid → 고스트 사각형 id (드래그 중 위젯 대신 이동)
        self._drag_bounds = None     # 드래그 시작 시 선택 바운딩 박스 캐시
        self._resize   = {}    # mid → 리사이즈 상태
        self._edit_mid = None  # 현재 편집 중인 mid
        self._last_edit_mid = None      # 직전 편집 메모(포커스 이탈 후 줄색 적용용)
        self._last_sel_lines = {}       # mid → 최근 본문 선택 줄(0-based)
        self._selected: set = set()
        self._undo_stack: list = []   # [(action, memos_snapshot), ...]
        self._redo_stack: list = []   # [(action, memos_snapshot), ...]

        # ── 주 모니터 정보 ────────────────────────────
        primary = next((m for m in monitors_info if m[4]), monitors_info[0])
        self.mx, self.my, self.mw, self.mh, _ = primary

        # ── 모드·분할 설정 (역산 재사용을 위해 저장) ──
        self._mode  = app.config.get("screensaver_mode", "media")
        self._ratio = app.config.get("split_ratio", 0.65)
        self._direc = app.config.get("split_direction", "h")

        # ── 메모 영역 좌표 계산 (실제 픽셀) ────────────
        if self._mode == "split":
            if self._direc == "h":
                self.memo_x = int(self.mw * self._ratio)
                self.memo_y = 0
                self.memo_w = max(1, self.mw - self.memo_x)
                self.memo_h = self.mh
            else:
                self.memo_x = 0
                self.memo_y = int(self.mh * self._ratio)
                self.memo_w = self.mw
                self.memo_h = max(1, self.mh - self.memo_y)
        else:
            self.memo_x, self.memo_y = 0, 0
            self.memo_w, self.memo_h = self.mw, self.mh

        # ── 전체화면 오버레이 창 ────────────────────────
        self.overlay = tk.Toplevel()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", 0.0)   # 투명하게 시작
        self.overlay.geometry(f"{self.mw}x{self.mh}+{self.mx}+{self.my}")
        self.overlay.configure(bg="#020715")

        # ── grab_set: 지연 재시도 패턴 (응답없음 방어) ─────
        # 직접 grab_set() 호출 시 블로킹 가능 → after(100)으로 지연 호출.
        # 3회 재시도 후 실패하면 grab 없이 진행 (overrideredirect+topmost로 보완).
        self.overlay.deiconify()
        self.overlay.lift()
        self.overlay.focus_force()
        self._grab_active = False
        # 기존 grab 선제 해제
        try:
            cur_grab = self.overlay.grab_current()
            if cur_grab:
                cur_grab.grab_release()
                LOG.info(f"[FSEditor] 기존 grab 선제 해제: {cur_grab}")
        except Exception:
            pass
        self.overlay.after(100, lambda: self._try_grab_set(retries=3))

        # ── DPI 실측 재확인 ──────────────────────────
        self.overlay.update_idletasks()
        actual_w = self.overlay.winfo_width()
        actual_h = self.overlay.winfo_height()
        if abs(actual_w - self.mw) > 2 or abs(actual_h - self.mh) > 2:
            LOG.warning(f"[DPI] 창 크기 불일치: 설정={self.mw}×{self.mh} "
                        f"실측={actual_w}×{actual_h} → 실측값으로 보정")
            self.mw, self.mh = actual_w, actual_h
            # memo_w/h 재계산
            if self._mode == "split":
                if self._direc == "h":
                    self.memo_x = int(self.mw * self._ratio)
                    self.memo_w = max(1, self.mw - self.memo_x)
                else:
                    self.memo_y = int(self.mh * self._ratio)
                    self.memo_h = max(1, self.mh - self.memo_y)
            else:
                self.memo_w, self.memo_h = self.mw, self.mh

        # ── 배경 캔버스 (영상 영역 표시) ──────────────
        bg_cv = tk.Canvas(self.overlay, bg="#020715", highlightthickness=0)
        bg_cv.place(x=0, y=0, width=self.mw, height=self.mh)

        if self._mode == "split":
            if self._direc == "h":
                bx1, by1, bx2, by2 = 0, 0, self.memo_x, self.mh
                lx1, ly1, lx2, ly2 = self.memo_x, 0, self.memo_x, self.mh
                tx, ty = self.memo_x // 2, self.mh // 2
            else:
                bx1, by1, bx2, by2 = 0, 0, self.mw, self.memo_y
                lx1, ly1, lx2, ly2 = 0, self.memo_y, self.mw, self.memo_y
                tx, ty = self.mw // 2, self.memo_y // 2
            bg_cv.create_rectangle(bx1, by1, bx2, by2,
                                   fill="#000000", outline="", stipple="gray50")
            bg_cv.create_text(tx, ty, text=t("lbl_video_area", L),
                              fill="#555555", font=("Malgun Gothic", 14),
                              justify="center")
            bg_cv.create_line(lx1, ly1, lx2, ly2,
                              fill="#5b8dee", width=3, dash=(10, 5))

        # ── 버튼 바 ────────────────────────────────────
        BTN_H = 60   # 상단 메뉴 16pt 수용 위해 44→60
        self._btn_h = BTN_H
        RIBBON_H = 46   # 서식 리본 바 (글꼴/크기/색/셀색)
        self._ribbon_h = RIBBON_H
        btn_bar = tk.Frame(self.overlay, bg="#16181d", height=BTN_H)
        btn_bar.place(x=self.memo_x, y=self.memo_y,
                      width=self.memo_w, height=BTN_H)

        # ── 상단 3버튼 규격 통일 ─────────────────────────
        # width(글자수)는 한글 폭과 안 맞아 짤림 → 사용 안 함.
        # bd=0·highlightthickness=0·동일 font·동일 padx/ipady 로 높이·여백 통일.
        _BTN_FONT = ("Malgun Gothic", 16, "bold")
        _BTN_PADX = 16    # 내부 좌우 여백(내용 맞춤 폭)
        _BTN_IPADY = 5    # 높이 통일
        # pady 명시: Button↔Menubutton 기본 내부 pady 차이로 인한 높이 불일치 해소
        _btn_kw = dict(font=_BTN_FONT, fg="white", relief="flat",
                       bd=0, highlightthickness=0, padx=_BTN_PADX, pady=6)

        # 즐겨찾기 양식 바로가기 — 주황
        self._fav_btn = tk.Button(btn_bar, bg="#f97316",
                                  command=self._run_favorite, **_btn_kw)
        self._fav_btn.pack(side="left", padx=(12, 4), pady=6, ipady=_BTN_IPADY)
        self._refresh_fav_btn()

        # 템플릿 — Button + 수동 팝업(Menubutton 높이차 제거, 세 버튼 동일 위젯)
        self._tmpl_btn = tk.Button(btn_bar, text=t("btn_template", L),
                                   bg="#10b981", command=self._show_tmpl_menu,
                                   **_btn_kw)
        self._tmpl_menu = tk.Menu(self._tmpl_btn, tearoff=0,
                                  bg="#1e1e2e", fg="#e5e7eb",
                                  activebackground="#5b8dee",
                                  font=("Malgun Gothic", 14))
        self._build_template_menu()
        self._tmpl_btn.pack(side="left", padx=(0, 4), pady=6, ipady=_BTN_IPADY)

        # 전체 재배열 버튼 — 그레이
        tk.Button(btn_bar, text=t("btn_rearrange", L), bg="#6b7280",
                  command=self._reset_all_positions, **_btn_kw
                  ).pack(side="left", padx=(0, 4), pady=6, ipady=_BTN_IPADY)
        tk.Button(btn_bar, text=t("btn_save_close", L),
                  bg="#5b8dee", fg="white",
                  font=("Malgun Gothic", 16, "bold"),
                  command=self._save_and_close,
                  relief="flat", padx=12
                  ).pack(side="right", pady=6, padx=8)
        tk.Button(btn_bar, text=t("btn_cancel", L),
                  bg="#374151", fg="#e5e7eb",
                  font=("Malgun Gothic", 16),
                  command=self._cancel,
                  relief="flat", padx=12
                  ).pack(side="right", pady=6, padx=4)
        tk.Label(btn_bar,
                 text=(f"🖥️ 실제 크기 편집  |  "
                       f"메모 영역 {self.memo_w}×{self.memo_h}px  |  "
                       f"더블클릭=편집  Ctrl+Enter=확인  ESC=취소"),
                 bg="#16181d", fg="#9ca3af",
                 font=("Malgun Gothic", 9)
                 ).pack(side="left", padx=10)

        # 모드 상태 표시 라벨
        self._mode_lbl = tk.Label(btn_bar, text=t("lbl_drag_mode", L),
                                   bg="#16181d", fg="#34d399",
                                   font=("Malgun Gothic", 9))
        self._mode_lbl.pack(side="left", padx=(0, 8))

        # 강제 종료 시에도 저장되도록 WM_DELETE_WINDOW 핸들러 등록
        self.overlay.protocol("WM_DELETE_WINDOW", self._save_and_close)

        # ── 편집 캔버스 (실제 픽셀 크기) ───────────────
        # 테마 1회 캐싱 (파일 I/O 최적화)
        theme_key = app.config.get("memo_bg_theme", "paper")
        self._current_theme = get_all_themes().get(theme_key, MEMO_BG_THEMES["paper"])
        self.canvas = tk.Canvas(
            self.overlay,
            bg="#020715",   # 편집 캔버스 배경 고정(사용자 지정)
            highlightthickness=2,
            highlightbackground="#5b8dee"
        )
        self.canvas.place(
            x=self.memo_x, y=self.memo_y + BTN_H + RIBBON_H,
            width=self.memo_w, height=self.memo_h - BTN_H - RIBBON_H
        )
        self.canvas_h = self.memo_h - BTN_H - RIBBON_H

        # ── 서식 리본 바 (btn_bar 아래, canvas 위) ──────
        self._build_ribbon(self.memo_x, self.memo_y + BTN_H,
                            self.memo_w, RIBBON_H)

        # 캔버스 실측 보정 (DPI 타이밍 오류 방지)
        # place() 직후 update_idletasks()로 실제 배치 확정 후 재측정
        self.canvas.update_idletasks()
        real_cw = self.canvas.winfo_width()
        real_ch = self.canvas.winfo_height()
        if real_cw > 10:
            self.memo_w   = real_cw
        if real_ch > 10:
            self.canvas_h = real_ch
        LOG.info(f"[FSEditor] 캔버스 실측: {self.memo_w}×{self.canvas_h}px")

        # 배경 렌더링 (이미지/패턴/그라데이션 — z-order 최하단)
        _render_canvas_bg(self.canvas, self.memo_w, self.canvas_h, self._current_theme)

        self.canvas.create_text(
            self.memo_w // 2, 24,
            text=t("lbl_drag_guide", L),
            fill="#444444", font=("Malgun Gothic", 10), tags="guide"
        )

        # ── ESC 계층 바인딩 ────────────────────────────
        self.overlay.bind("<Escape>", self._on_escape)
        self.canvas.bind("<Escape>",  self._on_escape)
        self.canvas.bind("<F4>",      lambda e: self._cancel())
        # Ctrl+Z / Ctrl+Y — canvas/overlay에 바인딩 (Text 위젯 내부와 분리)
        self.canvas.bind("<Control-z>", self._undo)
        self.canvas.bind("<Control-y>", self._redo)
        self.overlay.bind("<Control-z>", self._undo)
        self.overlay.bind("<Control-y>", self._redo)
        # Delete=선택 삭제 / Insert=즐겨찾기 양식 생성 (편집 중엔 핸들러가 무시)
        self.overlay.bind("<Delete>", self._on_delete_key)
        self.canvas.bind("<Button-1>", self._on_canvas_click)   # 배경 클릭=선택 해제
        self.canvas.bind("<Delete>",  self._on_delete_key)
        self.overlay.bind("<Insert>", self._on_insert_key)
        self.canvas.bind("<Insert>",  self._on_insert_key)
        # 빈 배경 클릭 → 선택/편집 해제
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.focus_set()

        # ── 페이드인 시작 (grab은 이미 __init__에서 선점 완료) ──
        self._fade_in()

        # ── 카드 배치 ──────────────────────────────────
        self._place_cards()

    def _fade_in(self, step: int = 0):
        """
        alpha 0 → 0.90 페이드인 (20프레임 × 16ms ≈ 330ms).
        grab_set은 __init__에서 이미 동기적으로 완료됨.
        페이드인 중 Alt-Tab/타창 클릭 → grab이 이미 걸려있어 차단.
        """
        TARGET, STEPS = self._OVERLAY_ALPHA, 20
        if step > STEPS:
            return
        try:
            self.overlay.attributes("-alpha", TARGET * step / STEPS)
            self.overlay.after(16, lambda: self._fade_in(step + 1))
        except Exception:
            pass

    # ══ 서식 리본 바 ═════════════════════════════════════

    def _build_ribbon(self, x, y, w, h):
        """서식 리본: 글꼴/제목·본문 크기/글자색/셀색. 선택 메모에 즉시 적용.
        우클릭 메뉴와 병행. 단일 선택 시만 활성."""
        L = self.app.config.get("language", "ko")
        self._rb_mid = None
        BG = "#23252b"; FG = "#e5e7eb"; FNT = ("Malgun Gothic", 11)
        bar = tk.Frame(self.overlay, bg=BG, height=h)
        bar.place(x=x, y=y, width=w, height=h)
        self._ribbon = bar

        def _lbl(txt):
            return tk.Label(bar, text=txt, bg=BG, fg="#9ca3af", font=FNT)

        def _sep():
            tk.Frame(bar, bg="#3a3d44", width=1).pack(side="left", fill="y",
                                                       padx=6, pady=8)

        # ── 1) 제목(선택) 표시 ─────
        self._rb_sel_lbl = tk.Label(bar, text=t("rb_sel_none", L), bg=BG,
                                    fg="#6b7280", font=("Malgun Gothic", 11, "bold"))
        self._rb_sel_lbl.pack(side="left", padx=(10, 4))
        _sep()

        # ── 2) 테마색 ─────
        self._rb_bg_lbl = _lbl(t("rb_theme_color", L))
        self._rb_bg_lbl.pack(side="left", padx=(0, 2))
        self._rb_bg_mb = tk.Menubutton(bar, text="\U0001f3a8", bg="#374151", fg=FG,
                                       font=FNT, relief="flat", padx=6)
        self._rb_bg_mb.pack(side="left", padx=(0, 6), pady=8)
        self._rb_build_bg_menu()
        _sep()

        # ── 3) 글꼴 ─────
        _lbl(t("rb_font", L)).pack(side="left", padx=(0, 2))
        self._rb_font_mb = tk.Menubutton(bar, text="\u2014", bg="#374151", fg=FG,
                                         font=FNT, relief="flat", padx=6, width=12)
        self._rb_font_mb.pack(side="left", padx=(0, 6), pady=8)
        self._rb_build_font_menu()
        _sep()

        # 색상 메뉴 공용 헬퍼 (제목색/본문색)
        def _swatch_fg(ck):
            hx = TEXT_COLORS.get(ck, "#e5e7eb")
            try:
                h = hx.lstrip("#")
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                if (0.299 * r + 0.587 * g + 0.114 * b) < 70:
                    return "#e5e7eb"
            except Exception:
                pass
            return hx
        _tcolors = [("white", t("clr_white", L)), ("black", t("clr_black", L)),
                    ("red", t("clr_red", L)), ("blue", t("clr_blue", L)),
                    ("yellow", t("clr_yellow", L))]

        # ── 4) 제목: 크기 + 색 ─────
        _lbl(t("rb_title_size", L)).pack(side="left")
        self._rb_tsize = tk.Entry(bar, width=4, justify="center", font=FNT,
                                  bg="#3f434b", fg="#ffffff", insertbackground=FG,
                                  relief="flat", highlightthickness=1,
                                  highlightbackground="#9ca3af",
                                  highlightcolor="#5b8dee")
        self._rb_tsize.pack(side="left", padx=(2, 6), ipady=2)
        self._rb_tsize.bind("<Return>",
                            lambda e: self._rb_apply_size("title_font_size",
                                                          self._rb_tsize))
        _lbl(t("rb_title_color", L)).pack(side="left", padx=(0, 2))
        self._rb_tcolor = tk.Menubutton(bar, text="\u25a0", bg="#374151", fg=FG,
                                        font=FNT, relief="flat", padx=6)
        tcm = tk.Menu(self._rb_tcolor, tearoff=0, bg="#1e1e2e", fg=FG,
                      activebackground="#5b8dee", font=FNT)
        for ck, cl in _tcolors:
            tcm.add_command(label=cl, foreground=_swatch_fg(ck),
                            command=lambda v=ck: self._rb_apply_color("title_text_color", v))
        tcm.add_separator()
        tcm.add_command(label=t("ctx_pick_color", L),
                        command=lambda: self._rb_pick_tcolor("title_text_color"))
        self._rb_tcolor["menu"] = tcm
        self._rb_tcolor.pack(side="left", padx=(0, 6), pady=8)
        _sep()

        # ── 5) 본문: 크기 + 색 + 줄글자 ─────
        _lbl(t("rb_body_size", L)).pack(side="left")
        self._rb_bsize = tk.Entry(bar, width=4, justify="center", font=FNT,
                                  bg="#3f434b", fg="#ffffff", insertbackground=FG,
                                  relief="flat", highlightthickness=1,
                                  highlightbackground="#9ca3af",
                                  highlightcolor="#5b8dee")
        self._rb_bsize.pack(side="left", padx=(2, 6), ipady=2)
        self._rb_bsize.bind("<Return>",
                            lambda e: self._rb_apply_size("body_font_size",
                                                          self._rb_bsize))
        _lbl(t("rb_body_color", L)).pack(side="left", padx=(0, 2))
        self._rb_bcolor = tk.Menubutton(bar, text="\u25a0", bg="#374151", fg=FG,
                                        font=FNT, relief="flat", padx=6)
        bcm = tk.Menu(self._rb_bcolor, tearoff=0, bg="#1e1e2e", fg=FG,
                      activebackground="#5b8dee", font=FNT)
        for ck, cl in _tcolors:
            bcm.add_command(label=cl, foreground=_swatch_fg(ck),
                            command=lambda v=ck: self._rb_apply_color("body_text_color", v))
        bcm.add_separator()
        bcm.add_command(label=t("ctx_pick_color", L),
                        command=lambda: self._rb_pick_tcolor("body_text_color"))
        self._rb_bcolor["menu"] = bcm
        self._rb_bcolor.pack(side="left", padx=(0, 6), pady=8)
        # 줄글자 / 줄글자지우기 (표 선택 시 셀글자로 동적 전환 — _sync_ribbon)
        self._rb_cellfg_btn = tk.Button(bar, text=t("rb_cell_fg", L), bg="#374151",
                                        fg=FG, font=FNT, relief="flat", padx=8,
                                        command=self._rb_apply_cell_fg)
        self._rb_cellfg_btn.pack(side="left", padx=(0, 4), pady=8)
        self._rb_cellfg_clr = tk.Button(bar, text=t("rb_cell_fg_clear", L), bg="#374151",
                                        fg=FG, font=FNT, relief="flat", padx=8,
                                        command=self._rb_clear_cell_fg)
        self._rb_cellfg_clr.pack(side="left", padx=(0, 8), pady=8)
        _sep()

        # ── 6) 정렬 (제목/본문 타깃 + 화살표) ─────
        _lbl(t("rb_align", L)).pack(side="left", padx=(0, 2))
        self._rb_align_target = "body"
        self._rb_tgt_title = tk.Button(
            bar, text=t("rb_title_size", L), font=FNT, relief="flat", padx=6,
            command=lambda: self._rb_set_align_target("title"))
        self._rb_tgt_title.pack(side="left", padx=(0, 2), pady=8)
        self._rb_tgt_body = tk.Button(
            bar, text=t("rb_body_size", L), font=FNT, relief="flat", padx=6,
            command=lambda: self._rb_set_align_target("body"))
        self._rb_tgt_body.pack(side="left", padx=(0, 6), pady=8)
        for _a, _sym in (("l", "\u2b05"), ("c", "\u2b1b"), ("r", "\u27a1")):
            tk.Button(bar, text=_sym, bg="#374151", fg=FG, font=FNT,
                      relief="flat", padx=6,
                      command=lambda a=_a: self._rb_align(a)
                      ).pack(side="left", padx=(0, 2), pady=8)
        self._rb_set_align_target("body")
        _sep()

        # ── 7) 이모지 ─────
        _lbl(t("rb_emoji", L)).pack(side="left", padx=(0, 2))
        tk.Button(bar, text="\U0001f600", bg="#374151", fg=FG,
                  font=("Segoe UI Emoji", 13), relief="flat", padx=6,
                  command=self._open_emoji_palette
                  ).pack(side="left", padx=(0, 2), pady=8)
        _sep()

        # ── 8) 표 (행/열 + 삽입·삭제 + 셀색/셀색지우기) ─────
        _lbl(t("rb_rows", L)).pack(side="left")
        self._rb_rows = tk.Entry(bar, width=3, justify="center", font=FNT,
                                 bg="#3f434b", fg="#ffffff", insertbackground=FG,
                                 relief="flat", highlightthickness=1,
                                 highlightbackground="#9ca3af",
                                 highlightcolor="#5b8dee")
        self._rb_rows.pack(side="left", padx=(2, 6), ipady=2)
        self._rb_rows.bind("<Return>", lambda e: self._rb_set_rows())
        _lbl(t("rb_cols", L)).pack(side="left")
        self._rb_cols = tk.Entry(bar, width=3, justify="center", font=FNT,
                                 bg="#3f434b", fg="#ffffff", insertbackground=FG,
                                 relief="flat", highlightthickness=1,
                                 highlightbackground="#9ca3af",
                                 highlightcolor="#5b8dee")
        self._rb_cols.pack(side="left", padx=(2, 6), ipady=2)
        self._rb_cols.bind("<Return>", lambda e: self._rb_set_cols())
        self._rb_rowmb = tk.Menubutton(bar, text=t("ctx_row", L), bg="#374151",
                                       fg=FG, font=FNT, relief="flat", padx=6)
        _rowmenu = tk.Menu(self._rb_rowmb, tearoff=0, bg="#1e1e2e", fg=FG,
                           activebackground="#5b8dee", font=FNT)
        _rowmenu.add_command(label=t("tir_above", L), command=lambda: self._rb_row_op("above"))
        _rowmenu.add_command(label=t("tir_below", L), command=lambda: self._rb_row_op("below"))
        _rowmenu.add_command(label=t("tdr_this", L), command=lambda: self._rb_row_op("del"))
        self._rb_rowmb["menu"] = _rowmenu
        self._rb_rowmb.pack(side="left", padx=(0, 4), pady=8)
        self._rb_colmb = tk.Menubutton(bar, text=t("ctx_col", L), bg="#374151",
                                       fg=FG, font=FNT, relief="flat", padx=6)
        _colmenu = tk.Menu(self._rb_colmb, tearoff=0, bg="#1e1e2e", fg=FG,
                           activebackground="#5b8dee", font=FNT)
        _colmenu.add_command(label=t("tic_left", L), command=lambda: self._rb_col_op("left"))
        _colmenu.add_command(label=t("tic_right", L), command=lambda: self._rb_col_op("right"))
        _colmenu.add_command(label=t("tdc_this", L), command=lambda: self._rb_col_op("del"))
        self._rb_colmb["menu"] = _colmenu
        self._rb_colmb.pack(side="left", padx=(0, 6), pady=8)
        self._rb_cell_btn = tk.Button(bar, text=t("rb_cell_bg", L), bg="#374151",
                                      fg=FG, font=FNT, relief="flat", padx=8,
                                      command=self._rb_apply_cell_bg)
        self._rb_cell_btn.pack(side="left", padx=(0, 4), pady=8)
        self._rb_cell_clr = tk.Button(bar, text=t("rb_cell_clear", L), bg="#374151",
                                      fg=FG, font=FNT, relief="flat", padx=8,
                                      command=self._rb_clear_cell_bg)
        self._rb_cell_clr.pack(side="left", padx=(0, 8), pady=8)
        _sep()

        # ── 9) 레이어(맨앞/맨뒤) + TXT 내보내기 ─────────
        _lbl(t("rb_layer", L)).pack(side="left", padx=(0, 2))
        tk.Button(bar, text=t("ctx_to_front", L), bg="#374151", fg=FG, font=FNT,
                  relief="flat", padx=6, command=self._rb_raise_front
                  ).pack(side="left", padx=(0, 2), pady=8)
        tk.Button(bar, text=t("ctx_to_back", L), bg="#374151", fg=FG, font=FNT,
                  relief="flat", padx=6, command=self._rb_send_back
                  ).pack(side="left", padx=(0, 6), pady=8)
        _sep()
        tk.Button(bar, text=t("rb_export_txt", L), bg="#374151", fg=FG, font=FNT,
                  relief="flat", padx=8, command=self._rb_export_txt
                  ).pack(side="left", padx=(0, 4), pady=8)
        tk.Button(bar, text=t("rb_import_txt", L), bg="#374151", fg=FG, font=FNT,
                  relief="flat", padx=8, command=self._rb_import_txt
                  ).pack(side="left", padx=(0, 8), pady=8)

        self._rb_widgets = [self._rb_font_mb, self._rb_tsize, self._rb_bsize,
                            self._rb_tcolor, self._rb_bcolor, self._rb_bg_mb]
        self._sync_ribbon()

    def _rb_build_font_menu(self):
        """리본 글꼴 메뉴 (저장된 시스템 글꼴 반영 위해 매번 재구성)."""
        FG = "#e5e7eb"; FNT = ("Malgun Gothic", 11)
        L = self.app.config.get("language", "ko")
        m = tk.Menu(self._rb_font_mb, tearoff=0, bg="#1e1e2e", fg=FG,
                    activebackground="#5b8dee", font=FNT)
        fonts = list(self._BASE_FONTS) + \
            list(self.app.config.get("custom_memo_fonts", []) or [])
        for fn in fonts:
            m.add_command(label=fn, command=lambda v=fn: self._rb_apply_font(v))
        m.add_separator()
        m.add_command(label=t("ctx_sys_font", L), command=self._rb_pick_font)
        self._rb_font_mb["menu"] = m

    def _rb_build_bg_menu(self):
        """리본 배경색 메뉴 (저장된 커스텀색 반영 위해 매번 재구성)."""
        FG = "#e5e7eb"; FNT = ("Malgun Gothic", 11)
        L = self.app.config.get("language", "ko")
        m = tk.Menu(self._rb_bg_mb, tearoff=0, bg="#1e1e2e", fg=FG,
                    activebackground="#5b8dee", font=FNT)
        # 기본 테마색(젬스톤) 프리셋 6종
        for ck, tk_ in (("purple","thm_purple"),("teal","thm_cyan"),
                        ("blue","thm_blue"),("amber","thm_gold"),
                        ("pink","thm_pink"),("white","thm_white")):
            m.add_command(label=t(tk_, L),
                          command=lambda v=ck: self._rb_apply_bg(v))
        m.add_separator()
        m.add_command(label=t("ctx_pick_color", L), command=self._rb_pick_color)
        customs = self.app.config.get("custom_memo_colors", []) or []
        if customs:
            m.add_separator()
            for hx in customs:
                m.add_command(label=f"🎨 {hx}", foreground=hx,
                              command=lambda v=hx: self._rb_apply_bg(v))
        self._rb_bg_mb["menu"] = m

    def _rb_target(self):
        """리본 적용 대상 mid (단일 선택일 때만)."""
        if len(self._selected) == 1:
            return next(iter(self._selected))
        return None

    def _sync_ribbon(self):
        """선택 변경 시 리본 상태·값 동기화."""
        if not hasattr(self, "_ribbon"):
            return
        L = self.app.config.get("language", "ko")
        mid = self._rb_target()
        self._rb_mid = mid
        memo = next((m for m in self._memos if m["id"] == mid), None) if mid else None

        def _set(w, enabled):
            try: w.config(state="normal" if enabled else "disabled")
            except Exception: pass

        if not memo:
            self._rb_sel_lbl.config(text=t("rb_sel_none", L), fg="#6b7280")
            for w in self._rb_widgets:
                _set(w, False)
            _set(self._rb_cell_btn, False)
            _set(self._rb_cell_clr, False)
            _set(self._rb_cellfg_btn, False)
            _set(self._rb_cellfg_clr, False)
            _set(self._rb_rows, False)
            _set(self._rb_cols, False)
            _set(self._rb_rowmb, False)
            _set(self._rb_colmb, False)
            return

        title = (memo.get("title") or "").strip() or t("lbl_untitled", L)
        is_table = memo.get("kind") == "table"
        self._rb_sel_lbl.config(
            text=(f"▦ 표 ({title[:14]})" if is_table else "📝 " + title[:16]),
            fg="#e5e7eb")
        self._rb_font_mb.config(text=memo.get("font_family", "Malgun Gothic"))
        # 저장된 시스템 글꼴·커스텀 배경색 반영 위해 메뉴 재구성
        self._rb_build_font_menu()
        self._rb_build_bg_menu()
        ck = memo.get("color_key", "yellow")
        self._rb_bg_mb.config(fg=(ck if isinstance(ck, str) and ck.startswith("#")
                                  else "#e5e7eb"))
        self._rb_bg_lbl.config(text=t("rb_theme_color", L))
        self._rb_tsize.delete(0, "end")
        self._rb_tsize.insert(0, str(memo.get("title_font_size", 11)))
        self._rb_bsize.delete(0, "end")
        self._rb_bsize.insert(0, str(memo.get("body_font_size", 10)))
        for w in self._rb_widgets:
            _set(w, True)
        # 표가 아니면 제목크기/제목색은 의미있으나 유지, 셀색·행/열은 표 전용
        _set(self._rb_cell_btn, is_table)
        _set(self._rb_cell_clr, is_table)
        # 🅰 글자색: 표=셀 / 일반 메모=줄 색 → 항상 활성 + 라벨 동적 전환
        _set(self._rb_cellfg_btn, True)
        _set(self._rb_cellfg_clr, True)
        self._rb_cellfg_btn.config(
            text=t("rb_cell_fg" if is_table else "rb_line_fg", L))
        self._rb_cellfg_clr.config(
            text=t("rb_cell_fg_clear" if is_table else "rb_line_fg_clear", L))
        # 행/열 입력: 표일 때 현재 개수 표시 + 활성
        for ent, n in ((self._rb_rows, (memo.get("table") or {}).get("rows", 0)),
                       (self._rb_cols, (memo.get("table") or {}).get("cols", 0))):
            _set(ent, True)   # 값 기입 위해 먼저 normal
            ent.delete(0, "end")
            if is_table:
                ent.insert(0, str(n))
            _set(ent, is_table)
        _set(self._rb_rowmb, is_table)
        _set(self._rb_colmb, is_table)

    def _rb_apply_font(self, fn):
        if not self._rb_mid:
            return
        self._update_style(self._rb_mid, "font_family", fn)

    def _rb_apply_size(self, key, entry):
        if not self._rb_mid:
            return
        try:
            v = max(6, min(200, int(entry.get())))
        except (ValueError, TypeError):
            return
        self._update_style(self._rb_mid, key, v)

    def _rb_apply_color(self, key, ck):
        if not self._rb_mid:
            return
        self._update_style(self._rb_mid, key, ck)

    def _rb_apply_bg(self, hx):
        if not self._rb_mid:
            return
        self._update_style(self._rb_mid, "color_key", hx)

    def _rb_pick_color(self):
        """메모 배경색 직접 선택 (colorchooser) — 기존 핸들러 재사용."""
        if self._rb_mid:
            self._pick_custom_color(self._rb_mid)

    def _rb_pick_font(self):
        """시스템 글꼴 추가 다이얼로그 — 기존 핸들러 재사용."""
        if self._rb_mid:
            self._pick_system_font(self._rb_mid)

    def _rb_pick_tcolor(self, key):
        if self._rb_mid:
            self._pick_text_color(self._rb_mid, key)

    def _toggle_checkbox(self, mid, event):
        """본문 체크박스 글리프(☐/☑) 클릭 토글. 편집모드·표에서는 무시."""
        if self._edit_mid == mid:
            return
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo or memo.get("kind") == "table":
            return
        card = self._cards.get(mid)
        txt = card.get("txt_body") if card else None
        if txt is None:
            return
        try:
            idx = txt.index(f"@{event.x},{event.y}")
        except Exception:
            return
        line = int(idx.split(".")[0]); col = int(idx.split(".")[1])
        line_text = txt.get(f"{line}.0", f"{line}.end")
        gpos = len(line_text) - len(line_text.lstrip())   # 첫 글자(글리프) 위치
        if gpos >= len(line_text):
            return
        glyph = line_text[gpos]
        if glyph not in ("☐", "☑"):
            return
        if col > gpos + 1:          # 글리프 근처 클릭만 토글(본문 클릭 제외)
            return
        new_glyph = "☑" if glyph == "☐" else "☐"
        lines = memo.get("body", "").split("\n")
        if 0 <= line - 1 < len(lines):
            ln = lines[line - 1]
            gp = len(ln) - len(ln.lstrip())
            if gp < len(ln) and ln[gp] in ("☐", "☑"):
                lines[line - 1] = ln[:gp] + new_glyph + ln[gp + 1:]
                self._push_undo("체크박스")
                memo["body"] = "\n".join(lines)
                memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                txt.config(state="normal")
                txt.delete("1.0", "end")
                txt.insert("1.0", memo["body"])
                txt.config(state="disabled")
        return "break"

    def _pick_text_color(self, mid, key):
        """글자색 직접 선택(colorchooser) → hex 적용. 렌더는 resolve_text_color가 해석."""
        L = self.app.config.get("language", "ko")
        try:
            _rgb, hx = colorchooser.askcolor(parent=self.overlay,
                                             title=t("ctx_pick_color", L))
        except Exception:
            hx = None
        if not hx:
            return
        self._update_style(mid, key, hx.lower())

    def _rb_apply_cell_bg(self):
        if self._rb_mid:
            self._apply_cell_bg(self._rb_mid)

    def _rb_clear_cell_bg(self):
        if self._rb_mid:
            self._clear_cell_bg(self._rb_mid)

    _JUSTIFY = {"l": "left", "c": "center", "r": "right"}

    def _rb_set_align_target(self, tgt):
        """정렬 타깃 전환(title/body) + 토글 버튼 하이라이트."""
        self._rb_align_target = tgt
        if not hasattr(self, "_rb_tgt_title"):
            return
        ON, OFF = "#10b981", "#374151"
        try:
            self._rb_tgt_title.config(bg=ON if tgt == "title" else OFF, fg="white")
            self._rb_tgt_body.config(bg=ON if tgt == "body" else OFF, fg="white")
        except Exception:
            pass

    # Windows 흑백 폴백(Segoe UI Symbol) 호환 위주로 큐레이션.
    # 변형 선택자(FE0F)·신형(Unicode 9+) 이모지는 글리프 누락으로 제외.
    _EMOJI_SET = [
        "😀","😁","😂","😃","😄","😅","😆","😉","😊","😋","😌","😍","😎","😏","😐","😑",
        "😒","😓","😔","😖","😘","😚","😜","😝","😞","😠","😡","😢","😣","😤","😥","😨",
        "😩","😪","😫","😭","😰","😱","😲","😳","😵","😶","😷","👍","👎","👌","👏","🙏",
        "💪","🙌","👀","🔥","⭐","💯","❗","❓","💡","📌","📝","📅","🎉","🎂","🎁","💜",
        "💛","💚","💙","☀","☁","❄","🌙","🍀","🌸","🌹","🐱","🐶","🍎","☕","🚗","🏠",
        "💻","📱","🔔","📖","🎵","⚽","🏆","🎯","💰","🕐","✅","❌",
    ]

    def _open_emoji_palette(self):
        """내장 이모지 팔레트 — 현재 포커스 Entry/Text에 삽입. 흑백 표시."""
        L = self.app.config.get("language", "ko")
        # 마지막 포커스 편집위젯 우선(😀 버튼 클릭으로 포커스 이탈해도 유지)
        tgt = getattr(self, "_last_text_focus", None)
        try:
            if not (isinstance(tgt, (tk.Entry, tk.Text)) and tgt.winfo_exists()):
                tgt = self.overlay.focus_get()
        except Exception:
            tgt = None
        try:
            alive = isinstance(tgt, (tk.Entry, tk.Text)) and tgt.winfo_exists()
        except Exception:
            alive = False
        if not alive:
            self._set_mode_label(t("hint_emoji_focus", L), "#fbbf24")
            return
        self._emoji_target = tgt
        old = getattr(self, "_emoji_win", None)
        if old is not None:
            try: old.destroy()
            except Exception: pass
        # 모달 grab 해제(팔레트 클릭 가능) → 닫힐 때 복원
        try:
            self.overlay.grab_release(); self._grab_active = False
        except Exception:
            pass
        win = tk.Toplevel(self.overlay)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#1e1e2e", highlightbackground="#5b8dee",
                      highlightthickness=2)
        self._emoji_win = win
        def _restore_grab(e=None):
            try:
                if not self._grab_active:
                    self.overlay.grab_set(); self._grab_active = True
            except Exception:
                pass
        win.bind("<Destroy>", _restore_grab)
        COLS = 8
        for i, ch in enumerate(self._EMOJI_SET):
            b = tk.Button(win, text=ch, font=("Segoe UI Emoji", 15),
                          bg="#2a2a3a", fg="#e5e7eb", relief="flat",
                          width=2, command=lambda c=ch: self._insert_emoji(c))
            b.grid(row=i // COLS, column=i % COLS, padx=1, pady=1)
        tk.Button(win, text=t("btn_cancel2", L), bg="#374151", fg="#e5e7eb",
                  relief="flat", font=("Malgun Gothic", 10),
                  command=win.destroy).grid(
                      row=len(self._EMOJI_SET) // COLS + 1, column=0,
                      columnspan=COLS, sticky="ew", padx=1, pady=(2, 1))
        # 버튼 아래 배치
        win.update_idletasks()
        px = self.overlay.winfo_rootx() + 40
        py = self.overlay.winfo_rooty() + self._btn_h + self._ribbon_h
        win.geometry(f"+{px}+{py}")

    def _insert_emoji(self, ch):
        """포커스 위젯에 이모지 삽입(비-BMP 실패 방어)."""
        w = getattr(self, "_emoji_target", None)
        if w is None:
            return
        try:
            if isinstance(w, tk.Text):
                if str(w.cget("state")) != "normal":
                    return
                w.insert("insert", ch)
            elif isinstance(w, tk.Entry):
                w.insert("insert", ch)
            w.focus_set()
        except Exception as e:
            LOG.error(f"[FSEditor] 이모지 삽입 실패(Tk 제약 가능): {e}")
            self._set_mode_label(t("hint_emoji_fail", self.app.config.get("language","ko")),
                                 "#f87171")

    def _rb_align(self, a):
        """정렬: 타깃(제목/본문) 기준. 본문 타깃에서 표는 선택 셀에 적용."""
        mid = self._rb_mid or self._last_edit_mid
        if not mid:
            return
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        # 제목 타깃: 표·메모 공통 title_align
        if getattr(self, "_rb_align_target", "body") == "title":
            self._update_style(mid, "title_align", a)
            return
        if memo.get("kind") == "table":
            sel = self._tbl_sel.get(mid, set()) if hasattr(self, "_tbl_sel") else set()
            if not sel:
                self._set_mode_label(t("hint_cell_sel", self.app.config.get("language","ko")),
                                     "#fbbf24")
                return
            self._push_undo("셀 정렬")
            ca = (memo.setdefault("table", {})).setdefault("cell_align", {})
            for (r, c) in sel:
                ca[f"{r},{c}"] = a
                ent = self._tbl_cells.get(mid, {}).get((r, c))
                if ent is not None:
                    try: ent.config(justify=self._JUSTIFY[a])
                    except Exception: pass
            memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            return
        # 일반 메모: 본문만 정렬(제목은 건드리지 않음)
        # 선택 줄은 '해당 메모를 편집 중이고 실제 선택이 있을 때'만 사용
        lines = self._last_sel_lines.get(mid) if self._edit_mid == mid else None
        if lines:
            la = memo.setdefault("line_align", {})
            for idx in lines:
                la[str(idx)] = a
        else:
            memo["body_align"] = a
            memo["line_align"] = {}   # 전체 적용 → 개별 줄 오버라이드 제거
        # 카드 재생성(+undo)은 _update_style이 처리 (body_align만 반영, 제목 불변)
        self._update_style(mid, "body_align", memo.get("body_align", "l"))

    def _ctx_body_align(self, mid, a):
        """우클릭 본문 정렬 — 전체 적용(줄 오버라이드 제거)."""
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        memo["line_align"] = {}
        self._update_style(mid, "body_align", a)

    def _ctx_cell_align(self, mid, a):
        """우클릭 셀 정렬 — 선택 셀 대상(없으면 힌트)."""
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo or memo.get("kind") != "table":
            return
        sel = self._tbl_sel.get(mid, set()) if hasattr(self, "_tbl_sel") else set()
        if not sel:
            self._set_mode_label(t("hint_cell_sel", self.app.config.get("language", "ko")),
                                 "#fbbf24")
            return
        self._push_undo("셀 정렬")
        ca = (memo.setdefault("table", {})).setdefault("cell_align", {})
        for (r, c) in sel:
            ca[f"{r},{c}"] = a
            ent = self._tbl_cells.get(mid, {}).get((r, c))
            if ent is not None:
                try: ent.config(justify=self._JUSTIFY[a])
                except Exception: pass
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _rb_row_op(self, op):
        """리본 행 삽입/삭제 — 선택 셀 행 기준."""
        mid = self._rb_mid or self._last_edit_mid
        if not mid:
            return
        rc = self._rb_sel_cell(mid)
        if rc is None:
            self._set_mode_label(t("hint_cell_sel", self.app.config.get("language","ko")),
                                 "#fbbf24")
            return
        r, _c = rc
        if op == "above":
            self._table_insert_row(mid, r)
        elif op == "below":
            self._table_insert_row(mid, r + 1)
        elif op == "del":
            self._table_delete_row(mid, r)

    def _rb_col_op(self, op):
        """리본 열 삽입/삭제 — 선택 셀 열 기준."""
        mid = self._rb_mid or self._last_edit_mid
        if not mid:
            return
        rc = self._rb_sel_cell(mid)
        if rc is None:
            self._set_mode_label(t("hint_cell_sel", self.app.config.get("language","ko")),
                                 "#fbbf24")
            return
        _r, c = rc
        if op == "left":
            self._table_insert_col(mid, c)
        elif op == "right":
            self._table_insert_col(mid, c + 1)
        elif op == "del":
            self._table_delete_col(mid, c)

    def _rb_sel_cell(self, mid):
        """선택 셀 중 좌상단(min) 좌표. 없으면 None."""
        sel = self._tbl_sel.get(mid, set()) if hasattr(self, "_tbl_sel") else set()
        if not sel:
            return None
        return min(sel)

    def _rb_apply_cell_fg(self):
        """동적: 표=셀 글자색 / 일반 메모=드래그 선택 줄 글자색."""
        mid = self._rb_mid or self._last_edit_mid
        if not mid:
            return
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if memo and memo.get("kind") == "table":
            self._apply_cell_fg(mid)
        else:
            self._apply_line_color(mid)

    def _rb_clear_cell_fg(self):
        mid = self._rb_mid or self._last_edit_mid
        if not mid:
            return
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if memo and memo.get("kind") == "table":
            self._clear_cell_fg(mid)
        else:
            self._clear_line_color(mid)

    def _capture_body_sel(self, mid):
        """본문 드래그 선택 줄(0-based)을 저장. 포커스 이탈(리본 클릭) 전 호출됨."""
        if self._edit_mid != mid:
            return
        card = self._cards.get(mid)
        txt = card.get("txt_body") if card else None
        if txt is None:
            return
        try:
            f = int(txt.index("sel.first").split(".")[0])
            l = int(txt.index("sel.last").split(".")[0])
            self._last_sel_lines[mid] = list(range(f - 1, l))   # 0-based
        except Exception:
            self._last_sel_lines[mid] = []   # 선택 없음 → 전체 취급

    def _apply_line_color(self, mid):
        """선택 줄 글자색 지정(colorchooser). 캡처된 선택 줄 사용(포커스 이탈 후에도)."""
        L = self.app.config.get("language", "ko")
        lines = self._last_sel_lines.get(mid) if self._edit_mid == mid else None
        if not lines:
            self._set_mode_label(t("hint_line_sel", L), "#fbbf24")
            return
        try:
            _rgb, hx = colorchooser.askcolor(parent=self.overlay,
                                             title=t("ctx_pick_color", L))
        except Exception:
            hx = None
        if not hx:
            return
        hx = hx.lower()
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        self._push_undo("줄 글자색")
        lc = memo.setdefault("line_colors", {})
        card = self._cards.get(mid)
        txt = card.get("txt_body") if card else None
        for idx in lines:
            lc[str(idx)] = hx
            if txt is not None:
                li = idx + 1; tag = f"lc{li}"
                try:
                    txt.tag_add(tag, f"{li}.0", f"{li}.end")
                    txt.tag_config(tag, foreground=hx)
                except Exception:
                    pass
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _clear_line_color(self, mid):
        """선택 줄 글자색 해제(선택 없으면 전체 해제)."""
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        lc = memo.get("line_colors") or {}
        if not lc:
            return
        lines = self._last_sel_lines.get(mid) if self._edit_mid == mid else None
        self._push_undo("줄 글자색 지우기")
        card = self._cards.get(mid)
        txt = card.get("txt_body") if card else None
        targets = [str(i) for i in lines] if lines else list(lc.keys())
        for sidx in targets:
            lc.pop(sidx, None)
            if txt is not None:
                try: txt.tag_delete(f"lc{int(sidx)+1}")
                except Exception: pass
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _rb_set_rows(self):
        """행 목표개수 입력 → 기존 add/del 반복으로 증감 (1~MAX)."""
        if not self._rb_mid:
            return
        memo, tbl = self._table_of(self._rb_mid)
        if not tbl:
            return
        try:
            tgt = max(1, min(TABLE_MAX_ROWS, int(self._rb_rows.get())))
        except (ValueError, TypeError):
            return
        while tbl["rows"] < tgt:
            self._table_add_row(self._rb_mid)
        while tbl["rows"] > tgt:
            self._table_del_row(self._rb_mid)
        self._sync_ribbon()

    def _rb_set_cols(self):
        """열 목표개수 입력 → 기존 add/del 반복으로 증감 (1~MAX)."""
        if not self._rb_mid:
            return
        memo, tbl = self._table_of(self._rb_mid)
        if not tbl:
            return
        try:
            tgt = max(1, min(TABLE_MAX_COLS, int(self._rb_cols.get())))
        except (ValueError, TypeError):
            return
        while tbl["cols"] < tgt:
            self._table_add_col(self._rb_mid)
        while tbl["cols"] > tgt:
            self._table_del_col(self._rb_mid)
        self._sync_ribbon()

    # ══ 카드 생성 ═══════════════════════════════════════

    def _place_cards(self):
        """
        FSEditor는 모든 메모를 표시 (Freemium 필터 미적용).
        이유: 실제 크기 편집기에서 숨겨진 메모도 위치 확인 필요.
        Freemium 제한은 _save_and_close 시 MemoBoardViewer.render()에서 적용.
        렌더링 가드: 개별 메모 오류 시 루프 중단 방지 (try/except + continue).
        """
        # ⚠️ _get_visible_memos 대신 self._memos 전체 사용
        # FSEditor는 편집 전용 — Freemium 표시 제한 없음
        visible_sorted = sorted(
            self._memos,
            key=lambda m: (not m.get("pinned", False), m.get("z_order", 0))
        )
        for memo in visible_sorted:
            mid = memo["id"]
            try:
                if "rel_x" in memo:
                    x = int(memo["rel_x"] * self.memo_w)
                    y = int(memo["rel_y"] * self.canvas_h)
                    w = int(memo["rel_w"] * self.memo_w)
                    h = int(memo["rel_h"] * self.canvas_h)
                else:
                    x, y = memo.get("x", 60), memo.get("y", 60)
                    w, h = memo.get("width", 220), memo.get("height", 160)
                w, h = max(self.MIN_W, w), max(self.MIN_H, h)

                LOG.debug(f"[FSEditor] _place_cards: mid={mid[:8]} x={x} y={y} w={w} h={h} memo_w={self.memo_w} canvas_h={self.canvas_h}")
                self._cards[mid] = {"w": w, "h": h}
                self._make_card(memo, mid, x, y, w, h)

                if memo.get("pinned"):
                    try:
                        self.canvas.tag_raise(self._cards[mid]["item_id"])
                    except Exception:
                        pass
            except Exception as e:
                # 개별 메모 렌더 실패 — 나머지 메모는 계속 진행
                import traceback as _tb
                LOG.error(f"[FSEditor] 메모 {mid} 렌더링 실패: {e}\n{_tb.format_exc()}")
                self._cards.pop(mid, None)
                continue

    def _make_card(self, memo, mid, x, y, w, h):
        """카드 위젯 생성 — 제목/본문/리사이즈 핸들 포함."""
        L = self.app.config.get("language", "ko")
        color_key = memo.get("color_key", "yellow")
        _is_custom = isinstance(color_key, str) and color_key.startswith("#")
        # 개별 opacity: 기존 OPACITY_PRESETS 방식 복원
        opacity   = memo.get("opacity", 1.0)
        op_key    = min(OPACITY_PRESETS.keys(), key=lambda k: abs(k - opacity))
        blended   = OPACITY_PRESETS.get(op_key, {})
        if _is_custom:
            # 커스텀 색: 실제 색으로 렌더(WYSIWYG) — 배경=원색, 헤더=어둡게
            bg  = _blend_color(color_key, _CANVAS_BG, op_key)
            hdr = _blend_color(_darken(color_key), _CANVAS_BG, op_key)
        else:
            hdr, bg, _ = (blended.get(color_key) + ("",) if color_key in blended
                          else self.COLORS.get(color_key, self.COLORS["yellow"]))
        # global_opacity: 전체 투명도 추가 적용 (0.0이면 변화 없음)
        global_opacity = self.app.config.get("memo_opacity", 0.0)
        if global_opacity > 0.01:
            theme_color = getattr(self, '_current_theme', {}).get("color", _CANVAS_BG)
            bg  = _blend_color(bg,  theme_color, 1.0 - global_opacity)
            hdr = _blend_color(hdr, theme_color, 1.0 - global_opacity)
        family = memo.get("font_family", "Malgun Gothic")
        tfs    = memo.get("title_font_size", 11)
        bfs    = memo.get("body_font_size", 10)
        is_image = (memo.get("kind") == "image")

        outer = tk.Frame(self.canvas, bg=bg, width=w, height=h,
                         relief="flat", bd=0)
        outer.pack_propagate(False)

        # ── 헤더 ── (이미지=폴라로이드: 제목바 하단)
        header = tk.Frame(outer, bg=hdr)
        header.pack(fill="x", side="bottom" if is_image else "top")

        title_var = tk.StringVar(value=memo.get("title", "")[:100])
        # 커스텀 색은 헤더·배경 명암 기반 자동 글자색(명시 지정 우선)
        if _is_custom:
            _def_title_fg = _memo_text_color(_darken(color_key))
            _def_body_fg  = _memo_text_color(color_key)
        else:
            _def_title_fg, _def_body_fg = "#1a1a1a", "#dddddd"
        title_fg = resolve_text_color(memo.get("title_text_color"), _def_title_fg)
        body_fg  = resolve_text_color(memo.get("body_text_color"),  _def_body_fg)
        _ta = memo.get("title_align", "l")
        _tanchor = {"l": "nw", "c": "n", "r": "ne"}.get(_ta, "nw")
        lbl_title = tk.Label(header,
                              textvariable=title_var,
                              bg=hdr, fg=title_fg,
                              font=_safe_font(family, tfs, "bold"),
                              anchor=_tanchor,
                              justify={"l": "left", "c": "center", "r": "right"}.get(_ta, "left"))
        lbl_title.pack(side="left", padx=5, pady=4, fill="x", expand=True)

        # ── 달력 메모: 이전/다음 달 네비 버튼(헤더) ──
        if memo.get("calendar"):
            _afs = max(14, tfs)   # 화살표를 제목 글자 크기에 맞춰 확대
            nxt = tk.Label(header, text="▶", bg=hdr, fg=title_fg, cursor="hand2",
                           font=("Arial", _afs, "bold"))
            nxt._fs_tag = "edit_text"   # 드래그/컨텍스트 제외
            nxt.pack(side="right", padx=(4, 8))
            nxt.bind("<Button-1>", lambda e, m=mid: self._calendar_shift(m, +1))
            prv = tk.Label(header, text="◀", bg=hdr, fg=title_fg, cursor="hand2",
                           font=("Arial", _afs, "bold"))
            prv._fs_tag = "edit_text"
            prv.pack(side="right", padx=(4, 0))
            prv.bind("<Button-1>", lambda e, m=mid: self._calendar_shift(m, -1))

        # ── 본문 (Text — 기본 DISABLED) ───────────────
        txt_body = tk.Text(outer,
                            bg=bg, fg=body_fg,
                            font=_safe_font(family, bfs),
                            relief="flat", bd=0,
                            state="disabled",
                            cursor="arrow",
                            wrap="word", undo=True,
                            padx=6, pady=4,
                            highlightthickness=0)
        txt_body._fs_tag = "edit_text"
        txt_body.config(state="normal")
        txt_body.insert("1.0", memo.get("body", ""))
        # 줄 단위 글자색(line_colors) 태그 적용
        for sidx, hx in (memo.get("line_colors") or {}).items():
            try:
                li = int(sidx) + 1
                tag = f"lc{li}"
                txt_body.tag_add(tag, f"{li}.0", f"{li}.end")
                txt_body.tag_config(tag, foreground=hx)
            except Exception:
                pass
        # 본문 정렬: 전체(body_align) + 줄별(line_align) 태그
        _bj = {"l": "left", "c": "center", "r": "right"}
        _ba = memo.get("body_align", "l")
        try:
            txt_body.tag_add("balign", "1.0", "end")
            txt_body.tag_config("balign", justify=_bj.get(_ba, "left"))
        except Exception:
            pass
        for sidx, av in (memo.get("line_align") or {}).items():
            try:
                li = int(sidx) + 1
                tag = f"la{li}"
                txt_body.tag_add(tag, f"{li}.0", f"{li}.end")
                txt_body.tag_config(tag, justify=_bj.get(av, "left"))
            except Exception:
                pass
        txt_body.config(state="disabled")

        # 표 메모: 셀 그리드 빌드(텍스트 본문 대체)
        is_table = (memo.get("kind") == "table")
        table_frame = self._build_table_grid(outer, memo, mid, bg) if is_table else None
        # 이미지 메모: 사진 라벨(폴라로이드 상단)
        img_label = self._build_image_label(outer, memo, w, h, tfs) if is_image else None

        # collapsed 상태 처리: 헤더만 표시
        if memo.get("collapsed"):
            # pack하지 않으면 outer가 헤더 높이만큼만 차지
            outer.config(height=max(self.MIN_H, header.winfo_reqheight() + 4))
        elif is_table:
            table_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        elif is_image:
            img_label.pack(fill="both", expand=True, padx=6, pady=(6, 2))
            img_label.bind("<Double-Button-1>",
                           lambda e, m=mid: self._replace_image(m))
        else:
            txt_body.pack(fill="both", expand=True)

        # ── 리사이즈 핸들 (우하단) ────────────────────
        handle = tk.Label(outer, text="◢", bg="#444444", fg="#aaaaaa",
                          cursor="size_nw_se",
                          font=("Arial", 7), padx=0, pady=0)
        handle._fs_tag = "resize_handle"   # 드래그 재귀 제외 태그
        handle.place(relx=1.0, rely=1.0, anchor="se",
                     width=self.HANDLE_SZ, height=self.HANDLE_SZ)

        # 리사이즈 바인딩 (드래그와 완전 분리)
        handle.bind("<ButtonPress-1>",
                    lambda e, m=mid: self._resize_start(e, m))
        handle.bind("<B1-Motion>",
                    lambda e, m=mid: self._resize_move(e, m))
        handle.bind("<ButtonRelease-1>",
                    lambda e, m=mid: self._resize_end(e, m))

        # 접힘 상태: 리사이즈 핸들 숨김 → 크기 변경 불가(펼침 착시 방지). 이동은 그대로 가능.
        if memo.get("collapsed"):
            handle.place_forget()

        # ── Canvas 배치: shadow → border → card 순서 ───────
        # 리뷰 확인: drag_start에서 3가지 함께 raise 필수
        shadow_id = self.canvas.create_rectangle(
            x+3, y+3, x+w+3, y+h+3,
            fill="#000000", outline="",
            stipple="gray25",          # PIL 불필요 — 네이티브 stipple
            tags=f"shadow_{mid}"
        )
        border_id = self.canvas.create_rectangle(
            x-1, y-1, x+w+1, y+h+1,
            outline=hdr, width=1,
            tags=f"border_{mid}"
        )
        item_id = self.canvas.create_window(
            x, y, window=outer, anchor="nw", tags=f"card_{mid}"
        )
        self._cards[mid].update({
            "item_id":   item_id,
            "shadow_id": shadow_id,
            "border_id": border_id,
            "outer":     outer,
            "header":    header,
            "lbl_title": lbl_title,
            "title_var": title_var,
            "txt_body":  txt_body,
            "handle":    handle,
            "tfs":       tfs,
            "hdr_bg":    hdr,
        })

        # ── 드래그 바인딩 (핸들·Text 제외, 재귀) ───────
        self._bind_drag_recursive(
            outer, mid,
            exclude_tags={"resize_handle", "edit_text", "table_cell"}
        )

        # ── 우클릭 → 컨텍스트 메뉴 (핸들·표셀 제외, 재귀) ───
        # table_cell 제외: 셀 자체 우클릭(_cell_menu) 바인딩이 덮이지 않도록
        self._bind_context_recursive(
            outer, mid,
            exclude_tags={"resize_handle", "table_cell"}
        )

        # ── 더블클릭 → 편집 모드 ───────────────────────
        header.bind("<Double-Button-1>",
                    lambda e, m=mid: self._edit_title_popup(m))
        lbl_title.bind("<Double-Button-1>",
                       lambda e, m=mid: self._edit_title_popup(m))
        txt_body.bind("<Double-Button-1>",
                      lambda e, m=mid: self._enter_edit_mode(m))
        # 체크박스 토글: 편집모드 아닐 때(disabled) 글리프 클릭 → ☐↔☑
        txt_body.bind("<Button-1>",
                      lambda e, m=mid: self._toggle_checkbox(m, e))
        # 본문 선택 줄 캡처(리본 줄색용) — 포커스 이탈 전 미리 저장
        txt_body.bind("<ButtonRelease-1>",
                      lambda e, m=mid: self._capture_body_sel(m), add="+")
        txt_body.bind("<KeyRelease>",
                      lambda e, m=mid: self._capture_body_sel(m), add="+")
        # Ctrl+Z/Y: Text 내부 edit_undo/redo와 충돌 방지 — canvas undo로 차단
        txt_body.bind("<Control-z>", lambda e: "break")
        txt_body.bind("<Control-y>", lambda e: "break")
        # 이모지 삽입 대상 추적
        txt_body.bind("<FocusIn>", lambda e, w=txt_body: setattr(self, "_last_text_focus", w), add="+")

        # ── 핸들 Z-order 보장 ────────────────────────
        handle.lift()

        # ── 스케줄 비활성 배지 (FSEditor 전용) ────────────
        # Viewer에서는 비활성 메모가 아예 미표시됨.
        # FSEditor는 전체 메모 표시 → 비활성 상태임을 시각적으로 알림.
        # 리뷰 지적: "유령 메모" 방지 — 스케줄 비활성 메모도 편집/삭제 가능해야 함.
        # stipple 점묘: PIL alpha 불필요 — Tkinter 네이티브로 50% 투명 효과
        if memo.get("schedule_enabled", False) and not _is_scheduled_now(memo):
            # 헤더에 ⏰ 비활성 배지
            tk.Label(header,
                     text=t("lbl_schedule_off", L),
                     bg="#374151", fg="#9ca3af",
                     font=("Malgun Gothic", 7),
                     padx=3, pady=1
                     ).pack(side="right", padx=2, pady=2)
            # 카드 위에 반투명 오버레이 (stipple=gray50 → 50% 불투명)
            # create_window 이후 좌표를 사용해야 하므로 after 50ms 지연
            def _add_inactive_overlay(m=mid, _w=w, _h=h):
                card = self._cards.get(m)
                if not card:
                    return
                try:
                    coords = self.canvas.coords(card["item_id"])
                    if len(coords) < 2:
                        return
                    cx, cy = int(coords[0]), int(coords[1])
                    ov_id = self.canvas.create_rectangle(
                        cx, cy, cx + _w, cy + _h,
                        fill="#111111", outline="",
                        stipple="gray50",
                        tags=f"inactive_{m}"
                    )
                    self.canvas.tag_raise(f"inactive_{m}")
                    card["inactive_id"] = ov_id
                except Exception:
                    pass
            self.canvas.after(50, _add_inactive_overlay)

    # ══ 드래그 ══════════════════════════════════════════

    def _bind_drag_recursive(self, widget, mid: str,
                              exclude_tags: set = None):
        """
        위젯 및 모든 자식에 드래그 바인딩 재귀 적용.
        exclude_tags: 드래그 바인딩 덮어쓰기 제외 위젯 태그.
        """
        if exclude_tags and getattr(widget, '_fs_tag', None) in exclude_tags:
            return
        widget.bind("<ButtonPress-1>",
                    lambda e, m=mid: self._drag_start(e, m))
        widget.bind("<B1-Motion>",
                    lambda e, m=mid: self._drag_move(e, m))
        widget.bind("<ButtonRelease-1>",
                    lambda e, m=mid: self._drag_end(e, m))
        for child in widget.winfo_children():
            self._bind_drag_recursive(child, mid, exclude_tags)

    def _restore_all_hidden(self):
        """숨김(드래그) 상태의 모든 카드/그림자/테두리를 강제 복원.
        불완전 드래그로 인한 '메모 사라짐' 방지용 안전장치."""
        for _mid, _g in list(getattr(self, "_ghosts", {}).items()):
            try: self.canvas.delete(_g)
            except Exception: pass
        self._ghosts = {}
        self._drag = {}
        for _mid, card in list(self._cards.items()):
            iid = card.get("item_id")
            if iid is None:
                continue
            try:
                self.canvas.itemconfigure(iid, state="normal")
                self.canvas.itemconfigure(f"shadow_{_mid}", state="normal")
                self.canvas.itemconfigure(f"border_{_mid}", state="normal")
            except Exception:
                pass

    def _drag_start(self, event, mid: str):
        # 이전 드래그 잔여(숨김 카드) 정리 — 사라짐 방지
        if getattr(self, "_ghosts", None):
            self._restore_all_hidden()
        self._close_title_ents()   # 떠 있는 제목 편집창 닫기
        # 편집 중 처리: 제목바(카드) 클릭 = 편집 종료 후 선택으로 전환
        if self._edit_mid == mid:
            self._exit_edit_mode(mid)
        elif self._edit_mid and self._edit_mid != mid:
            self._exit_edit_mode(self._edit_mid)

        # 제목바/카드 클릭 = 표 전체 선택으로 전환:
        # 셀 Entry 포커스 해제(단축키 정상화) + 표 셀 선택 해제
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        if getattr(self, "_tbl_sel", None):
            for _m, _sel in list(self._tbl_sel.items()):
                if _sel:
                    _sel.clear()
                    self._refresh_cell_sel(_m)

        # ── Ctrl+클릭: 다중 선택 토글 ──────────────────
        if event.state & 0x4:   # Ctrl 키 감지 (Windows Tkinter 표준값)
            if mid in self._selected:
                self._selected.discard(mid)
                self._set_card_border(mid, selected=False)
            else:
                self._selected.add(mid)
                self._set_card_border(mid, selected=True)
            self._sync_ribbon()
            return   # 토글만, 드래그 시작 없음

        # 단독 클릭: 선택 해제 후 현재 카드만 선택
        if mid not in self._selected:
            self._clear_selection()
            self._selected = {mid}
            self._set_card_border(mid, selected=True)
            self._sync_ribbon()
        # 겹침 상태에서 제목바/카드 클릭 시 항상 최상단(이미 선택된 경우도 포함)
        self._raise_to_front(mid)

        cx0 = self.canvas.winfo_rootx()
        cy0 = self.canvas.winfo_rooty()
        self._drag_origin = (cx0, cy0)                 # 매 프레임 winfo 조회 제거용 캐시
        self._drag_bounds = self._get_selection_bounds()   # 드래그 중 불변 → 1회 캐시
        for sel_mid in self._selected:
            try:
                coords = self.canvas.coords(self._cards[sel_mid]["item_id"])
            except Exception:
                continue
            if len(coords) < 2:
                continue
            self._drag[sel_mid] = {
                "rx0": event.x_root - cx0,
                "ry0": event.y_root - cy0,
                "ix0": coords[0],
                "iy0": coords[1],
                "mx0": event.x_root - cx0,
                "my0": event.y_root - cy0,
            }
            # ⚠️ 숨김·고스트 생성은 실제 이동(_drag_move) 전까지 미룸.
            #    클릭 즉시 숨기면 위젯 unmap으로 포인터 grab이 풀려
            #    ButtonRelease(_drag_end) 미발동 → 카드 사라짐.
        self.canvas.delete("guide")

    def _ensure_ghosts(self):
        """첫 이동 시 카드 숨김 + 고스트 생성(1회). 단순 클릭은 호출 안 됨."""
        if self._ghosts:
            return
        for sel_mid in list(self._drag.keys()):
            card = self._cards.get(sel_mid)
            if not card:
                continue
            try:
                coords = self.canvas.coords(card["item_id"])
            except Exception:
                continue
            if len(coords) < 2:
                continue
            cw = card["w"]; ch = card["h"]
            gx, gy = coords[0], coords[1]
            self.canvas.itemconfigure(card["item_id"], state="hidden")
            self.canvas.itemconfigure(f"shadow_{sel_mid}", state="hidden")
            self.canvas.itemconfigure(f"border_{sel_mid}", state="hidden")
            self._ghosts[sel_mid] = self.canvas.create_rectangle(
                gx, gy, gx + cw, gy + ch,
                outline=card.get("hdr_bg", "#5b8dee"),
                width=2, dash=(5, 3), tags=f"ghost_{sel_mid}")

    def _clear_selection(self):
        """선택된 모든 카드의 border 색상 초기화."""
        for sel_mid in list(self._selected):
            self._set_card_border(sel_mid, selected=False)
        self._selected.clear()
        self._sync_ribbon()

    def _on_canvas_click(self, event=None):
        """빈 배경 클릭 → 편집 종료 + 선택/셀선택/포커스 해제.
        (카드는 임베드 위젯이 클릭을 소비하므로, 이 핸들러는 배경에서만 발생)"""
        # 드래그 진행 중이면 숨김 카드 복원 후 무시(사라짐 방지)
        if getattr(self, "_ghosts", None) or getattr(self, "_drag", None):
            self._restore_all_hidden()
            return
        if self._edit_mid:
            self._exit_edit_mode(self._edit_mid)
        self._close_title_ents()   # 떠 있는 제목 편집창 닫기
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        if getattr(self, "_tbl_sel", None):
            for _m, _sel in list(self._tbl_sel.items()):
                if _sel:
                    _sel.clear()
                    self._refresh_cell_sel(_m)
        if self._selected:
            self._clear_selection()

    def _set_card_border(self, mid: str, selected: bool):
        """선택 테두리. 초록 테두리는 카드 위젯(outer) highlight로 그림 —
        캔버스 사각형은 임베드 윈도우에 가려 끊기므로(Tk 제약) 위젯 자체에 표시."""
        card = self._cards.get(mid)
        if not card:
            return
        outer = card.get("outer")
        if selected:
            if outer is not None:
                try:
                    outer.config(highlightthickness=3,
                                 highlightbackground="#22c55e",
                                 highlightcolor="#22c55e")
                except Exception:
                    pass
            try:
                self.canvas.itemconfig(f"border_{mid}", outline="#22c55e", width=2)
            except Exception:
                pass
        else:
            if outer is not None:
                try:
                    outer.config(highlightthickness=0)
                except Exception:
                    pass
            try:
                self.canvas.itemconfig(f"border_{mid}",
                                       outline=card.get("hdr_bg", "#5b8dee"), width=1)
            except Exception:
                pass

    def _get_selection_bounds(self) -> tuple:
        """
        선택된 카드 전체의 바운딩 박스 (min_x, min_y, max_x, max_y).
        _drag_move에서 바운딩 박스 기준 클램핑 → 카드 대형 유지.
        """
        xs, ys, x2s, y2s = [], [], [], []
        for sel_mid in self._selected:
            card = self._cards.get(sel_mid)
            if not card:
                continue
            try:
                coords = self.canvas.coords(card["item_id"])
            except Exception:
                continue
            if len(coords) < 2:
                continue
            cx, cy = coords[0], coords[1]
            xs.append(cx);  ys.append(cy)
            x2s.append(cx + card["w"])
            y2s.append(cy + card["h"])
        if not xs:
            return 0, 0, self.memo_w, self.canvas_h
        return min(xs), min(ys), max(x2s), max(y2s)

    def _drag_move(self, event, mid: str):
        d = self._drag.get(mid)
        if not d:
            return
        cx0, cy0 = self._drag_origin or (self.canvas.winfo_rootx(), self.canvas.winfo_rooty())
        raw_dx = (event.x_root - cx0) - d["rx0"]
        raw_dy = (event.y_root - cy0) - d["ry0"]

        # 실제 이동일 때만 숨김·고스트 생성(미세 이동=클릭으로 간주 → 카드 안 숨김)
        if not self._ghosts:
            if abs(raw_dx) < 3 and abs(raw_dy) < 3:
                return
            self._ensure_ghosts()

        # ── 바운딩 박스 기준 클램핑 (drag_start에서 캐시) ───────────
        bb_x1, bb_y1, bb_x2, bb_y2 = self._drag_bounds or self._get_selection_bounds()
        dx = max(-bb_x1, min(self.memo_w  - bb_x2, raw_dx))
        dy = max(-bb_y1, min(self.canvas_h - bb_y2, raw_dy))

        # 선택된 카드의 고스트 사각형만 이동 (위젯은 drag_end에서 1회 반영)
        for sel_mid in self._selected:
            s = self._drag.get(sel_mid)
            g = self._ghosts.get(sel_mid)
            if not s or g is None:
                continue
            nx = s["ix0"] + dx
            ny = s["iy0"] + dy
            cw = self._cards[sel_mid]["w"]
            ch = self._cards[sel_mid]["h"]
            try:
                self.canvas.coords(g, nx, ny, nx + cw, ny + ch)
            except Exception:
                pass

    def _drag_end(self, event, mid: str):
        """선택된 모든 카드의 최종 위치를 rel_*로 저장."""
        self._drag_origin = None
        self._drag_bounds = None
        moved = bool(self._ghosts)   # 실제 이동 여부(고스트 존재)

        # 고스트 최종 위치 → 실제 위젯 이동 + 표시 복원 + 고스트 삭제
        # ⚠️ _selected가 아니라 _ghosts(실제 숨긴 카드) 기준으로 복원
        #    (드래그 중 선택이 바뀌어도 숨긴 카드가 반드시 복원되도록)
        for sel_mid in list(self._ghosts.keys()):
            g = self._ghosts.pop(sel_mid, None)
            card = self._cards.get(sel_mid)
            if g is None:
                continue
            if not card:
                # 카드가 사라졌어도 숨김 상태만은 복원 시도
                try:
                    self.canvas.itemconfigure(f"shadow_{sel_mid}", state="normal")
                    self.canvas.itemconfigure(f"border_{sel_mid}", state="normal")
                    self.canvas.delete(g)
                except Exception:
                    pass
                continue
            try:
                gc = self.canvas.coords(g)
                if len(gc) >= 2:
                    nx, ny = gc[0], gc[1]
                    cw, ch = card["w"], card["h"]
                    self.canvas.coords(card["item_id"], nx, ny)
                    self.canvas.coords(f"shadow_{sel_mid}", nx+3, ny+3, nx+cw+3, ny+ch+3)
                    self.canvas.coords(f"border_{sel_mid}", nx-1, ny-1, nx+cw+1, ny+ch+1)
                self.canvas.itemconfigure(card["item_id"], state="normal")
                self.canvas.itemconfigure(f"shadow_{sel_mid}", state="normal")
                self.canvas.itemconfigure(f"border_{sel_mid}", state="normal")
                self.canvas.delete(g)
            except Exception:
                pass
        # 실측 캔버스 크기
        try:
            self.canvas.update_idletasks()
            real_cw = self.canvas.winfo_width()
            real_ch = self.canvas.winfo_height()
        except Exception:
            real_cw, real_ch = 1, 1
        memo_w   = real_cw  if real_cw  > 10 else self.memo_w
        canvas_h = real_ch  if real_ch  > 10 else self.canvas_h

        # 순수 클릭(이동 없음)은 위치 저장·undo 생략(변화 없음 + undo 오염 방지)
        saved_any = False
        if moved:
            for sel_mid in list(self._selected):
                card = self._cards.get(sel_mid)
                if not card:
                    continue
                try:
                    coords = self.canvas.coords(card["item_id"])
                except Exception:
                    continue
                if len(coords) < 2:
                    continue
                nx = max(0, min(memo_w  - card["w"], int(coords[0])))
                ny = max(0, min(canvas_h - card["h"], int(coords[1])))
                memo = next((m for m in self._memos if m["id"] == sel_mid), None)
                if memo:
                    if not saved_any:
                        self._push_undo("이동")
                        saved_any = True
                    memo["x"], memo["y"] = nx, ny
                    memo.update(_abs_to_rel(nx, ny, card["w"], card["h"],
                                            memo_w, canvas_h))
                    memo["_saved_canvas_w"]    = memo_w
                    memo["_saved_canvas_h"]    = canvas_h
                    memo["_saved_split_ratio"] = self.app.config.get("split_ratio", 0.65)
                    memo["updated_at"]         = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._drag = {}   # 드래그 상태 정리

    # ══ 리사이즈 ════════════════════════════════════════

    def _resize_start(self, event, mid: str):
        card = self._cards.get(mid)
        if not card:
            return
        # 접힘 상태 방어: 크기 변경 금지(핸들은 숨겨져 있으나 이중 안전)
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if memo and memo.get("collapsed"):
            return
        self._resize[mid] = {
            "mx0": event.x_root,
            "my0": event.y_root,
            "w0":  card["w"],
            "h0":  card["h"],
        }

    def _resize_move(self, event, mid: str):
        r    = self._resize.get(mid)
        card = self._cards.get(mid)
        if not r or not card:
            return
        # 캔버스 소멸 방어
        try:
            if not self.canvas.winfo_exists():
                return
            coords = self.canvas.coords(card["item_id"])
        except Exception:
            return
        if len(coords) < 2:
            return
        ix, iy = coords[0], coords[1]
        dx = event.x_root - r["mx0"]
        dy = event.y_root - r["my0"]
        nw = max(self.MIN_W, r["w0"] + dx)
        nh = max(self.MIN_H, r["h0"] + dy)
        nw = min(nw, self.memo_w  - int(ix))
        nh = min(nh, self.canvas_h - int(iy))
        card["outer"].config(width=nw, height=nh)
        card["w"], card["h"] = nw, nh
        card["handle"].lift()
        # 그림자·테두리도 새 크기로 갱신 — 미갱신 시 축소하면 잔상 남음
        try:
            self.canvas.coords(card["shadow_id"], ix + 3, iy + 3, ix + nw + 3, iy + nh + 3)
            self.canvas.coords(card["border_id"], ix - 1, iy - 1, ix + nw + 1, iy + nh + 1)
        except Exception:
            pass

    def _resize_end(self, event, mid: str):
        r = self._resize.pop(mid, None)
        if not r:
            return
        card = self._cards.get(mid)
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not card or not memo:
            return
        # coords() 빈 리스트 방어
        try:
            coords = self.canvas.coords(card["item_id"])
        except Exception:
            return
        if len(coords) < 2:
            return
        ix, iy = int(coords[0]), int(coords[1])
        # MIN_W/H 강제 + 캔버스 경계 클램핑
        nw = max(self.MIN_W, min(card["w"], self.memo_w  - ix))
        nh = max(self.MIN_H, min(card["h"], self.canvas_h - iy))
        card["outer"].config(width=nw, height=nh)
        card["w"], card["h"] = nw, nh
        # 그림자·테두리 최종 크기 동기화 — 축소 잔상 방지
        try:
            self.canvas.coords(card["shadow_id"], ix + 3, iy + 3, ix + nw + 3, iy + nh + 3)
            self.canvas.coords(card["border_id"], ix - 1, iy - 1, ix + nw + 1, iy + nh + 1)
        except Exception:
            pass
        # 저장 전 캔버스 실측 재확인
        try:
            self.canvas.update_idletasks()
            real_cw = self.canvas.winfo_width()
            real_ch = self.canvas.winfo_height()
        except Exception:
            real_cw, real_ch = 1, 1
        memo_w   = real_cw  if real_cw  > 10 else self.memo_w
        canvas_h = real_ch  if real_ch  > 10 else self.canvas_h

        memo["width"], memo["height"] = nw, nh
        memo.update(_abs_to_rel(
            ix, iy, nw, nh,
            memo_w, canvas_h
        ))
        memo["_saved_canvas_w"]    = memo_w
        memo["_saved_canvas_h"]    = canvas_h
        memo["_saved_split_ratio"] = self.app.config.get("split_ratio", 0.65)
        memo["updated_at"]         = time.strftime("%Y-%m-%dT%H:%M:%S")
        # 이미지 메모: 새 크기에 맞춰 사진 재스케일(카드 재생성)
        if memo.get("kind") == "image":
            self._rebuild_card(mid)

    # ══ 편집 모드 ════════════════════════════════════════

    def _enter_edit_mode(self, mid: str):
        """
        본문 더블클릭 → 편집 모드 진입.
        overrideredirect 창 키보드 입력: focus_force 필수.
        """
        card = self._cards.get(mid)
        if not card:
            return
        # 기존 편집 카드 먼저 저장
        if self._edit_mid and self._edit_mid != mid:
            self._exit_edit_mode(self._edit_mid)

        self._edit_mid = mid
        self._last_edit_mid = mid
        # 리본이 이 메모를 대상으로 인식하도록 선택 고정 + 동기화
        self._selected = {mid}
        self._set_card_border(mid, selected=True)
        self._sync_ribbon()
        self._rb_set_align_target("body")   # 본문 편집 → 정렬 타깃=본문
        txt = card["txt_body"]
        txt.config(state="normal", cursor="xterm")
        # 이모지 패널(Win+.)·IME 후보창이 뜰 수 있도록 모달 grab 해제
        try:
            self.overlay.grab_release(); self._grab_active = False
        except Exception:
            pass
        txt.focus_force()   # overrideredirect 창 키보드 입력 필수
        txt.mark_set("insert", "end")
        card["handle"].lift()

        # 모드 라벨 업데이트
        self._set_mode_label("✏️ 편집 모드 (Ctrl+Enter=확인  ESC=취소  이모지 Win+. 가능)", "#f0c040")

        txt.bind("<Control-Return>", lambda e, m=mid: self._exit_edit_mode(m))
        txt.bind("<Escape>",         lambda e, m=mid: self._exit_edit_mode(m))
        # ⚠️ FocusOut 자동종료 제거: 이모지 패널/IME가 포커스를 가져가도 편집 유지.
        #    편집 종료는 배경/제목바/다른카드 클릭·Ctrl+Enter·Esc가 담당.

        # 편집 중 드래그 비활성화 (실수 이동 방지)
        for w in [card["header"], card["outer"]]:
            w.unbind("<B1-Motion>")

    def _exit_edit_mode(self, mid: str):
        """편집 완료 → 내용 저장 + 드래그 모드 복귀."""
        if self._edit_mid != mid:
            return
        card = self._cards.get(mid)
        if not card:
            self._edit_mid = None
            return

        txt = card["txt_body"]

        # ⚠️ FocusOut 선제 해제 (무한 루프 방지)
        try:
            txt.unbind("<FocusOut>")
        except Exception:
            pass

        # ── [종료 3] 위젯 생존 여부 확인 ─────────────────────────
        # overlay 파괴(Alt+F4, OS 강제 종료 등) 중 _exit_edit_mode 호출 시
        # txt.get() / canvas.focus_set() 등에서 TclError → 비정상 종료
        canvas_alive = False
        txt_alive    = False
        try:
            canvas_alive = self.canvas.winfo_exists()
        except Exception:
            pass
        try:
            txt_alive = txt.winfo_exists()
        except Exception:
            pass

        if not canvas_alive:
            # 창이 파괴되는 중 → 저장만 안전하게 시도 후 상태 초기화
            self._edit_mid = None
            return

        memo = next((m for m in self._memos if m["id"] == mid), None)
        if memo and txt_alive:
            try:
                new_body  = txt.get("1.0", "end-1c")
            except Exception:
                new_body  = memo.get("body", "")
            new_title = card["title_var"].get()
            memo["body"]       = new_body
            memo["title"]      = new_title[:100]
            memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        if txt_alive:
            try:
                txt.config(state="disabled", cursor="arrow")
                txt.unbind("<Control-Return>")
                txt.unbind("<Escape>")
            except Exception:
                pass

        # 모드 라벨 복귀 — 창 파괴 중 TclError 명시적 차단
        try:
            self._set_mode_label("🖱️ 드래그 모드", "#34d399")
        except tk.TclError:
            pass
        except Exception:
            pass

        # 드래그 바인딩 재연결
        try:
            self._bind_drag_recursive(
                card["outer"], mid,
                exclude_tags={"resize_handle", "edit_text"}
            )
        except Exception:
            pass

        self._edit_mid = None

        # canvas.focus_set() + 모달 grab 복원 (편집 종료 후 다시 모달)
        try:
            if self.canvas.winfo_exists():
                self.canvas.focus_set()
                if not self._grab_active:
                    self.overlay.grab_set(); self._grab_active = True
        except tk.TclError:
            pass
        except Exception:
            pass

    def _close_title_ents(self):
        """떠 있는 제목 편집 Entry 정리 — 파괴 전에 값을 직접 저장(FocusOut 순서 의존 X)."""
        for k, ent in list(self.__dict__.items()):
            if k.startswith("_title_ent_") and ent is not None:
                mid = k[len("_title_ent_"):]
                try:
                    if ent.winfo_exists():
                        nt = ent.get()[:100]
                        card = self._cards.get(mid)
                        if card:
                            try: card["title_var"].set(nt)
                            except Exception: pass
                        memo = next((m for m in self._memos if m["id"] == mid), None)
                        if memo:
                            memo["title"] = nt
                            memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                except Exception:
                    pass
                try:
                    if ent.winfo_exists():
                        ent.destroy()
                except Exception:
                    pass
                setattr(self, k, None)
        try:
            if not self._grab_active and self.overlay.winfo_exists():
                self.overlay.grab_set(); self._grab_active = True
        except Exception:
            pass

    def _edit_title_popup(self, mid: str):
        """
        제목 더블클릭 → 헤더 위에 Entry 인라인 오버레이.
        FocusOut 시 자동 저장.
        """
        card = self._cards.get(mid)
        if not card:
            return
        # 기존 편집 종료
        if self._edit_mid:
            self._exit_edit_mode(self._edit_mid)

        header   = card["header"]
        hdr_bg   = card["hdr_bg"]
        tfs      = card["tfs"]
        attr_key = f"_title_ent_{mid}"

        # 중복 Entry 방지
        existing = getattr(self, attr_key, None)
        if existing:
            try:
                existing.destroy()
            except Exception:
                pass

        ent = tk.Entry(header, bg=hdr_bg, fg="#1a1a1a",
                       relief="flat", bd=1,
                       font=_safe_font("Malgun Gothic", tfs, "bold"),
                       insertbackground="#1a1a1a")
        ent.insert(0, card["title_var"].get())
        ent.select_range(0, "end")
        ent.place(x=4, y=3, relwidth=0.95, height=tfs + 10)
        # 이모지/IME 위해 모달 grab 해제
        try:
            self.overlay.grab_release(); self._grab_active = False
        except Exception:
            pass
        self._rb_set_align_target("title")   # 제목 편집 → 정렬 타깃=제목
        ent.focus_force()
        setattr(self, attr_key, ent)

        def _commit(e=None):
            # winfo_exists 이중 가드 (Entry 소멸 후 FocusOut 오발동 방지)
            try:
                if not ent.winfo_exists():
                    return
            except Exception:
                return
            # FocusOut 바인딩 선제 해제 (리사이즈 클릭 시 중복 발동 방지)
            try:
                ent.unbind("<FocusOut>")
            except Exception:
                pass
            new_title = ent.get()[:100]
            card["title_var"].set(new_title)
            memo = next((m for m in self._memos if m["id"] == mid), None)
            if memo:
                memo["title"]      = new_title
                memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                ent.destroy()
            except Exception:
                pass
            setattr(self, attr_key, None)
            self.canvas.focus_set()
            try:
                if not self._grab_active:
                    self.overlay.grab_set(); self._grab_active = True
            except Exception:
                pass

        def _save(e=None):
            # FocusOut: 값만 저장하고 Entry는 유지(이모지 팔레트 삽입 가능하도록)
            try:
                if not ent.winfo_exists():
                    return
            except Exception:
                return
            nt = ent.get()[:100]
            card["title_var"].set(nt)
            memo = next((m for m in self._memos if m["id"] == mid), None)
            if memo:
                memo["title"]      = nt
                memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        ent.bind("<Return>",   _commit)
        ent.bind("<Escape>",   lambda e: (ent.destroy(),
                                           setattr(self, attr_key, None),
                                           self.canvas.focus_set()))
        ent.bind("<FocusOut>", _save)   # 파괴 대신 저장만
        ent.bind("<FocusIn>",  lambda e: setattr(self, "_last_text_focus", ent))
        self._last_text_focus = ent

    # ══ ESC 계층 ════════════════════════════════════════

    def _on_escape(self, event=None):
        """
        ESC 계층:
          편집 모드 중 → _exit_edit_mode
          선택 카드 있음 → 선택 해제
          드래그 모드  → _cancel
        """
        if self._edit_mid:
            self._exit_edit_mode(self._edit_mid)
        elif self._selected:
            self._clear_selection()
        else:
            self._cancel()

    # ══ 저장 / 닫기 ══════════════════════════════════════

    # ══ Undo / Redo ══════════════════════════════════════

    def _push_undo(self, action: str = ""):
        """
        현재 _memos 상태를 undo 스택에 스냅샷 저장.
        deepcopy 사용 — import copy 모듈 레벨 추가됨(v8_84).
        스택 30개 제한 (메모 10개 × 5KB × 30 ≈ 1.5MB 허용 범위).
        """
        self._undo_stack.append((action, copy.deepcopy(self._memos)))
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)
        self._redo_stack.clear()   # 새 액션 → redo 스택 초기화

    def _undo(self, event=None):
        """Ctrl+Z — 마지막 액션 되돌리기."""
        if not self._undo_stack:
            return
        action, snapshot = self._undo_stack.pop()
        self._redo_stack.append(("redo", copy.deepcopy(self._memos)))
        self._memos = snapshot
        self._render_all_fs()
        self._set_mode_label(f"↩ 실행 취소: {action}", "#9ca3af")

    def _redo(self, event=None):
        """Ctrl+Y — 되돌린 액션 다시 실행."""
        if not self._redo_stack:
            return
        _, snapshot = self._redo_stack.pop()
        self._undo_stack.append(("redo", copy.deepcopy(self._memos)))
        self._memos = snapshot
        self._render_all_fs()
        self._set_mode_label(f"↪ 다시 실행", "#9ca3af")

    def _set_mode_label(self, text: str, color: str = "#34d399"):
        """모드 상태 표시 라벨 업데이트."""
        try:
            self._mode_lbl.config(text=text, fg=color)
        except tk.TclError:
            pass   # 창 파괴 중 접근 → 무시
        except Exception:
            pass

    def _try_grab_set(self, retries=3):
        """grab_set 지연 재시도 — 블로킹 방어."""
        if retries <= 0:
            LOG.warning("[FSEditor] grab_set 3회 실패 → grab 없이 진행 (topmost로 보완)")
            return
        try:
            if not self.overlay.winfo_exists():
                return
            self.overlay.grab_set()
            self._grab_active = True
            LOG.info("[FSEditor] grab_set 성공")
        except Exception as e:
            LOG.debug(f"[FSEditor] grab_set 재시도 {4-retries}/3 실패: {e}")
            self.overlay.after(200, lambda: self._try_grab_set(retries - 1))

    def _release_grab(self):
        """grab_release 안전 호출 — 어떤 경로에서도 반드시 해제."""
        if self._grab_active:
            try:
                self.overlay.grab_release()
            except Exception:
                pass
            self._grab_active = False

    def _save_and_close(self):
        LOG.info("[FSEditor] 🛑 _save_and_close 진입 성공!")

        # 1. 편집 모드 해제
        if self._edit_mid:
            try:
                self._exit_edit_mode(self._edit_mid)
                LOG.info("[FSEditor] 1. 편집 모드 해제 완료")
            except tk.TclError as te:
                # 창 파괴 중 TclError → 데이터는 _exit_edit_mode 내부에서 커밋됨
                LOG.warning(f"[FSEditor] 1. 편집 해제 중 UI 파괴 감지 (정상 종료 과정): {te}")
                self._edit_mid = None   # 상태 초기화 보장
            except Exception as e:
                LOG.error(f"[FSEditor] 편집 모드 해제 오류: {e}")

        # 2. 데이터 저장
        try:
            LOG.info(f"[FSEditor] 2-pre. _memos 타입: {type(self._memos)}, 길이: {len(self._memos) if self._memos else 'None'}")
            save_memos(self._memos)
            LOG.info("[FSEditor] 2. 메모 데이터 저장 완료")
        except NameError:
            LOG.error("[FSEditor] 🚨 NameError: save_memos 함수를 찾을 수 없음")
        except Exception as e:
            import traceback as _tb
            LOG.error(f"[FSEditor] 🚨 메모 저장 오류: {e}\n{_tb.format_exc()}")

        # 3. 화면 새로고침
        try:
            if hasattr(self, 'app') and self.app:
                self.app._refresh_memo_summary()
                LOG.info("[FSEditor] 3. 메인 화면 새로고침 완료")
        except Exception as e:
            LOG.error(f"[FSEditor] 화면 새로고침 오류: {e}")

        # 4. Grab 해제 + 창 파괴
        try:
            self._release_grab()
            LOG.info("[FSEditor] 4. Grab 해제 완료")
            if self.overlay.winfo_exists():
                self.overlay.destroy()
                LOG.info("[FSEditor] 5. 오버레이 창 파괴 완료")
        except Exception as e:
            LOG.error(f"[FSEditor] 🚨 창 종료 오류: {e}")

        # 5. 참조 해제 (가장 마지막)
        try:
            if hasattr(self, 'app') and self.app:
                self.app._fs_editor = None
                LOG.info("[FSEditor] 6. 참조 초기화 완료 ✅")
        except Exception:
            pass

    def _cancel(self):
        """변경사항 버리고 닫기 (memo.json 저장 없음)."""
        L = self.app.config.get("language", "ko")
        # 편집 중인 카드가 있으면 경고
        if self._edit_mid:
            try:
                if not tk.messagebox.askyesno(
                    t("fs_confirm_close", L),
                    t("fs_unsaved_msg", L),
                    parent=self.overlay
                ):
                    return
            except Exception:
                pass
            # 경고 확인 후 편집 종료 (저장 없이)
            try:
                card = self._cards.get(self._edit_mid)
                if card:
                    card["txt_body"].config(state="disabled", cursor="arrow")
            except Exception:
                pass
            self._edit_mid = None
        try:
            self.app._fs_editor = None
        except Exception:
            pass
        self._release_grab()
        try:
            self.overlay.destroy()
        except Exception:
            pass

    # ══ 새 메모 추가 ═════════════════════════════════

    # ── 템플릿 메뉴(기본 + 사용자 커스텀 양식) ──────────
    _TMPL_STYLE_KEYS = ("color_key", "font_family", "title_font_size",
                        "body_font_size", "title_text_color",
                        "body_text_color", "opacity")

    def _show_tmpl_menu(self):
        """템플릿 버튼 아래로 메뉴 팝업(overlay grab 해제 후)."""
        btn = self._tmpl_btn
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height()
        try:
            self.overlay.grab_release(); self._grab_active = False
        except Exception:
            pass
        def _on_close(e=None):
            try:
                if not self._grab_active:
                    self.overlay.grab_set(); self._grab_active = True
            except Exception:
                pass
        self._tmpl_menu.bind("<Unmap>", lambda e: self.overlay.after(50, _on_close))
        try:
            self._tmpl_menu.tk_popup(x, y)
        finally:
            try: self._tmpl_menu.grab_release()
            except Exception: pass

    def _build_template_menu(self):
        """템플릿 드롭다운 재구성: 기본 + 표/달력 + 사용자 커스텀 + 저장/삭제."""
        L = self.app.config.get("language", "ko")
        m = self._tmpl_menu
        m.delete(0, "end")
        for name in MEMO_TEMPLATES:
            m.add_command(label=name,
                          command=lambda n=name: self._add_from_template(n))
        m.add_separator()
        m.add_command(label=t("btn_table_insert", L), command=self._insert_table)
        m.add_command(label=t("btn_calendar", L), command=self._insert_calendar)
        m.add_command(label=t("btn_image_insert", L), command=self._insert_image)

        customs = self.app.config.get("custom_memo_templates", {}) or {}
        if customs:
            m.add_separator()
            for name in customs:
                m.add_command(label=f"⭐ {name}",
                              command=lambda n=name: self._add_from_custom_template(n))
        # 즐겨찾기 지정 (바로가기 버튼 대상 1개)
        m.add_separator()
        favm = tk.Menu(m, tearoff=0, bg="#1e1e2e", fg="#e5e7eb",
                       activebackground="#5b8dee", font=("Malgun Gothic", 14))
        for name in MEMO_TEMPLATES:
            favm.add_command(label=name,
                             command=lambda n=name: self._set_favorite("builtin", n))
        favm.add_command(label=t("btn_table_insert", L),
                         command=lambda: self._set_favorite("table", ""))
        favm.add_command(label=t("btn_calendar", L),
                         command=lambda: self._set_favorite("calendar", ""))
        if customs:
            favm.add_separator()
            for name in customs:
                favm.add_command(label=f"⭐ {name}",
                                 command=lambda n=name: self._set_favorite("custom", n))
        m.add_cascade(label=t("fav_set", L), menu=favm)

        m.add_separator()
        m.add_command(label=t("tmpl_save", L),
                      command=self._save_current_as_template)
        m.add_command(label=t("fav_register", L),
                      command=self._register_favorite_current)
        if customs:
            delm = tk.Menu(m, tearoff=0, bg="#1e1e2e", fg="#e5e7eb",
                           activebackground="#5b8dee", font=("Malgun Gothic", 14))
            for name in customs:
                delm.add_command(label=f"🗑 {name}",
                                 command=lambda n=name: self._delete_custom_template(n))
            m.add_cascade(label=t("tmpl_delete", L), menu=delm)

    def _refresh_fav_btn(self):
        """즐겨찾기 바로가기 버튼 라벨 갱신."""
        L = self.app.config.get("language", "ko")
        fav = self.app.config.get("fav_template") or {}
        kind, name = fav.get("kind"), fav.get("name", "")
        if kind == "table":
            label = "⭐ " + t("btn_table_insert", L)
        elif kind == "calendar":
            label = "⭐ " + t("btn_calendar", L)
        elif kind in ("builtin", "custom") and name:
            label = f"⭐ {name}"
        else:
            label = t("fav_none", L)
        try: self._fav_btn.config(text=label)
        except Exception: pass

    def _set_favorite(self, kind: str, name: str):
        self.app.config["fav_template"] = {"kind": kind, "name": name}
        try: save_config(self.app.config)
        except Exception: pass
        self._refresh_fav_btn()

    def _run_favorite(self):
        """즐겨찾기 바로가기 실행. 미지정 시 일반 새 메모."""
        fav = self.app.config.get("fav_template") or {}
        kind, name = fav.get("kind"), fav.get("name", "")
        if kind == "builtin" and name:
            self._add_from_template(name)
        elif kind == "custom" and name:
            self._add_from_custom_template(name)
        elif kind == "table":
            self._insert_table()
        elif kind == "calendar":
            self._insert_calendar()
        else:
            self._add_new_memo()

    def _add_from_custom_template(self, name: str):
        """사용자 커스텀 양식으로 메모 생성(서식 포함)."""
        customs = self.app.config.get("custom_memo_templates", {}) or {}
        tmpl = customs.get(name)
        if not tmpl:
            return
        self._add_new_memo(
            preset_title=tmpl.get("title", "새 메모"),
            preset_body=tmpl.get("body", ""),
            skip_title_edit=True,
            preset_style={k: tmpl[k] for k in self._TMPL_STYLE_KEYS if k in tmpl},
            preset_line_colors=tmpl.get("line_colors") or {},
        )

    def _register_favorite_current(self):
        """현재 메모를 양식으로 저장 + 즐겨찾기 바로가기로 등록."""
        self._save_current_as_template(also_fav=True)

    def _save_current_as_template(self, also_fav: bool = False):
        """선택(또는 직전 편집) 메모의 내용·서식을 커스텀 양식으로 저장."""
        L = self.app.config.get("language", "ko")
        mid = self._rb_mid or self._last_edit_mid
        memo = next((x for x in self._memos if x["id"] == mid), None) if mid else None
        if not memo:
            self._set_mode_label(t("tmpl_need_sel", L), "#fbbf24")
            return
        if memo.get("kind") == "table":
            self._set_mode_label(t("tmpl_no_table", L), "#fbbf24")
            return

        def _commit(nm):
            nm = (nm or "").strip()
            if not nm:
                return
            store = self.app.config.setdefault("custom_memo_templates", {})
            payload = {"title": memo.get("title", ""), "body": memo.get("body", "")}
            for k in self._TMPL_STYLE_KEYS:
                if k in memo:
                    payload[k] = memo[k]
            if memo.get("line_colors"):
                payload["line_colors"] = dict(memo["line_colors"])
            store[nm] = payload
            if also_fav:
                self.app.config["fav_template"] = {"kind": "custom", "name": nm}
            try: save_config(self.app.config)
            except Exception: pass
            self._build_template_menu()
            if also_fav:
                self._refresh_fav_btn()
            self._set_mode_label(t("tmpl_saved", L).format(n=nm), "#34d399")

        self._text_input_panel(t("tmpl_prompt", L),
                               memo.get("title", "")[:20] or "내 양식", _commit)

    def _delete_custom_template(self, name: str):
        store = self.app.config.get("custom_memo_templates", {}) or {}
        if name in store:
            del store[name]
            try: save_config(self.app.config)
            except Exception: pass
            self._build_template_menu()

    def _text_input_panel(self, prompt: str, initial: str, on_ok):
        """캔버스 중앙 인라인 텍스트 입력 패널(양식 이름 등). on_ok(str) 콜백."""
        L = self.app.config.get("language", "ko")
        old = getattr(self, "_size_panel_id", None)
        if old is not None:
            try: self.canvas.delete(old)
            except Exception: pass
            self._size_panel_id = None
        panel = tk.Frame(self.canvas, bg="#1e1e2e",
                         highlightbackground="#5b8dee", highlightthickness=3)
        tk.Label(panel, text=prompt, bg="#1e1e2e", fg="#e5e7eb",
                 font=("Malgun Gothic", 12)).pack(padx=20, pady=(16, 8))
        var = tk.StringVar(value=initial)
        ent = tk.Entry(panel, textvariable=var, width=20, justify="center",
                       font=("Malgun Gothic", 14), bg="#2a2a3a", fg="#e5e7eb",
                       insertbackground="#e5e7eb", relief="flat")
        ent.pack(ipady=4, padx=20)

        def _close(*_):
            pid = getattr(self, "_size_panel_id", None)
            if pid is not None:
                try: self.canvas.delete(pid)
                except Exception: pass
            self._size_panel_id = None

        def _ok(*_):
            v = var.get()
            _close()
            on_ok(v)

        frm = tk.Frame(panel, bg="#1e1e2e"); frm.pack(pady=16, padx=20)
        tk.Button(frm, text=t("btn_ok", L), width=8, command=_ok).pack(side="left", padx=5)
        tk.Button(frm, text=t("btn_cancel2", L), width=8, command=_close).pack(side="left", padx=5)
        ent.bind("<Return>", _ok)
        ent.bind("<Escape>", _close)
        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width()  or self.mw
        ch = self.canvas.winfo_height() or self.mh
        self._size_panel_id = self.canvas.create_window(cw // 2, ch // 2,
                                                        window=panel, anchor="center")
        self.canvas.tag_raise(self._size_panel_id)
        ent.focus_force(); ent.select_range(0, "end")

    def _add_from_template(self, template_name: str):
        """템플릿 기반 메모 추가 — title/body 사전 설정."""
        tmpl = MEMO_TEMPLATES.get(template_name, {})
        # _add_new_memo 흐름 재사용
        self._add_new_memo(
            preset_title=tmpl.get("title", "새 메모"),
            preset_body=tmpl.get("body", ""),
            skip_title_edit=(len(tmpl.get("body", "")) > 0)
        )

    def _add_new_memo(self, preset_title: str = "새 메모",
                       preset_body: str = "",
                       skip_title_edit: bool = False,
                       kind: str = "text",
                       table: dict = None,
                       cal_meta: dict = None,
                       preset_style: dict = None,
                       preset_line_colors: dict = None,
                       image_path: str = None):
        """
        새 메모 추가 — 메모 영역 중앙 배치 + 겹침 방지.
        new_memo_template() 공통 함수로 규격 통일.
        추가 후 제목 편집 모드 자동 진입.
        """
        L = self.app.config.get("language", "ko")
        is_premium = self.app.config.get("is_premium", False)
        max_count  = TIER_CONFIG["premium" if is_premium else "free"]["max_memos"]
        visible    = _get_visible_memos(self._memos, is_premium)

        if len(visible) >= max_count:
            tk.messagebox.showinfo(
                t("fs_max_memo", L),
                t("fs_max_msg", L).format(n=max_count),
                parent=self.overlay
            )
            return
        self._push_undo("추가")

        dw = max(self.MIN_W, int(self.memo_w  * 0.20))
        dh = max(self.MIN_H, int(self.canvas_h * 0.20))
        base_x = (self.memo_w  - dw) // 2
        base_y = (self.canvas_h - dh) // 2
        existing = [
            (int(m.get("rel_x", 0.1) * self.memo_w),
             int(m.get("rel_y", 0.1) * self.canvas_h))
            for m in self._memos
        ]
        x, y = base_x, base_y
        for _ in range(15):
            if not any(abs(x - ex) < 40 and abs(y - ey) < 40
                       for ex, ey in existing):
                break
            x = min(x + 30, self.memo_w  - dw)
            y = min(y + 30, self.canvas_h - dh)

        rel = _abs_to_rel(x, y, dw, dh, self.memo_w, self.canvas_h)
        m   = new_memo_template()
        m.update({
            "title": preset_title,
            "body":  preset_body,
            "x": x, "y": y, "width": dw, "height": dh, **rel,
            "_saved_canvas_w":    self.memo_w,
            "_saved_canvas_h":    self.canvas_h,
            "_saved_split_ratio": self.app.config.get("split_ratio", 0.65),
        })
        if kind == "table" and table:
            m["kind"]  = "table"
            m["table"] = table
            if cal_meta:
                m["calendar"] = cal_meta
        elif kind == "image" and image_path:
            m["kind"] = "image"
            m["image_path"] = image_path
        if preset_style:
            m.update(preset_style)
        if preset_line_colors:
            m["line_colors"] = dict(preset_line_colors)
        self._memos.append(m)
        mid = m["id"]
        self._cards[mid] = {"w": dw, "h": dh}
        self._make_card(m, mid, x, y, dw, dh)
        self.canvas.delete("guide")
        if not skip_title_edit and kind != "table":
            self.canvas.after(100, lambda: self._edit_title_popup(mid))

    # ══ 단건 스타일 업데이트 ═════════════════════════

    # ── 커스텀 색상 (팔레트 선택/저장/삭제) ──────────
    def _pick_custom_color(self, mid: str):
        """색상 팔레트로 임의 색 선택 → config에 저장(공유) + 현재 메모 적용."""
        L = self.app.config.get("language", "ko")
        try:
            _rgb, hx = colorchooser.askcolor(parent=self.overlay,
                                             title=t("ctx_pick_color", L))
        except Exception:
            hx = None
        if not hx:
            return
        hx = hx.lower()
        customs = self.app.config.get("custom_memo_colors", []) or []
        if hx not in customs:
            if len(customs) >= 10:   # 상한 10개 도달 → 안내 후 차단
                messagebox.showinfo(t("ctx_pick_color", L),
                                    t("msg_custom_full", L), parent=self.overlay)
                return
            customs.append(hx)
            self.app.config["custom_memo_colors"] = customs
            try:
                save_config(self.app.config)
            except Exception:
                pass
        self._update_style(mid, "color_key", hx)

    def _del_custom_color(self, hx: str, mid: str):
        """저장된 커스텀 색 삭제. 현재 메모가 그 색이면 기본색으로 되돌림."""
        customs = self.app.config.get("custom_memo_colors", []) or []
        if hx in customs:
            customs.remove(hx)
            self.app.config["custom_memo_colors"] = customs
            try:
                save_config(self.app.config)
            except Exception:
                pass
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if memo and memo.get("color_key") == hx:
            self._update_style(mid, "color_key", "amber")   # 기본색 복귀

    # ── 시스템 글꼴 선택/저장/삭제 ──────────────────
    def _pick_system_font(self, mid: str):
        """설치된 시스템 글꼴 목록 다이얼로그 → 선택 저장(공유) + 현재 메모 적용."""
        import tkinter.font as _tkfont
        L = self.app.config.get("language", "ko")
        try:
            fams = sorted(set(_tkfont.families()))
        except Exception:
            fams = []
        # @세로쓰기 폰트 제외
        fams = [f for f in fams if f and not f.startswith("@")]
        if not fams:
            messagebox.showinfo(t("ctx_sys_font", L), t("msg_no_font", L),
                                parent=self.overlay)
            return

        dlg = tk.Toplevel(self.overlay)
        dlg.title(t("ctx_sys_font", L))
        dlg.transient(self.overlay)
        dlg.configure(bg="#1e1e2e")
        win_w, win_h = 380, 460
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"{win_w}x{win_h}+{(sw-win_w)//2}+{(sh-win_h)//2}")

        # 검색
        var_q = tk.StringVar()
        tk.Entry(dlg, textvariable=var_q, font=("Malgun Gothic", 12),
                 bg="#2a2a3a", fg="#e5e7eb", insertbackground="#e5e7eb",
                 relief="flat").pack(fill="x", padx=10, pady=(10, 4), ipady=4)

        # 리스트 + 스크롤
        frm = tk.Frame(dlg, bg="#1e1e2e")
        frm.pack(fill="both", expand=True, padx=10)
        sb = tk.Scrollbar(frm)
        sb.pack(side="right", fill="y")
        lb = tk.Listbox(frm, font=("Malgun Gothic", 12),
                        bg="#16181d", fg="#e5e7eb",
                        selectbackground="#5b8dee", selectforeground="white",
                        relief="flat", highlightthickness=0,
                        yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.config(command=lb.yview)

        # 미리보기
        prev = tk.Label(dlg, text=t("font_preview", L),
                        bg="#0f0f18", fg="#e5e7eb", height=2,
                        font=("Malgun Gothic", 20))
        prev.pack(fill="x", padx=10, pady=(6, 4))

        def _refill(*_):
            q = var_q.get().lower().strip()
            lb.delete(0, "end")
            for f in fams:
                if not q or q in f.lower():
                    lb.insert("end", f)

        def _on_sel(*_):
            sel = lb.curselection()
            if sel:
                try:
                    prev.config(font=(lb.get(sel[0]), 20))
                except Exception:
                    pass

        def _apply(*_):
            sel = lb.curselection()
            if not sel:
                return
            fn = lb.get(sel[0])
            customs = self.app.config.get("custom_memo_fonts", []) or []
            if fn not in customs and fn not in self._BASE_FONTS:
                if len(customs) >= 10:   # 상한 10개 도달 → 안내 후 차단(다이얼로그 유지)
                    messagebox.showinfo(t("ctx_sys_font", L),
                                        t("msg_custom_full", L), parent=dlg)
                    return
                customs.append(fn)
                self.app.config["custom_memo_fonts"] = customs
                try:
                    save_config(self.app.config)
                except Exception:
                    pass
            self._update_style(mid, "font_family", fn)
            _close()

        def _close(*_):
            try:
                if self.overlay.winfo_exists():
                    self.overlay.grab_set()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        # 버튼
        btnf = tk.Frame(dlg, bg="#1e1e2e")
        btnf.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(btnf, text=t("btn_ok", L), command=_apply,
                  bg="#5b8dee", fg="white", relief="flat",
                  font=("Malgun Gothic", 12), padx=14
                  ).pack(side="right", padx=(4, 0))
        tk.Button(btnf, text=t("btn_cancel2", L), command=_close,
                  bg="#374151", fg="#e5e7eb", relief="flat",
                  font=("Malgun Gothic", 12), padx=14
                  ).pack(side="right")

        var_q.trace_add("write", _refill)
        lb.bind("<<ListboxSelect>>", _on_sel)
        lb.bind("<Double-Button-1>", _apply)
        dlg.bind("<Escape>", _close)
        dlg.protocol("WM_DELETE_WINDOW", _close)
        _refill()

        # overlay 모달 grab 해제 후 다이얼로그 grab (색상 팝업과 동일 패턴)
        try:
            self.overlay.grab_release()
            self._grab_active = False
        except Exception:
            pass
        try:
            dlg.grab_set()
        except Exception:
            pass

    def _del_custom_font(self, fn: str, mid: str):
        """저장된 시스템 글꼴 삭제. 현재 메모가 그 글꼴이면 기본으로 되돌림."""
        customs = self.app.config.get("custom_memo_fonts", []) or []
        if fn in customs:
            customs.remove(fn)
            self.app.config["custom_memo_fonts"] = customs
            try:
                save_config(self.app.config)
            except Exception:
                pass
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if memo and memo.get("font_family") == fn:
            self._update_style(mid, "font_family", "Malgun Gothic")

    # ══ 표(테이블) — 생성·편집·셀색 ══════════════
    def _build_image_label(self, parent, memo, w, h, tfs):
        """이미지 메모 사진 라벨(폴라로이드 상단). 카드 크기에 맞춰 비율 유지 축소."""
        lbl = tk.Label(parent, bg="#ffffff", bd=0)
        path = memo.get("image_path")
        if not _HAS_PIL or not path:
            lbl.config(text="🖼", font=("Arial", 28), fg="#888888")
            return lbl
        try:
            im = Image.open(path)
            try: im = im.convert("RGBA")
            except Exception: pass
            aw = max(20, int(w) - 16)
            ah = max(20, int(h) - (int(tfs) + 24) - 12)
            im.thumbnail((aw, ah), Image.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            lbl.config(image=ph)
            lbl.image = ph   # GC 방지
        except Exception as e:
            LOG.error(f"[FSEditor] 이미지 로드 실패: {e}")
            lbl.config(text="🖼", font=("Arial", 28), fg="#888888")
        return lbl

    def _build_table_grid(self, parent, memo, mid, bg):
        """표 셀 그리드(Entry). 메모 글꼴 반영. 셀 편집→cells, 셀 선택·배경색 지원."""
        tbl   = memo.get("table") or {}
        rows  = max(1, int(tbl.get("rows", 1)))
        cols  = max(1, int(tbl.get("cols", 1)))
        cells = tbl.get("cells") or [["" for _ in range(cols)] for _ in range(rows)]
        bfs    = max(8, memo.get("body_font_size", 10))
        family = memo.get("font_family", "Malgun Gothic")   # 표에 글꼴 반영
        cfont  = _safe_font(family, bfs)
        fg     = resolve_text_color(memo.get("body_text_color"), "#1a1a1a")
        cell_bg = tbl.get("cell_bg") or {}
        cell_fg = tbl.get("cell_fg") or {}
        cell_align = tbl.get("cell_align") or {}

        if not hasattr(self, "_tbl_cells"): self._tbl_cells = {}
        if not hasattr(self, "_tbl_sel"):   self._tbl_sel = {}
        self._tbl_cells[mid] = {}
        self._tbl_sel[mid] = set()

        frame = tk.Frame(parent, bg="#888888")   # 셀 간 1px 간격=격자선 효과
        frame._fs_tag = "table_cell"             # 드래그/컨텍스트 재귀 제외(셀 전용 바인딩 보존)
        for c in range(cols):
            frame.grid_columnconfigure(c, weight=1, uniform="tcol")
        for r in range(rows):
            frame.grid_rowconfigure(r, weight=1, uniform="trow")
            for c in range(cols):
                val = cells[r][c] if (r < len(cells) and c < len(cells[r])) else ""
                var = tk.StringVar(value=val)
                cbg = cell_bg.get(f"{r},{c}", "#ffffff")
                cfg = cell_fg.get(f"{r},{c}", fg)
                cal = {"l": "left", "c": "center", "r": "right"}.get(
                    cell_align.get(f"{r},{c}", "l"), "left")
                ent = tk.Entry(frame, textvariable=var, font=cfont,
                               bg=cbg, fg=cfg, relief="flat", bd=0,
                               justify=cal, highlightthickness=1,
                               highlightbackground=cbg, highlightcolor="#2d7dff")
                ent._fs_tag = "table_cell"
                ent.grid(row=r, column=c, sticky="nsew", padx=1, pady=1, ipady=2)
                var.trace_add("write",
                              lambda *_, rr=r, cc=c, v=var: self._set_table_cell(mid, rr, cc, v.get()))
                ent.bind("<Button-1>", lambda e, rr=r, cc=c: self._cell_click(mid, rr, cc, e))
                ent.bind("<Button-3>", lambda e, rr=r, cc=c: self._cell_menu(mid, rr, cc, e))
                ent.bind("<FocusIn>", lambda e, w=ent: setattr(self, "_last_text_focus", w), add="+")
                self._tbl_cells[mid][(r, c)] = ent
        return frame

    def _cell_click(self, mid, r, c, event):
        """셀 선택(단일=클리어 후 선택 / Ctrl=토글). 편집 포커스는 유지(break 안 함)."""
        sel = self._tbl_sel.setdefault(mid, set())
        if event.state & 0x4:   # Ctrl
            sel.discard((r, c)) if (r, c) in sel else sel.add((r, c))
        else:
            sel.clear(); sel.add((r, c))
        self._refresh_cell_sel(mid)
        # 표 셀 클릭 = 그 표 단일 선택 → 리본 셀색 활성
        if mid not in self._selected or len(self._selected) != 1:
            self._clear_selection()
            self._selected = {mid}
            self._set_card_border(mid, selected=True)
        self._sync_ribbon()

    def _refresh_cell_sel(self, mid):
        memo = next((m for m in self._memos if m["id"] == mid), None)
        cell_bg = ((memo.get("table") or {}).get("cell_bg") or {}) if memo else {}
        sel = self._tbl_sel.get(mid, set())
        for (r, c), ent in self._tbl_cells.get(mid, {}).items():
            base = cell_bg.get(f"{r},{c}", "#ffffff")
            try:
                if (r, c) in sel:
                    ent.config(highlightthickness=2, highlightbackground="#2d7dff")
                else:
                    ent.config(highlightthickness=1, highlightbackground=base)
            except Exception:
                pass

    def _cell_menu(self, mid, r, c, event):
        """셀 우클릭 → 배경색 지정/지우기 (현재 선택 셀 대상, 없으면 클릭 셀)."""
        sel = self._tbl_sel.setdefault(mid, set())
        if (r, c) not in sel:
            sel.clear(); sel.add((r, c)); self._refresh_cell_sel(mid)
        L = self.app.config.get("language", "ko")
        menu = tk.Menu(self.overlay, tearoff=0, bg="#1e1e2e", fg="#e5e7eb",
                       activebackground="#5b8dee", activeforeground="white",
                       relief="flat", bd=1, font=("Malgun Gothic", 14))
        menu.add_command(label=t("cell_bg_set", L), command=lambda: self._apply_cell_bg(mid))
        menu.add_command(label=t("cell_bg_clear", L), command=lambda: self._clear_cell_bg(mid))
        menu.add_separator()
        menu.add_command(label=t("cell_fg_set", L), command=lambda: self._apply_cell_fg(mid))
        menu.add_command(label=t("cell_fg_clear", L), command=lambda: self._clear_cell_fg(mid))
        menu.add_separator()
        # 이 셀 위치 기준 행/열 삽입·삭제
        rowm = tk.Menu(menu, tearoff=0, bg="#1e1e2e", fg="#e5e7eb",
                       activebackground="#5b8dee", font=("Malgun Gothic", 14))
        rowm.add_command(label=t("tir_above", L), command=lambda: self._table_insert_row(mid, r))
        rowm.add_command(label=t("tir_below", L), command=lambda: self._table_insert_row(mid, r + 1))
        rowm.add_command(label=t("tdr_this", L), command=lambda: self._table_delete_row(mid, r))
        menu.add_cascade(label=t("ctx_row", L), menu=rowm)
        colm = tk.Menu(menu, tearoff=0, bg="#1e1e2e", fg="#e5e7eb",
                       activebackground="#5b8dee", font=("Malgun Gothic", 14))
        colm.add_command(label=t("tic_left", L), command=lambda: self._table_insert_col(mid, c))
        colm.add_command(label=t("tic_right", L), command=lambda: self._table_insert_col(mid, c + 1))
        colm.add_command(label=t("tdc_this", L), command=lambda: self._table_delete_col(mid, c))
        menu.add_cascade(label=t("ctx_col", L), menu=colm)
        menu.add_separator()
        # 셀 정렬 (선택 셀 대상)
        alm = tk.Menu(menu, tearoff=0, bg="#1e1e2e", fg="#e5e7eb",
                      activebackground="#5b8dee", font=("Malgun Gothic", 14))
        for av, lbl in (("l", t("al_left", L)), ("c", t("al_center", L)),
                        ("r", t("al_right", L))):
            alm.add_command(label=f"    {lbl}",
                            command=lambda v=av: self._ctx_cell_align(mid, v))
        menu.add_cascade(label=t("ctx_align", L), menu=alm)

        def _on_close(e=None):
            try:
                self.canvas.focus_set()
                if not self._grab_active:
                    self.overlay.grab_set(); self._grab_active = True
            except Exception:
                pass
        menu.bind("<Unmap>", lambda e: self.overlay.after(50, _on_close))
        try:
            self.overlay.grab_release(); self._grab_active = False
        except Exception:
            pass
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try: menu.grab_release()
            except Exception: pass
        return "break"

    def _apply_cell_bg(self, mid):
        memo, tbl = self._table_of(mid)
        if not tbl:
            return
        sel = self._tbl_sel.get(mid, set())
        if not sel:
            return
        # colorchooser: OS 네이티브 → 오버레이 위에 정상 표시
        try:
            rgb, hx = colorchooser.askcolor(parent=self.overlay, title=t("cell_bg_set", self.app.config.get("language","ko")))
        except Exception:
            hx = None
        if not hx:
            return
        self._push_undo("셀 배경색")
        cbg = tbl.setdefault("cell_bg", {})
        for (r, c) in sel:
            cbg[f"{r},{c}"] = hx
            ent = self._tbl_cells.get(mid, {}).get((r, c))
            if ent is not None:
                try: ent.config(bg=hx)
                except Exception: pass
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._refresh_cell_sel(mid)

    def _clear_cell_bg(self, mid):
        memo, tbl = self._table_of(mid)
        if not tbl:
            return
        sel = self._tbl_sel.get(mid, set())
        if not sel:
            return
        self._push_undo("셀 배경색 지우기")
        cbg = tbl.get("cell_bg") or {}
        for (r, c) in sel:
            cbg.pop(f"{r},{c}", None)
            ent = self._tbl_cells.get(mid, {}).get((r, c))
            if ent is not None:
                try: ent.config(bg="#ffffff")
                except Exception: pass
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._refresh_cell_sel(mid)

    def _apply_cell_fg(self, mid):
        memo, tbl = self._table_of(mid)
        if not tbl:
            return
        sel = self._tbl_sel.get(mid, set())
        if not sel:
            return
        try:
            _rgb, hx = colorchooser.askcolor(parent=self.overlay,
                       title=t("cell_fg_set", self.app.config.get("language","ko")))
        except Exception:
            hx = None
        if not hx:
            return
        self._push_undo("셀 글자색")
        cfg = tbl.setdefault("cell_fg", {})
        for (r, c) in sel:
            cfg[f"{r},{c}"] = hx
            ent = self._tbl_cells.get(mid, {}).get((r, c))
            if ent is not None:
                try: ent.config(fg=hx)
                except Exception: pass
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._refresh_cell_sel(mid)

    def _clear_cell_fg(self, mid):
        memo, tbl = self._table_of(mid)
        if not tbl:
            return
        sel = self._tbl_sel.get(mid, set())
        if not sel:
            return
        self._push_undo("셀 글자색 지우기")
        cfg = tbl.get("cell_fg") or {}
        base = resolve_text_color(memo.get("body_text_color"), "#1a1a1a")
        for (r, c) in sel:
            cfg.pop(f"{r},{c}", None)
            ent = self._tbl_cells.get(mid, {}).get((r, c))
            if ent is not None:
                try: ent.config(fg=base)
                except Exception: pass
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._refresh_cell_sel(mid)

    def _set_table_cell(self, mid: str, r: int, c: int, value: str):
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo or memo.get("kind") != "table":
            return
        cells = (memo.get("table") or {}).get("cells")
        if cells and 0 <= r < len(cells) and 0 <= c < len(cells[r]):
            cells[r][c] = value
            memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _insert_table(self):
        """표 삽입: 행×열 인라인 패널(canvas 위) → 표 메모 생성."""

    def _set_table_cell(self, mid: str, r: int, c: int, value: str):
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo or memo.get("kind") != "table":
            return
        cells = (memo.get("table") or {}).get("cells")
        if cells and 0 <= r < len(cells) and 0 <= c < len(cells[r]):
            cells[r][c] = value
            memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _insert_table(self):
        """표 삽입: 행×열 인라인 패널(canvas 위) → 표 메모 생성."""
        L = self.app.config.get("language", "ko")
        old = getattr(self, "_tbl_panel_id", None)
        if old is not None:
            try: self.canvas.delete(old)
            except Exception: pass
            self._tbl_panel_id = None

        panel = tk.Frame(self.canvas, bg="#1e1e2e",
                         highlightbackground="#5b8dee", highlightthickness=3)
        tk.Label(panel, text=t("tbl_prompt", L), bg="#1e1e2e", fg="#e5e7eb",
                 font=("Malgun Gothic", 12)).pack(padx=20, pady=(16, 8))
        row_in = tk.Frame(panel, bg="#1e1e2e"); row_in.pack(padx=20)
        tk.Label(row_in, text=t("tbl_rows", L), bg="#1e1e2e", fg="#e5e7eb",
                 font=("Malgun Gothic", 11)).grid(row=0, column=0, padx=4, pady=3, sticky="e")
        var_r = tk.StringVar(value="3")
        tk.Entry(row_in, textvariable=var_r, width=5, justify="center",
                 font=("Malgun Gothic", 14), bg="#2a2a3a", fg="#e5e7eb",
                 insertbackground="#e5e7eb", relief="flat").grid(row=0, column=1, padx=4, pady=3)
        tk.Label(row_in, text=t("tbl_cols", L), bg="#1e1e2e", fg="#e5e7eb",
                 font=("Malgun Gothic", 11)).grid(row=1, column=0, padx=4, pady=3, sticky="e")
        var_c = tk.StringVar(value="3")
        ent_c = tk.Entry(row_in, textvariable=var_c, width=5, justify="center",
                         font=("Malgun Gothic", 14), bg="#2a2a3a", fg="#e5e7eb",
                         insertbackground="#e5e7eb", relief="flat")
        ent_c.grid(row=1, column=1, padx=4, pady=3)

        def _close(*_):
            pid = getattr(self, "_tbl_panel_id", None)
            if pid is not None:
                try: self.canvas.delete(pid)
                except Exception: pass
            self._tbl_panel_id = None

        def _ok(*_):
            try:
                rr = max(1, min(TABLE_MAX_ROWS, int(var_r.get())))
                cc = max(1, min(TABLE_MAX_COLS, int(var_c.get())))
            except (ValueError, TypeError):
                return
            _close()
            self._add_new_memo(preset_title=t("tbl_title", L),
                               kind="table", table=new_table(rr, cc),
                               skip_title_edit=True)

        frm = tk.Frame(panel, bg="#1e1e2e"); frm.pack(pady=14)
        tk.Button(frm, text=t("btn_ok", L), width=8, command=_ok).pack(side="left", padx=5)
        tk.Button(frm, text=t("btn_cancel2", L), width=8, command=_close).pack(side="left", padx=5)
        ent_c.bind("<Return>", _ok)
        panel.bind("<Escape>", _close)

        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width()  or self.memo_w
        ch = self.canvas.winfo_height() or self.mh
        pid = self.canvas.create_window(cw // 2, ch // 2, window=panel, anchor="center")
        self._tbl_panel_id = pid
        self.canvas.tag_raise(pid)

    def _cal_weekdays(self):
        L = self.app.config.get("language", "ko")
        return [s.strip() for s in t("cal_weekdays", L).split(",")][:7]

    def _cal_title(self, y, m):
        L = self.app.config.get("language", "ko")
        return t("cal_title", L).format(y=y, m=m)

    def _insert_calendar(self):
        """달력 삽입: 현재 월 표 메모 생성(kind=table + calendar 메타)."""
        import datetime as _dt
        now = _dt.date.today()
        y, m = now.year, now.month
        tbl = build_calendar_table(y, m, self._cal_weekdays())
        self._add_new_memo(preset_title=self._cal_title(y, m),
                           kind="table", table=tbl,
                           cal_meta={"year": y, "month": m},
                           skip_title_edit=True)

    def _insert_image(self):
        """이미지 메모(폴라로이드) 삽입: 파일 선택 → 내부 복사 → kind=image."""
        L = self.app.config.get("language", "ko")
        from tkinter import filedialog as _fd
        # 이모지/파일 다이얼로그 위해 grab 해제
        try:
            self.overlay.grab_release(); self._grab_active = False
        except Exception:
            pass
        path = _fd.askopenfilename(
            parent=self.overlay, title=t("btn_image_insert", L),
            filetypes=[("Image", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("All", "*.*")])
        try:
            if not self._grab_active:
                self.overlay.grab_set(); self._grab_active = True
        except Exception:
            pass
        if not path:
            return
        dst = self._copy_image_internal(path)
        if not dst:
            return
        self._add_new_memo(preset_title=t("lbl_photo", L),
                           kind="image", image_path=dst, skip_title_edit=False)

    def _replace_image(self, mid):
        """이미지 메모 사진 교체(더블클릭)."""
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo or memo.get("kind") != "image":
            return
        L = self.app.config.get("language", "ko")
        from tkinter import filedialog as _fd
        try:
            self.overlay.grab_release(); self._grab_active = False
        except Exception:
            pass
        path = _fd.askopenfilename(
            parent=self.overlay, title=t("btn_image_insert", L),
            filetypes=[("Image", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("All", "*.*")])
        try:
            if not self._grab_active:
                self.overlay.grab_set(); self._grab_active = True
        except Exception:
            pass
        if not path:
            return
        dst = self._copy_image_internal(path)
        if not dst:
            return
        self._push_undo("이미지 교체")
        memo["image_path"] = dst
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _copy_image_internal(self, src: str):
        """이미지를 %LOCALAPPDATA%\\MuteAndSaver\\custom_bgs 로 내부 복사 → 경로 반환."""
        import shutil, os, uuid as _uuid
        from ...constants import CUSTOM_BGS_DIR
        try:
            CUSTOM_BGS_DIR.mkdir(parents=True, exist_ok=True)
            ext = os.path.splitext(src)[1].lower() or ".png"
            dst = CUSTOM_BGS_DIR / f"img_{_uuid.uuid4().hex[:12]}{ext}"
            shutil.copy2(src, dst)
            return str(dst)
        except Exception as e:
            LOG.error(f"[FSEditor] 이미지 복사 실패: {e}")
            return None

    def _calendar_shift(self, mid: str, delta: int):
        """달력 이전/다음 달. 범위 제한 없음(과거·미래 자유)."""
        memo = next((x for x in self._memos if x["id"] == mid), None)
        if not memo or not memo.get("calendar"):
            return
        cal = memo["calendar"]
        store = cal.setdefault("store", {})   # 월별 표 스냅샷 {"YYYY-MM": table}
        # 떠나는 달의 현재 표(셀색·입력 포함)를 보관
        oy, om = int(cal["year"]), int(cal["month"])
        store[f"{oy}-{om:02d}"] = memo.get("table")
        # 대상 달 계산
        y, m = oy, om + delta
        while m < 1:
            m += 12; y -= 1
        while m > 12:
            m -= 12; y += 1
        cal["year"], cal["month"] = y, m
        key = f"{y}-{m:02d}"
        # 저장된 달이면 복원, 없으면 신규 생성
        memo["table"] = store.get(key) or build_calendar_table(
            y, m, self._cal_weekdays())
        memo["title"] = self._cal_title(y, m)
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _rebuild_card(self, mid: str):
        """해당 카드만 동일 위치·크기로 destroy+재생성 (표 구조 변경 반영)."""
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        card = self._cards.get(mid)
        if card:
            try:
                coords = self.canvas.coords(card["item_id"])
                cx = int(coords[0]) if len(coords) >= 2 else 60
                cy = int(coords[1]) if len(coords) >= 2 else 60
            except Exception:
                cx, cy = 60, 60
            cw, ch = card["w"], card["h"]
            try:
                card["outer"].destroy()
                self.canvas.delete(card["item_id"])
                self.canvas.delete(f"shadow_{mid}")
                self.canvas.delete(f"border_{mid}")
            except Exception:
                pass
            del self._cards[mid]
        else:
            cx = int(memo.get("rel_x", 0.1) * self.memo_w)
            cy = int(memo.get("rel_y", 0.1) * self.canvas_h)
            cw = int(memo.get("rel_w", 0.2) * self.memo_w)
            ch = int(memo.get("rel_h", 0.2) * self.canvas_h)
        cw, ch = max(self.MIN_W, cw), max(self.MIN_H, ch)
        self._cards[mid] = {"w": cw, "h": ch}
        self._make_card(memo, mid, cx, cy, cw, ch)

    def _table_of(self, mid):
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo or memo.get("kind") != "table":
            return None, None
        return memo, (memo.get("table") or None)

    def _table_add_row(self, mid):
        memo, tbl = self._table_of(mid)
        if not tbl or tbl["rows"] >= TABLE_MAX_ROWS:
            return
        self._push_undo("행 추가")
        tbl["cells"].append(["" for _ in range(tbl["cols"])])
        tbl["rows"] += 1
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _table_del_row(self, mid):
        memo, tbl = self._table_of(mid)
        if not tbl or tbl["rows"] <= 1:
            return
        self._push_undo("행 삭제")
        tbl["cells"].pop()
        tbl["rows"] -= 1
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _table_add_col(self, mid):
        memo, tbl = self._table_of(mid)
        if not tbl or tbl["cols"] >= TABLE_MAX_COLS:
            return
        self._push_undo("열 추가")
        for row in tbl["cells"]:
            row.append("")
        tbl["cols"] += 1
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _table_del_col(self, mid):
        memo, tbl = self._table_of(mid)
        if not tbl or tbl["cols"] <= 1:
            return
        self._push_undo("열 삭제")
        for row in tbl["cells"]:
            if len(row) > 1:
                row.pop()
        tbl["cols"] -= 1
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _remap_cellmaps(self, tbl, axis, at, delta):
        """행/열 삽입·삭제 시 cell_bg/cell_fg/cell_align 인덱스 이동."""
        for kname in ("cell_bg", "cell_fg", "cell_align"):
            d = tbl.get(kname)
            if not d:
                continue
            new = {}
            for k, v in d.items():
                try:
                    r, c = map(int, k.split(","))
                except Exception:
                    continue
                if axis == "row":
                    if delta < 0 and r == at:
                        continue
                    nr = r + (1 if (delta > 0 and r >= at)
                              else (-1 if (delta < 0 and r > at) else 0))
                    nc = c
                else:
                    if delta < 0 and c == at:
                        continue
                    nc = c + (1 if (delta > 0 and c >= at)
                              else (-1 if (delta < 0 and c > at) else 0))
                    nr = r
                new[f"{nr},{nc}"] = v
            tbl[kname] = new

    def _table_insert_row(self, mid, at):
        memo, tbl = self._table_of(mid)
        if not tbl or tbl["rows"] >= TABLE_MAX_ROWS:
            return
        at = max(0, min(at, tbl["rows"]))
        self._push_undo("행 삽입")
        tbl["cells"].insert(at, ["" for _ in range(tbl["cols"])])
        tbl["rows"] += 1
        self._remap_cellmaps(tbl, "row", at, +1)
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _table_delete_row(self, mid, at):
        memo, tbl = self._table_of(mid)
        if not tbl or tbl["rows"] <= 1:
            return
        at = max(0, min(at, tbl["rows"] - 1))
        self._push_undo("행 삭제")
        tbl["cells"].pop(at)
        tbl["rows"] -= 1
        self._remap_cellmaps(tbl, "row", at, -1)
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _table_insert_col(self, mid, at):
        memo, tbl = self._table_of(mid)
        if not tbl or tbl["cols"] >= TABLE_MAX_COLS:
            return
        at = max(0, min(at, tbl["cols"]))
        self._push_undo("열 삽입")
        for row in tbl["cells"]:
            row.insert(at, "")
        tbl["cols"] += 1
        self._remap_cellmaps(tbl, "col", at, +1)
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _table_delete_col(self, mid, at):
        memo, tbl = self._table_of(mid)
        if not tbl or tbl["cols"] <= 1:
            return
        at = max(0, min(at, tbl["cols"] - 1))
        self._push_undo("열 삭제")
        for row in tbl["cells"]:
            if 0 <= at < len(row):
                row.pop(at)
        tbl["cols"] -= 1
        self._remap_cellmaps(tbl, "col", at, -1)
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._rebuild_card(mid)

    def _input_font_size(self, mid: str, key: str):
        """제목/본문 글자 크기 직접 입력 (6~200pt). 캔버스 위 인라인 패널.
        ⚠️ config 접근은 self.app.config (FSEditor엔 self.config 없음)."""
        L = self.app.config.get("language", "ko")
        memo = next((m for m in self._memos if m["id"] == mid), None)
        cur  = memo.get(key, 11) if memo else 11

        old = getattr(self, "_size_panel_id", None)
        if old is not None:
            try: self.canvas.delete(old)
            except Exception: pass
            self._size_panel_id = None

        panel = tk.Frame(self.canvas, bg="#1e1e2e",
                         highlightbackground="#5b8dee", highlightthickness=3)
        tk.Label(panel, text=t("ctx_size_prompt", L), bg="#1e1e2e", fg="#e5e7eb",
                 font=("Malgun Gothic", 12)).pack(padx=20, pady=(16, 8))
        var = tk.StringVar(value=str(cur))
        ent = tk.Entry(panel, textvariable=var, width=8, justify="center",
                       font=("Malgun Gothic", 16), bg="#2a2a3a", fg="#e5e7eb",
                       insertbackground="#e5e7eb", relief="flat")
        ent.pack(ipady=4, padx=20)

        def _close(*_):
            pid = getattr(self, "_size_panel_id", None)
            if pid is not None:
                try: self.canvas.delete(pid)
                except Exception: pass
            self._size_panel_id = None

        def _apply(*_):
            try:
                v = max(6, min(200, int(var.get())))
            except (ValueError, TypeError):
                return
            _close()
            self._update_style(mid, key, v)

        frm = tk.Frame(panel, bg="#1e1e2e")
        frm.pack(pady=16, padx=20)
        tk.Button(frm, text=t("btn_ok", L), width=8, command=_apply).pack(side="left", padx=5)
        tk.Button(frm, text=t("btn_cancel2", L), width=8, command=_close).pack(side="left", padx=5)
        ent.bind("<Return>", _apply)
        ent.bind("<Escape>", _close)

        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width()  or self.mw
        ch = self.canvas.winfo_height() or self.mh
        pid = self.canvas.create_window(cw // 2, ch // 2, window=panel, anchor="center")
        self._size_panel_id = pid
        self.canvas.tag_raise(pid)
        ent.focus_force()
        ent.select_range(0, "end")

    def _update_style(self, mid: str, key: str, value):
        """스타일 변경 → 해당 카드만 destroy + 재생성 (성능 최적화)."""
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        # ⚠️ 편집 중 카드면 Text 내용 선반영 후 재생성 — 스타일 변경 시 입력 유실 방지
        # (카드 destroy→재생성 전에 미저장 본문을 memo["body"]로 커밋)
        if self._edit_mid == mid:
            _c = self._cards.get(mid)
            _t = _c.get("txt_body") if _c else None
            if _t is not None:
                try:
                    if _t.winfo_exists():
                        memo["body"] = _t.get("1.0", "end-1c")
                except Exception:
                    pass
            self._edit_mid = None   # 재생성 후 카드는 표시모드 → 편집상태 정리(불일치 방지)
        self._push_undo(f"스타일 변경({key})")
        memo[key]          = value
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        card = self._cards.get(mid)
        if card:
            try:
                coords = self.canvas.coords(card["item_id"])
                cx = int(coords[0]) if len(coords) >= 2 else 60
                cy = int(coords[1]) if len(coords) >= 2 else 60
            except Exception:
                cx, cy = 60, 60
            cw, ch = card["w"], card["h"]
            try:
                card["outer"].destroy()
                self.canvas.delete(card["item_id"])
                self.canvas.delete(f"shadow_{mid}")   # 그림자 잔상 방지
                self.canvas.delete(f"border_{mid}")
                self.canvas.delete(f"inactive_{mid}")
            except Exception:
                pass
            del self._cards[mid]
        else:
            cx = int(memo.get("rel_x", 0.1) * self.memo_w)
            cy = int(memo.get("rel_y", 0.1) * self.canvas_h)
            cw = int(memo.get("rel_w", 0.2) * self.memo_w)
            ch = int(memo.get("rel_h", 0.2) * self.canvas_h)

        cw, ch = max(self.MIN_W, cw), max(self.MIN_H, ch)
        self._cards[mid] = {"w": cw, "h": ch}
        try:
            self._make_card(memo, mid, cx, cy, cw, ch)
        except Exception as e:
            # 재생성 실패 시 스텁(빈 카드) 남아 '사라짐' 방지 → 전체 재렌더로 복구
            import traceback as _tb
            LOG.error(f"[FSEditor] _update_style 재생성 실패 {mid}: {e}\n{_tb.format_exc()}")
            self._cards.pop(mid, None)
            self._render_all_fs()
            return
        # 카드 재생성 → 선택 테두리·리본 값 복원
        if mid in self._selected:
            self._set_card_border(mid, selected=True)
        self._sync_ribbon()

    # ══ 전체 재렌더 (FSEditor 전용) ══════════════════

    def _render_all_fs(self):
        """핀/z_order 변경 등 전체 재렌더 필요 시 호출."""
        L = self.app.config.get("language", "ko")
        if self._edit_mid:
            self._exit_edit_mode(self._edit_mid)
        self._clear_selection()   # 재렌더 시 선택 상태 초기화
        for card in self._cards.values():
            try:
                card["outer"].destroy()
            except Exception:
                pass
        self._cards.clear()
        self.canvas.delete("all")
        # 배경 재렌더링 (delete("all")로 bg_layer 소실 복구)
        _render_canvas_bg(self.canvas, self.memo_w, self.canvas_h,
                          getattr(self, '_current_theme', MEMO_BG_THEMES.get("paper", {})))
        self.canvas.create_text(
            self.memo_w // 2, 24,
            text=t("lbl_drag_guide2", L),
            fill="#444444", font=("Malgun Gothic", 10), tags="guide"
        )
        self._place_cards()

    # ══ 삭제 ════════════════════════════════════════

    def _export_one_memo_txt(self, mid: str):
        """단일 메모를 txt로 저장 (우클릭 메뉴). utf-8-sig. 덮어쓰기 확인은 OS 저장 다이얼로그가 처리."""
        L = self.app.config.get("language", "ko")
        import re as _re
        from tkinter import filedialog as _fd

        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        title = (memo.get("title") or "").strip() or t("lbl_untitled", L)
        body  = memo.get("body", "")
        # 파일시스템 금지문자 제거 + 길이 제한(50)
        safe = _re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip()[:50] or "memo"

        fpath = _fd.asksaveasfilename(
            title=t("btn_export_txt", L),
            defaultextension=".txt",
            initialfile=f"{safe}.txt",
            filetypes=[("Text", "*.txt")],
            parent=self.overlay
        )
        if not fpath:
            self.canvas.focus_set()
            return
        try:
            with open(fpath, "w", encoding="utf-8-sig") as f:
                f.write(f"{title}\n\n{body}")
            LOG.info(f"[Export] 단일 메모 저장: {fpath}")
        except Exception as e:
            messagebox.showerror(t("msg_error", L), str(e), parent=self.overlay)
            LOG.warning(f"[Export] 단일 메모 저장 실패: {e}")
        self.canvas.focus_set()

    def _delete_memo_fs(self, mid: str):
        """삭제 확인 → 카드 즉시 제거. parent=overlay 필수."""
        L = self.app.config.get("language", "ko")
        memo  = next((m for m in self._memos if m["id"] == mid), None)
        title = memo.get("title", "메모")[:20] if memo else "메모"
        try:
            if not tk.messagebox.askyesno(
                t("fs_delete_title", L),
                t("fs_delete_msg", L).format(title=title),
                parent=self.overlay
            ):
                self.canvas.focus_set()
                return
        except Exception:
            return

        self._push_undo("삭제")
        self._memos = [m for m in self._memos if m["id"] != mid]
        card = self._cards.pop(mid, None)
        if card:
            try:
                card["outer"].destroy()
                self.canvas.delete(card["item_id"])
                self.canvas.delete(f"shadow_{mid}")
                self.canvas.delete(f"border_{mid}")
                self.canvas.delete(f"inactive_{mid}")
            except Exception:
                pass
        if self._edit_mid == mid:
            self._edit_mid = None
            self._set_mode_label("🖱️ 드래그 모드", "#34d399")
        self.canvas.focus_set()

    # ══ 키보드: Delete 삭제 / Insert 즐겨찾기 생성 ════════
    def _typing_focus(self) -> bool:
        """현재 포커스가 입력 위젯(Entry/Text)인지 — 표 셀·본문 편집 중 단축키 차단."""
        try:
            w = self.overlay.focus_get()
        except Exception:
            w = None
        return isinstance(w, (tk.Entry, tk.Text))

    def _on_delete_key(self, event=None):
        """Delete: 선택 메모 삭제(1회 확인). 편집/입력 중엔 무시."""
        if self._edit_mid or self._typing_focus():
            return
        if not self._selected:
            return
        L = self.app.config.get("language", "ko")
        targets = list(self._selected)
        try:
            if not tk.messagebox.askyesno(
                t("fs_delete_title", L),
                t("fs_delete_sel_msg", L).format(n=len(targets)),
                parent=self.overlay):
                self.canvas.focus_set()
                return
        except Exception:
            return
        self._push_undo("삭제")
        ids = set(targets)
        self._memos = [m for m in self._memos if m["id"] not in ids]
        for mid in targets:
            card = self._cards.pop(mid, None)
            if card:
                try:
                    card["outer"].destroy()
                    self.canvas.delete(card["item_id"])
                    self.canvas.delete(f"shadow_{mid}")
                    self.canvas.delete(f"border_{mid}")
                    self.canvas.delete(f"inactive_{mid}")
                except Exception:
                    pass
            if self._edit_mid == mid:
                self._edit_mid = None
        self._selected.clear()
        self._sync_ribbon()
        self.canvas.focus_set()
        return "break"

    def _on_insert_key(self, event=None):
        """Insert: 즐겨찾기 양식 메모 즉시 생성. 편집/입력 중엔 무시."""
        if self._edit_mid or self._typing_focus():
            return
        self._run_favorite()
        return "break"

    # ══ 접기/핀 토글 ════════════════════════════════

    def _toggle_collapse_fs(self, mid: str):
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        memo["collapsed"]  = not memo.get("collapsed", False)
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._update_style(mid, "collapsed", memo["collapsed"])

    def _reset_memo_position(self, mid: str):
        """
        개별 메모를 메모 영역 중앙으로 이동 + rel_* 재계산.
        우클릭 → [📍 위치 초기화 (중앙 배치)] 에서 호출.
        Undo 스냅샷 포함.
        """
        L = self.app.config.get("language", "ko")
        memo = next((m for m in self._memos if m["id"] == mid), None)
        card = self._cards.get(mid)
        if not memo or not card:
            return

        self._push_undo(t("fs_reset_pos", L))

        # 중앙 좌표 계산 + 경계 클램핑
        cx = max(0, min(self.memo_w  - card["w"],
                        (self.memo_w  - card["w"]) // 2))
        cy = max(0, min(self.canvas_h - card["h"],
                        (self.canvas_h - card["h"]) // 2))

        # Canvas 위치 이동
        try:
            self.canvas.coords(card["item_id"], cx, cy)
            # 그림자 + 테두리도 함께 이동
            cw, ch = card["w"], card["h"]
            self.canvas.coords(f"shadow_{mid}", cx+3, cy+3, cx+cw+3, cy+ch+3)
            self.canvas.coords(f"border_{mid}", cx-1, cy-1, cx+cw+1, cy+ch+1)
        except Exception:
            pass

        # rel_* 재계산 + 메타데이터 갱신
        memo["x"], memo["y"] = cx, cy
        memo.update(_abs_to_rel(cx, cy, card["w"], card["h"],
                                 self.memo_w, self.canvas_h))
        memo["_saved_canvas_w"]    = self.memo_w
        memo["_saved_canvas_h"]    = self.canvas_h
        memo["_saved_split_ratio"] = self.app.config.get("split_ratio", 0.65)
        memo["updated_at"]         = time.strftime("%Y-%m-%dT%H:%M:%S")

    def _reset_all_positions(self):
        """
        모든 메모를 격자(Grid) 형태로 자동 재배열.
        툴바 [⚙ 전체 재배열] 에서 호출.
        3열 격자, 좌상단부터 채워나가며 경계 초과 시 다음 줄로.
        rel_* 범위 초과(화면 밖) 메모도 강제 복구.
        Undo 스냅샷 포함.
        """
        L = self.app.config.get("language", "ko")
        is_premium = self.app.config.get("is_premium", False)
        visible    = _get_visible_memos(self._memos, is_premium)
        if not visible:
            return

        try:
            if not tk.messagebox.askyesno(
                t("fs_rearrange", L),
                t("fs_rearrange_msg", L).format(n=len(visible)),
                parent=self.overlay
            ):
                return
        except Exception:
            return

        self._push_undo(t("fs_rearrange", L))

        # 격자 파라미터
        COLS  = 3
        PAD_X = 16
        PAD_Y = 16
        # 열 너비: 메모 영역 3등분 - 여백
        col_w = max(self.MIN_W, (self.memo_w  - PAD_X * (COLS + 1)) // COLS)
        row_h = max(self.MIN_H, int(self.canvas_h * 0.28))

        try:
            self.canvas.update_idletasks()
            real_cw = self.canvas.winfo_width()
            real_ch = self.canvas.winfo_height()
        except Exception:
            real_cw, real_ch = 1, 1
        memo_w   = real_cw  if real_cw  > 10 else self.memo_w
        canvas_h = real_ch  if real_ch  > 10 else self.canvas_h

        for idx, memo in enumerate(visible):
            mid  = memo["id"]
            col  = idx % COLS
            row  = idx // COLS
            nx   = PAD_X + col * (col_w + PAD_X)
            ny   = PAD_Y + row * (row_h + PAD_Y)

            # 경계 클램핑 (canvas_h 초과 시에도 마지막 줄에 맞춤)
            nx = max(0, min(memo_w   - self.MIN_W, nx))
            ny = max(0, min(canvas_h - self.MIN_H, ny))

            card = self._cards.get(mid)
            if card:
                cw = min(card["w"], col_w)
                ch = min(card["h"], row_h)
                try:
                    card["outer"].config(width=cw, height=ch)
                    card["w"], card["h"] = cw, ch
                    self.canvas.coords(card["item_id"], nx, ny)
                    self.canvas.coords(f"shadow_{mid}",
                                       nx+3, ny+3, nx+cw+3, ny+ch+3)
                    self.canvas.coords(f"border_{mid}",
                                       nx-1, ny-1, nx+cw+1, ny+ch+1)
                except Exception:
                    pass

            # rel_* 재계산
            memo["x"], memo["y"] = nx, ny
            memo["width"]  = card["w"] if card else self.MIN_W
            memo["height"] = card["h"] if card else self.MIN_H
            memo.update(_abs_to_rel(nx, ny,
                                     memo["width"], memo["height"],
                                     memo_w, canvas_h))
            memo["_saved_canvas_w"]    = memo_w
            memo["_saved_canvas_h"]    = canvas_h
            memo["_saved_split_ratio"] = self.app.config.get("split_ratio", 0.65)
            memo["updated_at"]         = time.strftime("%Y-%m-%dT%H:%M:%S")
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        memo["pinned"]     = not memo.get("pinned", False)
        memo["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._render_all_fs()   # z_order 재정렬

    # ══ Z-order (앞으로/뒤로) ════════════════════════
    def _restack_all(self):
        """z_order 오름차순 재적층. ⚠️ 캔버스 임베드 윈도우는 tag_raise로 실시간
        재적층 안 됨(Tk 제약) → 위젯 outer.lift()로 스택 변경. shadow/border(캔버스
        사각형)는 tag_raise 병행. bg 이미지는 Tk상 임베드 윈도우보다 항상 아래."""
        def _z(mid):
            m = next((x for x in self._memos if x["id"] == mid), None)
            return m.get("z_order", 0) if m else 0
        for mid in sorted(self._cards.keys(), key=_z):   # 낮은 z 먼저 → 높은 z가 최상단
            card = self._cards.get(mid)
            if not card:
                continue
            try:
                self.canvas.tag_raise(f"shadow_{mid}")
                self.canvas.tag_raise(f"border_{mid}")
            except Exception:
                pass
            outer = card.get("outer")
            if outer is not None:
                try:
                    outer.lift()   # 임베드 윈도우 실제 스택 변경(핵심)
                except Exception:
                    pass

    def _raise_to_front(self, mid: str):
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        zmax = max((m.get("z_order", 0) for m in self._memos), default=0)
        memo["z_order"] = zmax + 1
        self._restack_all()

    def _send_to_back(self, mid: str):
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        zmin = min((m.get("z_order", 0) for m in self._memos), default=0)
        memo["z_order"] = zmin - 1
        self._restack_all()

    # ── 리본: 레이어(맨앞/맨뒤) + TXT 내보내기 ──────
    def _rb_raise_front(self):
        if self._rb_mid:
            self._raise_to_front(self._rb_mid)

    def _rb_send_back(self):
        if self._rb_mid:
            self._send_to_back(self._rb_mid)

    def _rb_export_txt(self):
        """선택 메모를 .txt로 내보내기 (제목 + 본문/표 탭구분)."""
        L = self.app.config.get("language", "ko")
        mid = self._rb_mid
        memo = next((m for m in self._memos if m["id"] == mid), None) if mid else None
        if not memo:
            messagebox.showinfo(t("rb_export_txt", L), t("msg_no_memo", L),
                                parent=self.overlay)
            return
        title = (memo.get("title", "") or "memo")
        safe = "".join(c for c in title if c not in '\\/:*?"<>|').strip() or "memo"
        fpath = filedialog.asksaveasfilename(
            title=t("rb_export_txt", L), defaultextension=".txt",
            initialfile=f"{safe}.txt", filetypes=[("Text", "*.txt")],
            parent=self.overlay)
        if not fpath:
            return
        out = ["# " + (memo.get("title", "") or "")]
        if memo.get("kind") == "table":
            tbl = memo.get("table") or {}
            for row in (tbl.get("cells") or []):
                out.append("\t".join(str(c) for c in row))
        else:
            out.append(memo.get("body", "") or "")
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            messagebox.showinfo(t("rb_export_txt", L), t("msg_txt_saved", L),
                                parent=self.overlay)
        except Exception as e:
            LOG.error(f"[Export TXT] 실패: {e}")
            messagebox.showerror(t("rb_export_txt", L), str(e), parent=self.overlay)

    def _rb_import_txt(self):
        """.txt 파일을 새 메모로 불러오기 (제목=파일명, 본문=내용). 한도는 _add_new_memo가 처리."""
        import os as _os
        L = self.app.config.get("language", "ko")
        fpath = filedialog.askopenfilename(
            title=t("rb_import_txt", L),
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
            parent=self.overlay)
        if not fpath:
            return
        content = None
        for _enc in ("utf-8", "utf-8-sig", "cp949"):   # 한글 Windows txt 호환
            try:
                with open(fpath, "r", encoding=_enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
            except Exception as e:
                LOG.error(f"[Import TXT] 실패: {e}")
                messagebox.showerror(t("rb_import_txt", L), str(e), parent=self.overlay)
                return
        if content is None:
            messagebox.showerror(t("rb_import_txt", L), t("msg_txt_read_fail", L),
                                 parent=self.overlay)
            return
        name = _os.path.splitext(_os.path.basename(fpath))[0] or "메모"
        self._add_new_memo(preset_title=name, preset_body=content)

    # ══ 우클릭 컨텍스트 메뉴 ════════════════════════

    def _bind_context_recursive(self, widget, mid: str,
                                 exclude_tags: set = None):
        """우클릭 이벤트 재귀 바인딩."""
        if exclude_tags and getattr(widget, '_fs_tag', None) in exclude_tags:
            return
        widget.bind("<Button-3>",
                    lambda e, m=mid: self._show_context_menu(e, m))
        for child in widget.winfo_children():
            self._bind_context_recursive(child, mid, exclude_tags)

    def _show_context_menu(self, event, mid: str):
        """
        카드 우클릭 → 글꼴/크기/색상/접기/핀/삭제 컨텍스트 메뉴.
        다크 테마: bg="#1e1e2e", fg="#e5e7eb" (보안 도구 룩).
        메뉴 닫힌 후 grab + focus 복귀 보장.
        lambda 클로저 변수 캡처: `lambda v=val: ...` 패턴 사용.
        """
        L = self.app.config.get("language", "ko")
        memo = next((m for m in self._memos if m["id"] == mid), None)
        if not memo:
            return
        if self._edit_mid:
            self._exit_edit_mode(self._edit_mid)

        MBG = "#1e1e2e"; MFG = "#e5e7eb"; MACT = "#5b8dee"

        def mk(parent=None):
            return tk.Menu(parent or self.overlay, tearoff=0,
                           bg=MBG, fg=MFG,
                           activebackground=MACT, activeforeground="white",
                           relief="flat", bd=1,
                           font=("Malgun Gothic", 14))   # 우클릭 메뉴 가독성: 14pt

        menu = mk()

        # 순서: 맨 앞으로 / 맨 뒤로
        menu.add_command(label=t("ctx_to_front", L),
                         command=lambda m=mid: self._raise_to_front(m))
        menu.add_command(label=t("ctx_to_back", L),
                         command=lambda m=mid: self._send_to_back(m))
        menu.add_separator()

        # 표 메모: 행/열 추가·삭제
        if memo.get("kind") == "table":
            tblm = mk(menu)
            tblm.add_command(label=t("tbl_add_row", L), command=lambda m=mid: self._table_add_row(m))
            tblm.add_command(label=t("tbl_del_row", L), command=lambda m=mid: self._table_del_row(m))
            tblm.add_separator()
            tblm.add_command(label=t("tbl_add_col", L), command=lambda m=mid: self._table_add_col(m))
            tblm.add_command(label=t("tbl_del_col", L), command=lambda m=mid: self._table_del_col(m))
            menu.add_cascade(label=t("ctx_table", L), menu=tblm)
            menu.add_separator()

        # ── 서식 4분류: 메모 테마색 / 글꼴 / 글자 크기 / 글자색 ──

        # 1) 메모 테마색 (프리셋 + 저장색 + 직접 선택/삭제)
        cm = mk(menu)
        for ck, cl in [
            ("purple",t("thm_purple", L)),   # 자수정
            ("teal",t("thm_cyan", L)),       # 투어마린
            ("blue",t("thm_blue", L)),       # 사파이어
            ("amber",t("thm_gold", L)),      # 시트린
            ("pink",t("thm_pink", L)),       # 루비
            ("white",t("thm_white", L)),     # 진주
        ]:
            cur = "✔ " if memo.get("color_key") == ck else "    "
            cm.add_command(label=f"{cur}{cl}",
                           command=lambda v=ck: self._update_style(mid,"color_key",v))
        customs = self.app.config.get("custom_memo_colors", []) or []
        if customs:
            cm.add_separator()
            for hx in customs:
                cur = "✔ " if memo.get("color_key") == hx else "    "
                cm.add_command(label=f"{cur}🎨 {hx}",
                               command=lambda v=hx: self._update_style(mid,"color_key",v))
        cm.add_separator()
        cm.add_command(label=t("ctx_pick_color", L),
                       command=lambda: self._pick_custom_color(mid))
        if customs:
            delm = mk(cm)
            for hx in customs:
                delm.add_command(label=f"🗑 {hx}",
                                 command=lambda v=hx: self._del_custom_color(v, mid))
            cm.add_cascade(label=t("ctx_del_custom", L), menu=delm)
        menu.add_cascade(label=t("ctx_theme_color", L), menu=cm)

        # 2) 글꼴 (기본 + 저장 시스템 글꼴 + 직접 선택/삭제)
        fm = mk(menu)
        for fn in self._BASE_FONTS:
            cur = "✔ " if memo.get("font_family") == fn else "    "
            fm.add_command(label=f"{cur}{fn}",
                           command=lambda v=fn: self._update_style(mid,"font_family",v))
        cust_fonts = self.app.config.get("custom_memo_fonts", []) or []
        if cust_fonts:
            fm.add_separator()
            for fn in cust_fonts:
                cur = "✔ " if memo.get("font_family") == fn else "    "
                fm.add_command(label=f"{cur}🔤 {fn}",
                               command=lambda v=fn: self._update_style(mid,"font_family",v))
        fm.add_separator()
        fm.add_command(label=t("ctx_sys_font", L),
                       command=lambda: self._pick_system_font(mid))
        if cust_fonts:
            delfm = mk(fm)
            for fn in cust_fonts:
                delfm.add_command(label=f"🗑 {fn}",
                                  command=lambda v=fn: self._del_custom_font(v, mid))
            fm.add_cascade(label=t("ctx_del_font", L), menu=delfm)
        menu.add_cascade(label=t("ctx_font", L), menu=fm)

        # 3) 글자 크기 (제목/본문 하위)
        szm = mk(menu)
        tfm = mk(szm)
        for s in [18,24,32]:
            cur = "✔ " if memo.get("title_font_size") == s else "    "
            tfm.add_command(label=f"{cur}{s}pt",
                            command=lambda v=s: self._update_style(mid,"title_font_size",v))
        tfm.add_separator()
        tfm.add_command(label=t("ctx_size_input", L),
                        command=lambda: self._input_font_size(mid, "title_font_size"))
        szm.add_cascade(label=t("rb_title_size", L), menu=tfm)
        bfm = mk(szm)
        for s in [14,18,24]:
            cur = "✔ " if memo.get("body_font_size") == s else "    "
            bfm.add_command(label=f"{cur}{s}pt",
                            command=lambda v=s: self._update_style(mid,"body_font_size",v))
        bfm.add_separator()
        bfm.add_command(label=t("ctx_size_input", L),
                        command=lambda: self._input_font_size(mid, "body_font_size"))
        szm.add_cascade(label=t("rb_body_size", L), menu=bfm)
        menu.add_cascade(label=t("ctx_text_size", L), menu=szm)

        # 4) 글자색 (제목/본문 하위)
        _tcolors = [
            ("white", t("clr_white", L)), ("black", t("clr_black", L)),
            ("red",   t("clr_red", L)),   ("blue",  t("clr_blue", L)),
            ("yellow",t("clr_yellow", L)),
        ]
        colm = mk(menu)
        tcm = mk(colm)
        for ck, cl in _tcolors:
            cur = "✔ " if memo.get("title_text_color") == ck else "    "
            tcm.add_command(label=f"{cur}{cl}",
                            command=lambda v=ck: self._update_style(mid,"title_text_color",v))
        tcm.add_separator()
        tcm.add_command(label=t("ctx_pick_color", L),
                        command=lambda: self._pick_text_color(mid, "title_text_color"))
        colm.add_cascade(label=t("rb_title_size", L), menu=tcm)
        bcm = mk(colm)
        for ck, cl in _tcolors:
            cur = "✔ " if memo.get("body_text_color") == ck else "    "
            bcm.add_command(label=f"{cur}{cl}",
                            command=lambda v=ck: self._update_style(mid,"body_text_color",v))
        bcm.add_separator()
        bcm.add_command(label=t("ctx_pick_color", L),
                        command=lambda: self._pick_text_color(mid, "body_text_color"))
        colm.add_cascade(label=t("rb_body_size", L), menu=bcm)
        menu.add_cascade(label=t("ctx_text_color", L), menu=colm)

        # 5) 정렬 ▸ 제목 / 본문
        algm = mk(menu)
        # 제목
        tam = mk(algm)
        for av, lbl in (("l", t("al_left", L)), ("c", t("al_center", L)),
                        ("r", t("al_right", L))):
            cur = "✔ " if memo.get("title_align", "l") == av else "    "
            tam.add_command(label=f"{cur}{lbl}",
                            command=lambda v=av: self._update_style(mid, "title_align", v))
        algm.add_cascade(label=t("rb_title_size", L), menu=tam)
        # 본문(일반) 또는 셀(표)
        if memo.get("kind") == "table":
            cam = mk(algm)
            for av, lbl in (("l", t("al_left", L)), ("c", t("al_center", L)),
                            ("r", t("al_right", L))):
                cam.add_command(label=f"    {lbl}",
                                command=lambda v=av: self._ctx_cell_align(mid, v))
            algm.add_cascade(label=t("ctx_cell", L), menu=cam)
        else:
            bam = mk(algm)
            for av, lbl in (("l", t("al_left", L)), ("c", t("al_center", L)),
                            ("r", t("al_right", L))):
                cur = "✔ " if memo.get("body_align", "l") == av else "    "
                bam.add_command(label=f"{cur}{lbl}",
                                command=lambda v=av: self._ctx_body_align(mid, v))
            algm.add_cascade(label=t("rb_body_size", L), menu=bam)
        menu.add_cascade(label=t("ctx_align", L), menu=algm)

        menu.add_separator()
        menu.add_command(
            label=t("ctx_expand", L) if memo.get("collapsed") else t("ctx_collapse", L),
            command=lambda: self._toggle_collapse_fs(mid))
        menu.add_command(
            label=t("ctx_unpin", L) if memo.get("pinned") else t("ctx_pin", L),
            command=lambda: self._toggle_pin_fs(mid))

        # 투명도 (Pre-blended 3단계 — PIL/alpha 불필요, 드래그 중 재계산 없음)
        opm = mk(menu)
        for op, lbl in [(1.0,t("clr_default", L)),(0.7,"🔷 70%"),(0.4,"🔹 40%")]:
            cur = "✔ " if abs(memo.get("opacity", 1.0) - op) < 0.05 else "    "
            opm.add_command(
                label=f"{cur}{lbl}",
                command=lambda v=op: self._update_style(mid, "opacity", v)
            )
        menu.add_cascade(label=t("ctx_opacity", L), menu=opm)

        menu.add_separator()
        menu.add_command(label=t("ctx_reset_pos", L),
                         command=lambda: self._reset_memo_position(mid))
        menu.add_command(label=t("btn_export_txt", L),
                         command=lambda: self._export_one_memo_txt(mid))
        menu.add_command(label=t("ctx_delete", L), foreground="#f87171",
                         command=lambda: self._delete_memo_fs(mid))

        # 메뉴 닫힌 후 grab + focus 복귀
        def _on_close(e=None):
            try:
                self.canvas.focus_set()
                if not self._grab_active:
                    self.overlay.grab_set()
                    self._grab_active = True
            except Exception:
                pass
        menu.bind("<Unmap>", lambda e: self.overlay.after(50, _on_close))

        # ⚡ 우클릭 지연 완화: overlay 모달 grab을 먼저 해제 → tk_popup이 즉시 grab 획득
        #   (grab 경합 제거). 메뉴 닫힌 후 _on_close가 overlay grab 재설정.
        try:
            self.overlay.grab_release()
            self._grab_active = False
        except Exception:
            pass

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
