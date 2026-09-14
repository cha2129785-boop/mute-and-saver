# -*- coding: utf-8 -*-
"""
settings_tab — 설정 탭
⚠️ Mixin — ScreesaverApp에 다중상속됨. self 속성은 App.__init__에 정의.
"""
import logging
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

LOG = logging.getLogger("MuteAndSaver")

from ...i18n import t
from ...constants import (
    APP_VERSION, APP_DISPLAY, PRESETS,
    MEMO_BG_THEMES, CUSTOM_BGS_DIR, THUMBS_DIR,
    UI_LF_PADDING, UI_PAD_SEC, UI_PAD_SEP,
)
from ...persistence import (
    load_config, save_config, load_favorites, save_favorites,
    load_memos, save_memos, load_user_themes, save_user_themes, get_all_themes,
)
from ...services import verify_pin, set_pin, clear_pin, _verify_admin, _verify_license, _generate_activation_code, _get_hardware_id
from ...platform.windows.monitor import _get_monitors_info


class SettingsTabMixin:
    def _build_tab_setting(self):
        outer = self.tab_setting
        L = self.config.get("language", "ko")
        for w in outer.winfo_children():
            w.destroy()

        # 세로 스크롤 래퍼 — 폰트 확대로 내용이 길어도 하단(잠금 메시지 등)이 잘리지 않도록
        _canvas = tk.Canvas(outer, highlightthickness=0)
        _vsb = ttk.Scrollbar(outer, orient="vertical", command=_canvas.yview)
        _canvas.configure(yscrollcommand=_vsb.set)
        _vsb.pack(side="right", fill="y")
        _canvas.pack(side="left", fill="both", expand=True)
        parent = tk.Frame(_canvas)
        _win = _canvas.create_window((0, 0), window=parent, anchor="nw")
        # ⚠️ 재진입 방어: 폭 동기화↔스크롤영역 갱신이 <Configure>를 되쏘아 스택 오버플로로
        #  이어지는 경우 차단(리사이즈 크래시 가설 대응). 재진입 발생 시 1회 진단 로그.
        def _cfg_guard(fn, e):
            if getattr(self, "_st_cfg_busy", False):
                if not getattr(self, "_st_cfg_warned", False):
                    self._st_cfg_warned = True
                    LOG.warning("[Diag] 설정탭 <Configure> 재진입 차단 — 리사이즈 재귀 확인")
                return
            self._st_cfg_busy = True
            try:
                fn(e)
            except Exception as _ex:
                # 0xc000041d 방지: 리사이즈 콜백 예외가 커널 경계로 탈출하면 프로세스 강제종료됨
                if not getattr(self, "_st_cfg_exc_logged", False):
                    self._st_cfg_exc_logged = True
                    LOG.warning(f"[Diag] 설정탭 <Configure> 예외 격리: {type(_ex).__name__}: {_ex}")
            finally:
                self._st_cfg_busy = False
        def _on_inner_cfg(ev):
            _canvas.configure(scrollregion=_canvas.bbox("all"))
            self._update_settings_scrollbar()
        def _on_canvas_cfg(ev):
            _canvas.itemconfig(_win, width=ev.width)
            self._update_settings_scrollbar()
        parent.bind("<Configure>", lambda e: _cfg_guard(_on_inner_cfg, e))
        _canvas.bind("<Configure>", lambda e: _cfg_guard(_on_canvas_cfg, e))
        # 휠 스크롤 (포인터가 설정 탭 위일 때만 활성)
        def _wheel(e):
            _canvas.yview_scroll(int(-e.delta / 120), "units")
        _canvas.bind("<Enter>", lambda e: _canvas.bind_all("<MouseWheel>", _wheel))
        _canvas.bind("<Leave>", lambda e: _canvas.unbind_all("<MouseWheel>"))
        self._setting_canvas = _canvas
        self._setting_inner  = parent
        self._setting_vsb    = _vsb
        self._setting_vsb_mapped = True   # 최초 pack 상태

        # ── 설정 프리셋 (Stage C: 카드형 A안) ────────
        frm_preset = ttk.LabelFrame(parent, text=t("frm_preset", L), padding=UI_LF_PADDING)
        frm_preset.pack(fill="x", pady=UI_PAD_SEC)

        self.preset_frm = tk.Frame(frm_preset)
        self.preset_frm.pack(fill="x", pady=(0, 4))
        self._build_preset_cards()

        frm_preset_btn = tk.Frame(frm_preset)
        frm_preset_btn.pack(fill="x")
        ttk.Button(frm_preset_btn, text=t("btn_apply", L),
                   command=self._apply_preset
                   ).pack(side="left")
        ttk.Button(frm_preset_btn, text=t("btn_preset_save", L),
                   command=self._save_preset
                   ).pack(side="left", padx=(4, 0))
        ttk.Button(frm_preset_btn, text=t("btn_preset_del", L),
                   command=self._delete_preset
                   ).pack(side="left", padx=(4, 0))
        # 인라인 피드백 라벨 (Stage E — 저장/적용/삭제 비차단 표시)
        self._preset_fb = tk.Label(frm_preset_btn, text="", font=("Malgun Gothic", 13))
        self._preset_fb.pack(side="left", padx=(8, 0))

        # ── 기본 설정 섹션 ──────────────────────────
        frm_ss = ttk.LabelFrame(parent, text=f" {t('frm_basic', L)} ", padding=UI_LF_PADDING)
        frm_ss.pack(fill="x", pady=UI_PAD_SEC)
        frm_ss.columnconfigure(0, weight=1)

        ttk.Checkbutton(
            frm_ss, text=t("chk_ss_on", L),
            variable=self.var_ss_enabled,
            command=self._on_settings_change
        ).grid(row=0, column=0, sticky="w", pady=1)

        ttk.Checkbutton(
            frm_ss, text=t("chk_ps_on", L),
            variable=self.var_ps_enabled,
            command=self._on_settings_change
        ).grid(row=1, column=0, sticky="w", pady=1)

        ttk.Checkbutton(
            frm_ss, text=t("chk_mute_on", L),
            variable=self.var_mute_enabled,
            command=self._on_settings_change
        ).grid(row=2, column=0, sticky="w", pady=1)

        # 대기 시간 — 직접 입력만 (슬라이더 제거)
        frm_to = tk.Frame(frm_ss)
        frm_to.grid(row=3, column=0, sticky="ew", pady=(6, 2))
        tk.Label(frm_to, text=t("lbl_timeout", L),
                 font=("Malgun Gothic", 13)).pack(side="left")
        self.var_timeout_entry = tk.StringVar(value=str(int(self.var_timeout.get())))
        self.ent_timeout = ttk.Entry(
            frm_to, textvariable=self.var_timeout_entry,
            width=6, justify="center"
        )
        self.ent_timeout.pack(side="left", padx=(8, 4))
        self.ent_timeout.bind("<Return>", self._save_timeout_input)
        tk.Label(frm_to, text=t("lbl_min", L),
                 font=("Malgun Gothic", 13)).pack(side="left", padx=(0, 6))
        ttk.Button(
            frm_to, text=t("btn_save", L), width=6,
            command=self._save_timeout_input
        ).pack(side="left")

        # ── 화면보호기 모드 + 모니터 배정 (Stage B: memo_tab.py에서 이관) ──
        frm_mode = ttk.LabelFrame(parent, text=t("frm_ss_mode", L), padding=UI_LF_PADDING)
        frm_mode.pack(fill="x", pady=UI_PAD_SEC)

        self.var_ss_mode = tk.StringVar(value=self.config.get("screensaver_mode", "media"))
        for label, val in [(t("mode_media", L), "media"),
                            (t("mode_memo", L), "memo"),
                            (t("mode_split", L), "split")]:
            ttk.Radiobutton(frm_mode, text=label,
                            variable=self.var_ss_mode, value=val,
                            command=self._on_ss_mode_change).pack(anchor="w", pady=1)

        # 분할 옵션
        frm_sp = tk.Frame(frm_mode, padx=16)
        frm_sp.pack(fill="x", pady=(4, 0))
        tk.Label(frm_sp, text=t("lbl_split_dir", L)).pack(side="left")
        self.var_split_dir = tk.StringVar(value=self.config.get("split_direction", "h"))
        ttk.Combobox(frm_sp, textvariable=self.var_split_dir,
                     values=["h", "v"], state="readonly", width=4
                     ).pack(side="left", padx=(4, 2))
        tk.Label(frm_sp, text=t("lbl_split_guide", L)).pack(side="left", padx=(0, 4))
        self.var_split_ratio = tk.DoubleVar(value=self.config.get("split_ratio", 0.65))
        ttk.Scale(frm_sp, from_=0.3, to=0.85, orient="horizontal",
                  variable=self.var_split_ratio, length=80,
                  command=lambda v: self._on_ss_mode_change()).pack(side="left")
        self.lbl_ratio = tk.Label(frm_sp,
                                  text=f"{int(self.config.get('split_ratio', 0.65) * 100)}%",
                                  width=4)
        self.lbl_ratio.pack(side="left")
        self.var_split_dir.trace_add("write", lambda *_: self._on_ss_mode_change())

        # ── 모니터별 배정 ───────────────────────────
        frm_mon = ttk.LabelFrame(parent, text=t("frm_monitor", L), padding=UI_LF_PADDING)
        frm_mon.pack(fill="x", pady=UI_PAD_SEC)
        self._build_monitor_assignments(frm_mon)

        # ── 하단 버튼 행 ────────────────────────────
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=UI_PAD_SEP)
        frm_btn = tk.Frame(parent)
        frm_btn.pack(fill="x")

        ttk.Button(
            frm_btn, text=t("btn_pin_set", L),
            command=self._open_pin_dialog, width=10
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            frm_btn, text=t("btn_pin_rst", L),
            command=self._reset_pin_dialog, width=10
        ).pack(side="left", padx=(0, 4))

        ttk.Button(
            frm_btn, text=t("btn_lock", L),
            command=self._lock_screen, width=12
        ).pack(side="right")

        # ── PIN 메시지 입력 UI ───────────────────────
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=UI_PAD_SEP)
        frm_msg = ttk.LabelFrame(parent, text=t("frm_lock_msg", L), padding=UI_LF_PADDING)
        frm_msg.pack(fill="x", pady=UI_PAD_SEC)

        tk.Label(frm_msg,
                 text=t("lbl_pin_msg_guide", L),
                 font=("Malgun Gothic", 13), fg="#888888"
                 ).pack(anchor="w", pady=(0, 4))

        frm_msg_row = tk.Frame(frm_msg)
        frm_msg_row.pack(fill="x")

        self.var_pin_message = tk.StringVar(
            value=self.config.get("pin_message", "")
        )
        self._lbl_msg_count = tk.Label(frm_msg_row, text="0/30",
                                        font=("Arial", 13), fg="#888888", width=5)
        self._lbl_msg_count.pack(side="right", padx=(4, 0))

        entry_msg = ttk.Entry(frm_msg_row, textvariable=self.var_pin_message,
                              width=32)
        entry_msg.pack(side="left", fill="x", expand=True)

        def _on_msg_change(*_):
            raw = self.var_pin_message.get()
            if len(raw) > 30:
                self.var_pin_message.set(raw[:30])
                return
            self._lbl_msg_count.config(text=f"{len(raw)}/30",
                                        fg="#ff6b6b" if len(raw) == 30 else "#888888")
            self.config["pin_message"] = raw
            save_config(self.config)

        self.var_pin_message.trace_add("write", _on_msg_change)
        _on_msg_change()  # 초기 카운터 표시

        # ── 메시지 글자 크기 조절 ──────────────
        frm_msg_size = tk.Frame(frm_msg)
        frm_msg_size.pack(fill="x", pady=(6, 0))
        tk.Label(frm_msg_size, text=t("lbl_msg_size", L),
                 font=("Malgun Gothic", 13), fg="#666666"
                 ).pack(side="left")
        self.var_msg_fs = tk.IntVar(
            value=self.config.get("pin_message_font_size", 12)
        )
        ttk.Spinbox(frm_msg_size, from_=8, to=24,
                    textvariable=self.var_msg_fs, width=4
                    ).pack(side="left", padx=(4, 2))
        tk.Label(frm_msg_size, text="pt",
                 font=("Malgun Gothic", 13), fg="#666666"
                 ).pack(side="left")

        def _on_msg_fs_change(*_):
            try:
                fs = max(8, min(24, int(self.var_msg_fs.get())))
            except (tk.TclError, ValueError):
                fs = 12
            self.config["pin_message_font_size"] = fs
            save_config(self.config)
            # 미리보기 폰트 즉시 갱신
            try:
                if hasattr(self, '_lbl_msg_preview') and self._lbl_msg_preview:
                    self._lbl_msg_preview.config(
                        font=("Malgun Gothic", fs, "italic")
                    )
            except Exception:
                pass

        self.var_msg_fs.trace_add("write", _on_msg_fs_change)

        # 미리보기 라벨 (폰트 크기 반영)
        cur_fs = self.config.get("pin_message_font_size", 12)
        self._lbl_msg_preview = tk.Label(
            frm_msg, text="", font=("Malgun Gothic", cur_fs, "italic"),
            fg="#aaaaaa", pady=4, padx=8
        )
        self._lbl_msg_preview.pack(anchor="w", pady=(6, 0))

        def _update_preview(*_):
            raw = self.var_pin_message.get().strip()
            if raw:
                preview = raw[:30] + ("…" if len(raw) > 30 else "")
                self._lbl_msg_preview.config(text=f'미리보기: "{preview}"')
            else:
                self._lbl_msg_preview.config(text=t("lbl_no_msg", L))

        self.var_pin_message.trace_add("write", _update_preview)
        _update_preview()  # 초기 미리보기

    # ── 슬라이더 포맷 ────────────────────────────────
    def _save_preset(self):
        """현재 설정을 프리셋으로 저장 (이름 입력, 기존명=덮어쓰기 / 새 이름=추가)."""
        L = self.config.get("language", "ko")
        from ...persistence import load_user_presets, save_user_presets
        from ...constants import TIER_CONFIG
        sel = self.var_preset.get()
        internal = self._preset_map.get(sel, sel)
        name = simpledialog.askstring(
            t("btn_preset_save", L), t("dlg_preset_name", L),
            initialvalue=internal, parent=self.root
        )
        if not name:
            return
        name = name.strip()
        if not name or name == "none":
            return
        cur = {
            "screensaver_enabled":    self.config.get("screensaver_enabled", True),
            "power_save_enabled":     self.config.get("power_save_enabled", False),
            "mute_on_screensaver":    self.config.get("mute_on_screensaver", False),
            "pin_message":            self.config.get("pin_message", ""),
            "pin_message_font_size":  self.config.get("pin_message_font_size", 12),
            "screensaver_mode":       self.config.get("screensaver_mode", "media"),
            "split_ratio":            self.config.get("split_ratio", 0.65),
            "split_direction":        self.config.get("split_direction", "h"),
            "memo_bg_theme":          self.config.get("memo_bg_theme", "paper"),
            "memo_opacity":           self.config.get("memo_opacity", 0.0),
            "memo_bg_blur":           self.config.get("memo_bg_blur", False),
            "memo_blur_radius":       self.config.get("memo_blur_radius", 1),
            "hotkey_screensaver":     self.config.get("hotkey_screensaver", "ctrl+shift+l"),
            "hotkey_quick_memo":      self.config.get("hotkey_quick_memo", "ctrl+m"),
            "qm_hotkey_mode":         self.config.get("qm_hotkey_mode", "default"),
            "media_interval_seconds": self.config.get("media_interval_seconds", 10),
            "slide_mode":             self.config.get("slide_mode", "random"),
            "timeout_seconds":        self.config.get("timeout_seconds", 300),
            # Model B1: 선택(selected_media)만 프리셋에 저장(저장 시점 현재 선택 캡처).
            #  라이브러리(favorites)는 전역 — 저장 안 함(추가 미디어 항상 보존).
            "selected_media":         list(self.config.get("selected_media", [])),
        }
        up = load_user_presets()
        # 프리셋 한도 검사 (신규 프리셋만 — 기존명 덮어쓰기는 허용)
        is_premium  = self.config.get("is_premium", False)
        max_presets = TIER_CONFIG["premium" if is_premium else "free"]["max_presets"]
        if name not in up and len(up) >= max_presets:
            # 한도 도달 안내 — 구매 유도 대신 '업데이트 예정' 통일
            messagebox.showinfo(t("lic_pro_guide", L), t("msg_pro_limit", L),
                                parent=self.root)
            return
        up[name] = cur
        save_user_presets(up)
        self._build_tab_setting()
        self._flash_label("_preset_fb", "_preset_fb_job", t("fb_saved", L), "#27ae60")

    def _delete_preset(self):
        """선택 프리셋 삭제. 내장 키면 사용자 오버라이드만 제거(기본값 복귀)."""
        L = self.config.get("language", "ko")
        from ...persistence import load_user_presets, save_user_presets
        sel = self.var_preset.get()
        internal = self._preset_map.get(sel, sel)
        up = load_user_presets()
        if internal in up:
            del up[internal]
            save_user_presets(up)
            if self.config.get("active_preset") == internal:   # Stage F: 적용중 삭제 시 해제
                self.config["active_preset"] = None
                save_config(self.config)
            self._build_tab_setting()
            self._flash_label("_preset_fb", "_preset_fb_job", t("fb_deleted", L), "#27ae60")
        else:
            self._flash_label("_preset_fb", "_preset_fb_job", t("fb_preset_builtin", L), "#e67e22")

    # ══════════════════════════════════════════════
    # Stage C — 프리셋 카드 UI (A안)
    # ══════════════════════════════════════════════

    def _update_settings_scrollbar(self):
        """설정탭 세로 스크롤바: 내용이 캔버스보다 길 때만 표시(리사이즈 시 자동)."""
        try:
            c = self._setting_canvas; inner = self._setting_inner; vsb = self._setting_vsb
            if not (c.winfo_exists() and inner.winfo_exists()):
                return
            need = inner.winfo_reqheight() > c.winfo_height() + 2
            if need and not self._setting_vsb_mapped:
                vsb.pack(side="right", fill="y", before=c)
                self._setting_vsb_mapped = True
            elif not need and self._setting_vsb_mapped:
                vsb.pack_forget()
                self._setting_vsb_mapped = False
        except Exception:
            pass

    def fit_settings_canvas_to_content(self):
        """첫 실행 창 높이가 설정 내용에 딱 맞도록 캔버스 요청 높이를 내용 높이로 설정.
        center_window(reqheight 측정) 직전 호출. 이후 리사이즈는 fill/expand로 정상 동작."""
        try:
            c = getattr(self, "_setting_canvas", None)
            inner = getattr(self, "_setting_inner", None)
            if not c or not inner:
                return
            inner.update_idletasks()
            ch = inner.winfo_reqheight()
            if ch > 40:
                c.config(height=ch)
                if getattr(self, "_setting_vsb_mapped", False):
                    self._setting_vsb.pack_forget()
                    self._setting_vsb_mapped = False
        except Exception:
            pass

    def _build_preset_cards(self):
        """프리셋 카드 렌더링 (내장+사용자 병합). 선택 상태는 self.var_preset(표시명)로 관리."""
        L = self.config.get("language", "ko")
        for w in self.preset_frm.winfo_children():
            w.destroy()

        from ...persistence import get_all_presets
        _builtin_keys = ["none"]   # '기본'(none)만 내장 (업무/발표/집중/야간 제거)
        _tr_map = {"none": "preset_none"}
        _merged = get_all_presets()
        _preset_display = []
        self._preset_map = {}
        for _k in _merged:
            _disp = t(_tr_map[_k], L) if _k in _builtin_keys else _k
            _preset_display.append(_disp)
            self._preset_map[_disp] = _k

        # 선택 상태 var — 기존 선택이 유효하면 유지, 아니면 첫 항목으로
        if not hasattr(self, 'var_preset'):
            self.var_preset = tk.StringVar()
        if self.var_preset.get() not in _preset_display:
            self.var_preset.set(_preset_display[0] if _preset_display else "")

        # 카드=내용 크기만큼, 좌측 정렬, 한 줄 5개 초과 시 다음 줄 wrap (신축 없음)
        cols = self._PRESET_COLS
        for c in range(cols):
            self.preset_frm.grid_columnconfigure(c, weight=0, uniform="")
        for i, disp in enumerate(_preset_display):
            internal = self._preset_map[disp]
            card = self._create_preset_card(self.preset_frm, disp, internal, _merged.get(internal, {}), L)
            card.grid(row=i // cols, column=i % cols, padx=4, pady=2, sticky="w")

    _PRESET_COLS   = 5     # 한 줄 프리셋 카드 수
    _PRESET_CARD_W = 104   # 프리셋 카드 고정 폭(px) — 미디어 썸네일과 동일 정사각형
    _PRESET_CARD_H = 104   # 프리셋 카드 고정 높이(px)
    _PRESET_NAME_MAX = 15  # 카드 표시 이름 최대 글자수(초과 시 …). 104×104·14pt 기준 3줄 이내

    def _create_preset_card(self, parent, disp, internal, preset_dict, L):
        is_sel     = (self.var_preset.get() == disp)                 # 선택(포커스)
        is_applied = (internal == self.config.get("active_preset"))  # 적용 중(Stage F)
        bg  = "#d4e6ff" if is_sel else "#f5f5f5"
        brd = "#27ae60" if is_applied else ("#2980b9" if is_sel else "#dddddd")

        card = tk.Frame(parent, bg=bg, highlightbackground=brd,
                        highlightthickness=3 if is_applied else 2,
                        padx=8, pady=6, cursor="hand2",
                        width=self._PRESET_CARD_W, height=self._PRESET_CARD_H)
        card.pack_propagate(False)   # 내부가 pack 배치 → pack_propagate로 고정 크기 유지(썸네일처럼)
        hdr = tk.Frame(card, bg=bg)
        hdr.pack(fill="both", expand=True)   # 정사각형 카드 중앙 정렬
        # 적용 중 표시: ✔ (상단 중앙)
        if is_applied:
            tk.Label(hdr, text="✔", fg="#27ae60", font=("Arial", 13, "bold"),
                     bg=bg).pack(pady=(0, 2))
        # 카드 표시용 말줄임(…): 3줄 초과 방지. 선택/저장은 전체 이름(disp) 유지.
        _shown = disp if len(disp) <= self._PRESET_NAME_MAX else disp[:self._PRESET_NAME_MAX - 1] + "…"
        tk.Label(hdr, text=_shown, font=("Malgun Gothic", 14, "bold"), bg=bg,
                 anchor="center", justify="center",
                 wraplength=self._PRESET_CARD_W - 16).pack(expand=True)

        # 카드 전체(중첩 포함) 클릭 → 선택
        def _bind_click(w):
            w.bind("<Button-1>", lambda e, d=disp: self._select_preset(d))
            for c in w.winfo_children():
                _bind_click(c)
        _bind_click(card)

        return card

    def _preset_card_summary(self, preset_dict, L) -> str:
        """카드 요약: 모드 + 배경 테마. 빈 프리셋(none 등)은 기본 안내 문구."""
        _mode_tr = {"media": "mode_media", "memo": "mode_memo", "split": "mode_split"}
        _builtin_themes = {"white", "grid", "paper", "forest", "ocean"}
        parts = []
        mode = preset_dict.get("screensaver_mode")
        if mode in _mode_tr:
            parts.append(t(_mode_tr[mode], L))
        theme = preset_dict.get("memo_bg_theme")
        if theme:
            parts.append(t("theme_" + theme, L) if theme in _builtin_themes else theme)
        return " · ".join(parts) if parts else t("lbl_preset_default", L)

    def _select_preset(self, disp: str):
        """카드 클릭 → 선택 상태 갱신 + 카드 영역만 부분 재렌더(하이라이트)."""
        self.var_preset.set(disp)
        self._build_preset_cards()

    def _fmt_timeout(self) -> str:
        lang = self.config.get("language", "ko")
        mins = int(self.var_timeout.get())
        if mins < 60:
            return t("fmt_min", lang).format(n=mins)
        return t("fmt_60min", lang)

    def _on_timeout_change(self, *_):
        # 슬라이더 움직일 때 entry도 동기화
        if hasattr(self, "var_timeout_entry"):
            self.var_timeout_entry.set(str(int(self.var_timeout.get())))
        self._on_settings_change()

    def _save_timeout_input(self, event=None):
        """직접 설정 [저장] 버튼 — 입력값 검증 후 슬라이더·config 모두 반영."""
        L = self.config.get("language", "ko")
        try:
            val = int(self.var_timeout_entry.get())
            if val < 1:
                val = 1
        except (ValueError, tk.TclError):
            messagebox.showwarning(
                t("lbl_input_err", L),
                t("lbl_num_only", L),
                parent=self.root
            )
            self.var_timeout_entry.set(str(int(self.var_timeout.get())))
            return
        # 슬라이더 범위(9999) 초과 허용 — 슬라이더는 시각화 목적
        self.var_timeout.set(min(val, 9999))
        self.var_timeout_entry.set(str(val))
        self.config["timeout_seconds"] = val * 60
        save_config(self.config)
        messagebox.showinfo(t("msg_save_done", L), t("msg_timeout_set", L).format(val=val), parent=self.root)
        LOG.info(f"대기 시간 직접 설정: {val}분")

    # ── 설정 자동 저장 ───────────────────────────────
    def _on_settings_change(self, *_):
        self.config["screensaver_enabled"]    = self.var_ss_enabled.get()
        self.config["power_save_enabled"]     = self.var_ps_enabled.get()
        self.config["mute_on_screensaver"]    = self.var_mute_enabled.get()
        self.config["timeout_seconds"]        = int(self.var_timeout.get()) * 60
        self.config["slide_mode"]             = self.var_slide_mode.get()
        try:
            self.config["media_interval_seconds"] = int(self.var_interval.get())
        except (tk.TclError, ValueError):
            pass
        save_config(self.config)
        LOG.debug("설정 자동 저장")

    # ══════════════════════════════════════════════
    # Stage B — 화면보호기 모드 + 모니터 배정 (memo_tab.py에서 이관)
    # ══════════════════════════════════════════════

    def _on_ss_mode_change(self):
        self.config["screensaver_mode"]  = self.var_ss_mode.get()
        self.config["split_direction"]   = self.var_split_dir.get()
        try:
            ratio = float(self.var_split_ratio.get())
            self.config["split_ratio"] = ratio
            if hasattr(self, 'lbl_ratio'):
                self.lbl_ratio.config(text=f"{int(ratio*100)}%")
        except (ValueError, tk.TclError):
            pass
        # ✅ monitor_assignments 초기화 제거:
        #    주 모니터는 항상 글로벌 모드(_build_content_map에서 처리),
        #    보조 모니터 배정은 글로벌 모드 변경과 독립 유지.
        save_config(self.config)
        # 미니맵 주 모니터 타일은 g_mode(screensaver_mode) 기반 → 모드 변경 즉시 재렌더
        # (기존: _save_monitor_assignments에서만 갱신 → 2번 모니터 조작해야 반영되던 문제)
        try:
            self._draw_monitor_minimap(_get_monitors_info())
        except Exception:
            pass

    def _identify_monitors(self):
        """각 물리 모니터에 번호를 1.5초간 전체화면 오버레이로 표시(Windows Identify 유사).
        번호 규칙 = 배정 UI와 동일: 주 모니터 '🏠', 그 외 인덱스+1."""
        self._close_identify()   # 중복 호출 시 기존 오버레이 정리
        L = self.config.get("language", "ko")
        self._identify_wins = []
        try:
            mons = _get_monitors_info()
        except Exception:
            mons = []
        for i, mon in enumerate(mons):
            mx, my, mw, mh, is_primary = mon
            try:
                top = tk.Toplevel(self.root)
                top.overrideredirect(True)
                top.geometry(f"{mw}x{mh}+{mx}+{my}")
                top.configure(bg="#1b1b1b")
                try:
                    top.attributes("-topmost", True)
                    top.attributes("-alpha", 0.85)
                except Exception:
                    pass
                num_txt = "🏠" if is_primary else str(i + 1)
                tk.Label(top, text=num_txt, fg="#ffffff", bg="#1b1b1b",
                         font=("Arial", max(48, min(mw, mh) // 4), "bold")
                         ).place(relx=0.5, rely=0.46, anchor="center")
                tk.Label(top, text=f"{mw}×{mh}", fg="#8ab4f8", bg="#1b1b1b",
                         font=("Malgun Gothic", 22)
                         ).place(relx=0.5, rely=0.68, anchor="center")
                self._identify_wins.append(top)
            except Exception:
                pass
        self.root.after(1500, self._close_identify)

    def _close_identify(self):
        for w in getattr(self, "_identify_wins", []):
            try:
                if w.winfo_exists():
                    w.destroy()
            except Exception:
                pass
        self._identify_wins = []

    def _build_monitor_assignments(self, parent: tk.Frame):
        """
        보조 모니터마다 콘텐츠 배정 콤보박스 생성.
        주 모니터: 항상 글로벌 모드(설정 탭) 적용 → 배정 불필요.
        보조 모니터: 영상 / 메모 중 하나만 선택.
        """
        L = self.config.get("language", "ko")
        mons = _get_monitors_info()
        assignments = {
            a["mon_key"]: a["content"]
            for a in self.config.get("monitor_assignments", [])
        }
        if len(mons) == 1:
            tk.Label(parent,
                     text=t("lbl_single_mon", L),
                     fg="#888888", font=("Malgun Gothic", 13)
                     ).pack(anchor="w", pady=2)
            return

        # ── K1: 모니터 배치 미니맵 (읽기 전용) ──────────
        tk.Label(parent, text=t("lbl_mon_map", L),
                 font=("Malgun Gothic", 13), fg="#555555").pack(anchor="w", pady=(2, 0))
        self._mon_canvas = tk.Canvas(parent, width=280, height=120,
                                     bg="#f0f0f0", highlightthickness=1,
                                     highlightbackground="#cccccc")
        self._mon_canvas.pack(anchor="w", pady=(0, 4))
        self._draw_monitor_minimap(mons)

        # #7: 물리 모니터에 번호 잠깐 표시(Identify) — 설정 라벨과 매핑 확인
        ttk.Button(parent, text=t("btn_identify", L),
                   command=self._identify_monitors
                   ).pack(anchor="w", pady=(0, 4))

        # #5: 배정 콤보 클릭 타겟 확대(패딩) — 스타일 1회 정의
        try:
            _st = ttk.Style(self.root)
            _st.configure("Mon.TCombobox", padding=4)
        except Exception:
            pass

        self._mon_vars: dict = {}
        for i, mon in enumerate(mons):
            mx, my, mw, mh, is_primary = mon
            mon_key = f"{mw}x{mh}+{mx}+{my}"

            row = tk.Frame(parent)
            row.pack(fill="x", pady=2)

            if is_primary:
                # 주 모니터: 글로벌 모드 안내만, 콤보박스 없음
                tk.Label(row,
                         text=t("lbl_monitor_fmt", L).format(
                             num=" 🏠주", w=mw, h=mh),
                         font=("Malgun Gothic", 13), width=22, anchor="w"
                         ).pack(side="left")
                tk.Label(row,
                         text=t("lbl_primary_global", L),
                         fg="#888888", font=("Malgun Gothic", 13)
                         ).pack(side="left", padx=4)
            else:
                # 보조 모니터: 영상/메모 선택 (split 제외)
                sec_num = i + 1
                tk.Label(row,
                         text=t("lbl_monitor_fmt", L).format(
                             num=f" {sec_num}번", w=mw, h=mh),
                         font=("Malgun Gothic", 13), width=22, anchor="w"
                         ).pack(side="left")
                # 표시 ↔ 저장값 매핑 (영상=1개·주 비영상 시만 재생 / 이미지=정적)
                _opts = [("video", t("opt_video", L)),
                         ("media", t("opt_image", L)),
                         ("memo",  t("opt_memo", L)),
                         ("black", t("opt_black", L))]
                self._mon_disp2val = {d: v for v, d in _opts}
                _val2disp = {v: d for v, d in _opts}
                # 기존 assignments에 split이 있으면 media로 보정 (기본값=black)
                saved = assignments.get(mon_key, "black")
                if saved == "split":
                    saved = "media"
                self._mon_val2disp = _val2disp   # 미니맵 클릭 토글용 역매핑
                var = tk.StringVar(value=_val2disp.get(saved, _val2disp["media"]))
                self._mon_vars[mon_key] = var
                ttk.Combobox(row, textvariable=var,
                             values=[d for _, d in _opts],  # split 제외, 동영상 옵션 없음
                             state="readonly", width=12, style="Mon.TCombobox"
                             ).pack(side="left", padx=6, ipady=2)
                var.trace_add("write", lambda *_: self._save_monitor_assignments())

        tk.Label(parent,
                 text=t("lbl_dual_drag", L),
                 fg="#888888", font=("Malgun Gothic", 13)
                 ).pack(anchor="w", pady=(4, 0))
        # 동영상 미지원 명확화
        tk.Label(parent,
                 text=t("lbl_sec_no_video", L),
                 fg="#c0392b", font=("Malgun Gothic", 13)
                 ).pack(anchor="w", pady=(0, 2))
        # 인라인 저장 피드백 (Stage E)
        self._mon_fb = tk.Label(parent, text="", font=("Malgun Gothic", 13))
        self._mon_fb.pack(anchor="w")

    def _save_monitor_assignments(self):
        """보조 모니터 배정만 저장. 주 모니터는 항상 글로벌 모드."""
        if not hasattr(self, '_mon_vars'):
            return
        _d2v = getattr(self, "_mon_disp2val", None)
        self.config["monitor_assignments"] = [
            {"mon_key": k, "content": (_d2v.get(v.get(), v.get()) if _d2v else v.get())}
            for k, v in self._mon_vars.items()
        ]
        save_config(self.config)
        # K1: 저장 즉시 미니맵 재렌더 (콤보박스 변경 반영)
        try:
            self._draw_monitor_minimap(_get_monitors_info())
        except Exception:
            pass
        L = self.config.get("language", "ko")
        self._flash_label("_mon_fb", "_mon_fb_job", t("fb_saved", L), "#27ae60")

    def _draw_monitor_minimap(self, mons):
        """K1: 모니터 좌표 기반 축소 배치도(읽기 전용). 음수 좌표 정규화 + 균일 스케일."""
        cv = getattr(self, "_mon_canvas", None)
        if not cv or not cv.winfo_exists():
            return
        cv.delete("all")
        _COL = {"global": "#2980b9", "media": "#27ae60", "memo": "#e67e22",
                "black": "#333333", "video": "#8e44ad"}
        assignments = {a["mon_key"]: a["content"]
                       for a in self.config.get("monitor_assignments", [])}
        g_mode = self.config.get("screensaver_mode", "media")
        _L2 = self.config.get("language", "ko")
        _seclbl = {"media": t("opt_image", _L2), "memo": t("opt_memo", _L2),
                   "black": t("opt_black", _L2), "video": t("opt_video", _L2)}
        xs  = [m[0] for m in mons];            ys  = [m[1] for m in mons]
        xe  = [m[0] + m[2] for m in mons];     ye  = [m[1] + m[3] for m in mons]
        minx, miny = min(xs), min(ys)
        bw, bh = max(xe) - minx, max(ye) - miny
        if bw <= 0 or bh <= 0:
            return
        PAD, CW, CH = 8, 280, 120
        scale = min((CW - 2 * PAD) / bw, (CH - 2 * PAD) / bh)
        for i, (mx, my, mw, mh, is_primary) in enumerate(mons):
            x0 = PAD + (mx - minx) * scale
            y0 = PAD + (my - miny) * scale
            x1, y1 = x0 + mw * scale, y0 + mh * scale
            if is_primary:
                mode, num, disp = "global", "🏠", g_mode
                _tags = ()
            else:
                mon_key = f"{mw}x{mh}+{mx}+{my}"
                mode = assignments.get(mon_key, "black")
                if mode == "split":
                    mode = "media"
                num, disp = f"{i + 1}", _seclbl.get(mode, mode)
                _tags = (f"mk::{mon_key}",)   # 클릭 토글용 태그
            cv.create_rectangle(x0, y0, x1, y1, fill=_COL.get(mode, "#888888"),
                                outline="#ffffff", width=2, tags=_tags)
            cv.create_text((x0 + x1) / 2, (y0 + y1) / 2,
                           text=f"{num}\n{disp}", fill="#ffffff",
                           font=("Malgun Gothic", 12, "bold"),
                           justify="center", tags=_tags)
            # K2: 보조 모니터는 클릭 시 모드 순환(주 모니터는 클릭 비활성)
            if not is_primary:
                _tag = _tags[0]
                cv.tag_bind(_tag, "<Button-1>",
                            lambda e, k=mon_key: self._minimap_cycle(k))
                cv.tag_bind(_tag, "<Enter>",
                            lambda e: cv.config(cursor="hand2"))
                cv.tag_bind(_tag, "<Leave>",
                            lambda e: cv.config(cursor=""))

    def _minimap_cycle(self, mon_key):
        """K2: 미니맵 보조 사각형 클릭 → 모드 순환. 기존 콤보 var 갱신(저장 트리거)."""
        var = getattr(self, "_mon_vars", {}).get(mon_key)
        if not var:
            return
        order = ["video", "media", "memo", "black"]
        d2v = getattr(self, "_mon_disp2val", {})
        v2d = getattr(self, "_mon_val2disp", {})
        cur = d2v.get(var.get(), "media")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "media"
        var.set(v2d.get(nxt, var.get()))   # trace → _save_monitor_assignments(저장+미니맵 재렌더)

    # ── Stage E: 인라인 피드백 헬퍼 (비차단, N초 후 원복) ──
    def _flash_label(self, lbl_attr, job_attr, msg, color="#27ae60"):
        lbl = getattr(self, lbl_attr, None)
        if not (lbl and lbl.winfo_exists()):
            return
        _job = getattr(self, job_attr, None)
        if _job:
            try:
                self.root.after_cancel(_job)
            except Exception:
                pass
        lbl.config(text=msg, fg=color)
        setattr(self, job_attr,
                self.root.after(2000, lambda: self._clear_label(lbl_attr, job_attr)))

    def _clear_label(self, lbl_attr, job_attr):
        setattr(self, job_attr, None)
        lbl = getattr(self, lbl_attr, None)
        if lbl and lbl.winfo_exists():
            lbl.config(text="")

