# -*- coding: utf-8 -*-
"""
media_tab — 미디어 탭 (Stage A: settings_tab.py에서 분리)
⚠️ Mixin — ScreesaverApp에 다중상속됨. self 속성은 App.__init__에 정의.
"""
import logging
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

LOG = logging.getLogger("MuteAndSaver")

_HAS_PIL = False
try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except ImportError:
    pass

from ...i18n import t
from ...constants import TIER_CONFIG, IMG_EXTS, VIDEO_EXTS
from ...persistence import save_config, save_favorites
from ...services import _verify_master
from ...media import generate_thumb, _safe_font
from ..window_utils import add_tooltip


class MediaTabMixin:
    def _build_tab_media(self):
        parent = self.tab_media
        L = self.config.get("language", "ko")
        for w in parent.winfo_children():
            w.destroy()

        # ── 미디어 섹션 ─────────────────────────────
        frm_media = ttk.LabelFrame(parent, text=f" {t('frm_media', L)} ", padding=(8, 4))
        frm_media.pack(fill="both", expand=True, pady=(0, 6))

        # 즐겨찾기 표시 옵션 툴바 (정렬/필터)
        self.var_fav_top  = tk.BooleanVar(value=self.config.get("media_fav_top", False))
        self.var_fav_only = tk.BooleanVar(value=self.config.get("media_fav_only", False))
        frm_fav = tk.Frame(frm_media)
        frm_fav.pack(fill="x", pady=(0, 4))
        ttk.Checkbutton(frm_fav, text=t("chk_fav_top", L),
                        variable=self.var_fav_top,
                        command=self._on_fav_filter).pack(side="left")
        ttk.Checkbutton(frm_fav, text=t("chk_fav_only", L),
                        variable=self.var_fav_only,
                        command=self._on_fav_filter).pack(side="left", padx=(12, 0))

        # 영상 목록 (세로 스크롤 wrap 그리드 — 창 폭에 따라 열 수 자동)
        self.media_canvas = tk.Canvas(frm_media, height=160, highlightthickness=0)
        sb = ttk.Scrollbar(frm_media, orient="vertical",
                           command=self.media_canvas.yview)
        self.media_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.media_canvas.pack(fill="both", expand=True)
        self.media_frm = tk.Frame(self.media_canvas)
        self.media_canvas_win = self.media_canvas.create_window(
            (0, 0), window=self.media_frm, anchor="nw"
        )
        def _sync_scrollregion(e):
            try:
                self.media_canvas.configure(scrollregion=self.media_canvas.bbox("all"))
            except Exception as _ex:   # 0xc000041d 방지 — 콜백 예외 격리
                if not getattr(self, "_mf_cfg_exc_logged", False):
                    self._mf_cfg_exc_logged = True
                    LOG.warning(f"[Diag] media_frm <Configure> 예외 격리: {type(_ex).__name__}: {_ex}")
        self.media_frm.bind("<Configure>", _sync_scrollregion)
        # 캔버스 폭 변화 → 내부 프레임 폭 맞춤 + 열 수 재계산(디바운스)
        # 재빌드 시 이전 캔버스에 걸린 stale 디바운스 잡 취소(파괴 위젯 참조 차단)
        _old_job = getattr(self, "_media_resize_job", None)
        if _old_job:
            try:
                self.root.after_cancel(_old_job)
            except Exception:
                pass
        self.media_canvas.bind("<Configure>", self._on_media_canvas_resize)
        self._media_resize_job = None
        self._thumb_photos = {}
        self._build_media_grid()

        # 선택 상태 라벨
        self.lbl_selected = tk.Label(frm_media, text="", font=("Arial", 13), fg="#666666")
        self.lbl_selected.pack(anchor="w", pady=(4, 0))
        self._update_selection_label()

        # 미디어 옵션 행 (순서 + 간격)
        frm_opt = tk.Frame(frm_media)
        frm_opt.pack(fill="x", pady=(4, 0))

        tk.Label(frm_opt, text=t("lbl_order", L)).pack(side="left")
        slide_cb = ttk.Combobox(
            frm_opt, textvariable=self.var_slide_mode,
            values=["random", "sequential"],
            state="readonly", width=9
        )
        slide_cb.pack(side="left", padx=(2, 14))
        slide_cb.bind("<<ComboboxSelected>>", lambda e: self._on_settings_change())

        # 전환 자동/수동 (자동=초 간격 / 수동=Tab으로 다음)
        tk.Label(frm_opt, text=t("lbl_transition", L)).pack(side="left")
        self._auto_d2v = {t("opt_auto", L): True, t("opt_manual", L): False}
        _v2d = {v: d for d, v in self._auto_d2v.items()}
        self.var_slide_auto = tk.StringVar(
            value=_v2d.get(self.config.get("slide_auto", True), t("opt_auto", L)))
        trans_cb = ttk.Combobox(
            frm_opt, textvariable=self.var_slide_auto,
            values=[t("opt_auto", L), t("opt_manual", L)],
            state="readonly", width=7
        )
        trans_cb.pack(side="left", padx=(2, 14))
        trans_cb.bind("<<ComboboxSelected>>", lambda e: self._on_transition_change())

        tk.Label(frm_opt, text=t("lbl_interval", L)).pack(side="left")
        self._spn_interval = ttk.Spinbox(
            frm_opt, from_=3, to=300,
            textvariable=self.var_interval,
            width=4, command=self._on_settings_change
        )
        self._spn_interval.pack(side="left", padx=2)
        self.var_interval.trace_add("write", lambda *_: self._on_settings_change())
        tk.Label(frm_opt, text=t("lbl_sec", L)).pack(side="left")
        # 수동 힌트 라벨
        self._lbl_manual_hint = tk.Label(frm_opt, text=t("hint_manual_tab", L),
                                         fg="#888888", font=("Malgun Gothic", 13))
        self._lbl_manual_hint.pack(side="left", padx=(10, 0))
        self._sync_transition_ui()   # 초기 상태 반영(간격 활성/비활성 + 힌트)

    def _on_transition_change(self):
        """전환 자동/수동 변경 → config 저장 + UI 동기화."""
        auto = self._auto_d2v.get(self.var_slide_auto.get(), True)
        self.config["slide_auto"] = auto
        save_config(self.config)
        self._sync_transition_ui()

    def _sync_transition_ui(self):
        """자동=간격 활성/힌트 숨김, 수동=간격 비활성/힌트 표시."""
        auto = self.config.get("slide_auto", True)
        try:
            self._spn_interval.config(state=("normal" if auto else "disabled"))
        except Exception:
            pass
        try:
            if auto:
                self._lbl_manual_hint.pack_forget()
            elif not self._lbl_manual_hint.winfo_ismapped():
                self._lbl_manual_hint.pack(side="left", padx=(10, 0))
        except Exception:
            pass

    # ══════════════════════════════════════════════
    # Stage 4 — 미디어 갤러리 (Stage A: media_tab.py로 이관)
    # ══════════════════════════════════════════════

    _MEDIA_CARD_W  = 104   # 카드 폭 추정 기본값(실측 전 폴백)
    _MEDIA_MAX_COLS = 4    # 1줄 최대 썸네일 수(넓어도 4개 유지, 좁으면 다음 줄로)

    def _calc_media_cols(self, avail):
        """가용 폭 → 열 수. 실측 카드폭(있으면) 기반, 상한 4열, 최소 1열."""
        unit = getattr(self, "_media_card_unit", self._MEDIA_CARD_W)
        if unit <= 1:
            unit = self._MEDIA_CARD_W
        n = int(max(1, avail) // unit)
        return max(1, min(self._MEDIA_MAX_COLS, n))

    def _win_minimized(self):
        """메인 창 최소화(iconic) 상태 여부. 예외 시 False."""
        try:
            return self.root.state() == "iconic"
        except Exception:
            return False

    def _on_media_canvas_resize(self, event):
        """캔버스 폭 변화 시 내부 프레임 폭 동기화 + 열 수 재계산(디바운스)."""
        # ⚠️ 재진입 방어(리사이즈 재귀 → 스택 오버플로 가설 대응)
        if getattr(self, "_mc_cfg_busy", False):
            if not getattr(self, "_mc_cfg_warned", False):
                self._mc_cfg_warned = True
                LOG.warning("[Diag] 미디어탭 <Configure> 재진입 차단 — 리사이즈 재귀 확인")
            return
        # 파괴된 위젯 접근 차단 (탭 재빌드/종료 중 Configure 발화 가드)
        if not self.media_canvas.winfo_exists():
            return
        self._mc_cfg_busy = True
        try:
            self._do_media_canvas_resize(event)
        except Exception as _ex:
            # 0xc000041d 방지: 리사이즈 콜백 예외가 커널 경계로 탈출 시 프로세스 강제종료
            if not getattr(self, "_mc_cfg_exc_logged", False):
                self._mc_cfg_exc_logged = True
                LOG.warning(f"[Diag] 미디어탭 <Configure> 예외 격리: {type(_ex).__name__}: {_ex}")
        finally:
            self._mc_cfg_busy = False

    def _do_media_canvas_resize(self, event):
        # 최소화/0폭: Configure 폭주 구간 → 레이아웃 churn·열 수 폭주 방지
        if event.width <= 1 or self._win_minimized():
            return
        try:
            self.media_canvas.itemconfigure(self.media_canvas_win, width=event.width)
        except tk.TclError:
            return
        if self._media_resize_job:
            try:
                self.media_canvas.after_cancel(self._media_resize_job)
            except Exception:
                pass
        self._media_resize_job = self.media_canvas.after(
            120, lambda w=event.width: self._reflow_media(w)
        )

    def _reflow_media(self, width):
        self._media_resize_job = None
        if not (hasattr(self, "media_frm") and self.media_frm.winfo_exists()):
            return
        if width <= 1 or self._win_minimized():   # 0폭/최소화 구간 재배치 생략
            return
        cols = self._calc_media_cols(width - 4)   # -4: 우측 여유(마지막 카드 잘림 방지)
        if cols == getattr(self, "_media_cols", 0):
            return
        self._media_cols = cols
        # ⚠️ 핵심: resize 시 카드를 파괴/재생성하지 않고 기존 위젯을 재배치만.
        #    (destroy+재생성+PIL 썸네일 재로드가 Windows에서 네이티브 크래시 유발)
        try:
            self._place_media_cards()
        except tk.TclError:
            pass

    def _deferred_build_grid(self):
        self._grid_defer_job = None
        self._build_media_grid()

    def _build_media_grid(self):
        """카드 위젯을 1회 생성(favorites 변경 시에만) 후 배치 위임."""
        if not (hasattr(self, "media_frm") and self.media_frm.winfo_exists()):
            return
        # 최소화 중엔 썸네일 재생성(네이티브 지연 import 위험) 보류 → 복원 후 1회 재빌드
        if self._win_minimized():
            if getattr(self, "_grid_defer_job", None) is None:
                self._grid_defer_job = self.root.after(300, self._deferred_build_grid)
            return
        # 이전 썸네일 PhotoImage 참조 정리 (반복 재빌드 시 누수 방지)
        if hasattr(self, "_thumb_photos"):
            self._thumb_photos.clear()
        for w in self.media_frm.winfo_children():
            w.destroy()
        # 표시 목록 = 필터(즐겨찾기만) → 정렬(즐겨찾기 위로, 안정 정렬)
        fav_only = self.config.get("media_fav_only", False)
        fav_top  = self.config.get("media_fav_top", False)
        items = [f for f in self.favorites if f.get("fav", False)] if fav_only else list(self.favorites)
        if fav_top and not fav_only:
            items = sorted(items, key=lambda f: not f.get("fav", False))
        self._grid_items = items
        # 카드 위젯 생성(배치는 _place_media_cards가 담당)
        self._media_cards = []
        for fav in items:
            card = self._create_card(
                self.media_frm, fav.get("path",""), fav.get("name","?"),
                fav.get("tier","free"), show_remove=True
            )
            self._media_cards.append(card)
        # + 추가 버튼 (항상 맨 뒤)
        btn_add = tk.Frame(self.media_frm, width=90, height=90,
                           bg="#f0f0f0", highlightbackground="#cccccc",
                           highlightthickness=2, cursor="hand2")
        btn_add.pack_propagate(False)
        tk.Label(btn_add, text="＋", font=("Arial", 22), bg="#f0f0f0",
                 fg="#888888", cursor="hand2").pack(expand=True)
        btn_add.bind("<Button-1>", lambda e: self._add_user_media())
        for child in btn_add.winfo_children():
            child.bind("<Button-1>", lambda e: self._add_user_media())
        add_tooltip(btn_add, t("tip_add_media", self.config.get("language", "ko")))
        self._media_add_btn = btn_add
        self._place_media_cards()
        # 실제 카드 폭 측정은 after_idle로 지연 → 빌드 중 동기 update_idletasks 재진입 방지
        #  (파일 다이얼로그 콜백 직후 빌드 시 이벤트 루프 재진입 → 네이티브 크래시 유발했음)
        self.root.after_idle(self._measure_card_unit)

    def _measure_card_unit(self):
        """카드 실측 폭 → 단위 갱신 후 열 재계산·재배치(파괴 없음)."""
        if not (hasattr(self, "media_frm") and self.media_frm.winfo_exists()):
            return
        try:
            cards = getattr(self, "_media_cards", [])
            ref = cards[0] if cards else getattr(self, "_media_add_btn", None)
            if not (ref and ref.winfo_exists()):
                return
            w0 = ref.winfo_reqwidth()
            if w0 <= 1:
                return
            new_unit = w0 + 8
            if new_unit == getattr(self, "_media_card_unit", None):
                return
            self._media_card_unit = new_unit
            try:
                avail = self.media_canvas.winfo_width()
            except Exception:
                avail = 0
            if avail > 1:
                self._media_cols = self._calc_media_cols(avail - 4)
            self._place_media_cards()
        except tk.TclError:
            pass

    def _place_media_cards(self):
        """생성된 카드/추가버튼을 현재 열 수에 맞춰 grid 재배치(파괴 없음)."""
        if not (hasattr(self, "media_frm") and self.media_frm.winfo_exists()):
            return
        cols = getattr(self, "_media_cols", 0)
        if not cols:   # 최초 배치: 현재 캔버스 폭 기준 계산(미실현 시 4열 기본)
            try:
                avail = self.media_canvas.winfo_width()
            except Exception:
                avail = 0
            cols = self._calc_media_cols(avail - 4) if avail > 1 else self._MEDIA_MAX_COLS
            self._media_cols = cols
        widgets = list(getattr(self, "_media_cards", []))
        _add = getattr(self, "_media_add_btn", None)
        if _add is not None:
            widgets.append(_add)
        for i, w in enumerate(widgets):
            try:
                w.grid(row=i // cols, column=i % cols, padx=4, pady=4, sticky="n")
            except tk.TclError:
                pass

    def _create_card(self, parent, filepath, name, tier, show_remove=False):
        sel_list = self.config.get("selected_media", [])
        is_sel = filepath in sel_list
        _fav_item = next((f for f in self.favorites if f.get("path","") == filepath), None)
        is_fav = bool(_fav_item and _fav_item.get("fav", False))
        file_ok = Path(filepath).exists()

        bg   = "#d4e6ff" if is_sel else "#f5f5f5"
        brd  = "#2980b9" if is_sel else "#dddddd"

        card = tk.Frame(parent, bg=bg, highlightbackground=brd,
                        highlightthickness=2, padx=4, pady=4)

        # ── 썸네일 ──
        thumb_loaded = False
        if file_ok and _HAS_PIL:
            tp = generate_thumb(filepath)
            if tp:
                try:
                    with Image.open(tp) as pil_img:
                        photo = ImageTk.PhotoImage(pil_img)
                    lbl_img = tk.Label(card, image=photo, bg=bg, cursor="hand2")
                    lbl_img.image = photo
                    self._thumb_photos[filepath] = photo
                    lbl_img.pack(padx=1, pady=0)   # pady=0: 불필요한 수직 여백 제거
                    thumb_loaded = True
                except Exception:
                    pass
        if not thumb_loaded:
            txt = "⚠" if not file_ok else "\U0001F3AC"
            lbl_img = tk.Label(card, text=txt, font=("Arial", 18),
                               width=10, height=3, bg="#555555", fg="#ffffff",
                               cursor="hand2")
            lbl_img.pack(padx=1, pady=0)

        # ── 파일명 ──
        disp_name = name if len(name) <= 12 else name[:11] + "…"
        tk.Label(card, text=disp_name, font=("Arial", 13), bg=bg).pack(pady=(2,0))

        # ── 하단: ⭐ + ✔ + ✕ ──
        frm_b = tk.Frame(card, bg=bg)
        frm_b.pack(fill="x")
        _L = self.config.get("language", "ko")
        star_chr = "⭐" if is_fav else "☆"
        lbl_star = tk.Label(frm_b, text=star_chr, font=("Arial", 13),
                            cursor="hand2", bg=bg)
        lbl_star.pack(side="left")
        lbl_star.bind("<Button-1>",
                      lambda e, fp=filepath, n=name, t=tier: self._toggle_favorite(fp,n,t) or "break")
        add_tooltip(lbl_star, t("tip_fav", _L))

        if is_sel:
            tk.Label(frm_b, text="✔", font=("Arial", 13),
                     fg="#27ae60", bg=bg).pack(side="left", padx=2)
        if show_remove:
            lbl_rm = tk.Label(frm_b, text="✕", font=("Arial", 13),
                              cursor="hand2", fg="#e74c3c", bg=bg)
            lbl_rm.pack(side="right")
            lbl_rm.bind("<Button-1>",
                        lambda e, fp=filepath: self._remove_favorite(fp) or "break")
            add_tooltip(lbl_rm, t("tip_remove", _L))

        # ── 클릭 선택 + 드래그 재정렬 (이미지·카드) ──
        for w in [card, lbl_img]:
            w.bind("<Button-1>",       lambda e, fp=filepath: self._md_press(e, fp))
            w.bind("<B1-Motion>",      self._md_motion)
            w.bind("<ButtonRelease-1>", lambda e, fp=filepath: self._md_release(e, fp))

        return card

    # ── 즐겨찾기 정렬/필터 옵션 저장 후 갱신 ─────────
    def _on_fav_filter(self):
        self.config["media_fav_top"]  = self.var_fav_top.get()
        self.config["media_fav_only"] = self.var_fav_only.get()
        save_config(self.config)
        self._build_media_grid()

    def _fav_view_active(self):
        return self.config.get("media_fav_top", False) or self.config.get("media_fav_only", False)

    # ── 미디어 카드 드래그 재정렬 ────────────────────
    def _md_press(self, e, fp):
        self._md_start   = (e.x_root, e.y_root)
        self._md_moved   = False
        try:
            self._md_idx = next(i for i, f in enumerate(self.favorites)
                                if f.get("path", "") == fp)
        except StopIteration:
            self._md_idx = None

    def _md_motion(self, e):
        if getattr(self, "_md_idx", None) is None:
            return
        # 정렬/필터 표시 중엔 드래그 순서변경 비활성(카드↔favorites 인덱스 불일치 방지)
        if self._fav_view_active():
            return
        if not self._md_moved:
            if abs(e.x_root - self._md_start[0]) < 6 and abs(e.y_root - self._md_start[1]) < 6:
                return
            self._md_moved = True
        tgt = self._card_index_at(e.x_root, e.y_root)
        if tgt is None or tgt == self._md_idx:
            return
        # favorites·카드 위젯 리스트 동시 재정렬
        self.favorites.insert(tgt, self.favorites.pop(self._md_idx))
        self._media_cards.insert(tgt, self._media_cards.pop(self._md_idx))
        self._md_idx = tgt
        self._place_media_cards()

    def _md_release(self, e, fp):
        if getattr(self, "_md_idx", None) is None:
            return
        if self._md_moved:
            save_favorites(self.favorites)   # 순서 영속화
        else:
            self._toggle_selection(fp)       # 이동 없으면 기존 클릭=선택
        self._md_idx   = None
        self._md_moved = False

    def _card_index_at(self, x_root, y_root):
        """마우스 아래 위젯 → 소속 미디어 카드 인덱스 (없으면 None)."""
        try:
            w = self.media_frm.winfo_containing(x_root, y_root)
        except Exception:
            return None
        cards = getattr(self, "_media_cards", [])
        while w is not None:
            if w in cards:
                return cards.index(w)
            w = getattr(w, "master", None)
        return None

    # ── 선택/해제 ────────────────────────────────
    def _toggle_selection(self, filepath):
        sel = self.config.get("selected_media", [])
        if filepath in sel:
            sel.remove(filepath)
        else:
            sel.append(filepath)
        self.config["selected_media"] = sel
        save_config(self.config)
        self._refresh_galleries()

    # ── 즐겨찾기 토글 (표시 플래그만 — 라이브러리 삭제 안 함) ─────
    def _toggle_favorite(self, filepath, name, tier):
        # 해당 미디어의 fav 플래그만 켜고/끔. 삭제는 ✕(_remove_favorite) 담당.
        for f in self.favorites:
            if f.get("path", "") == filepath:
                f["fav"] = not f.get("fav", False)
                break
        save_favorites(self.favorites)
        self._refresh_galleries()

    # ── 즐겨찾기 삭제 ───────────────────────────
    def _remove_favorite(self, filepath):
        L = self.config.get("language", "ko")
        # 프리셋에 저장된 미디어면 삭제 전 확인 (사용자 프리셋 selected_media 스캔)
        try:
            from ...persistence import load_user_presets
            _hit = [nm for nm, pv in load_user_presets().items()
                    if filepath in (pv.get("selected_media") or [])]
        except Exception:
            _hit = []
        if _hit:
            if not messagebox.askyesno(
                    t("dlg_del_title", L),
                    t("dlg_preset_media_del", L).format(names="', '".join(_hit)),
                    parent=self.root):
                return
        self.favorites = [f for f in self.favorites if f.get("path","") != filepath]
        save_favorites(self.favorites)
        # selected_media에서도 제거
        sel = self.config.get("selected_media", [])
        if filepath in sel:
            sel.remove(filepath)
            self.config["selected_media"] = sel
            save_config(self.config)
        self._refresh_galleries()

    # ── 사용자 파일 추가 (freemium 제한) ─────────
    def _count_media(self):
        """라이브러리 favorites를 확장자로 분류 → (영상수, 이미지수)."""
        v = i = 0
        for f in self.favorites:
            if f.get("type") == "builtin":
                continue   # 기본 제공 사용설명서는 갯수 제한에서 제외
            ext = Path(f.get("path", "")).suffix.lower()
            if ext in VIDEO_EXTS:
                v += 1
            elif ext in IMG_EXTS:
                i += 1
        return v, i

    def _add_user_media(self):
        L = self.config.get("language", "ko")
        is_premium = self.config.get("is_premium", False)
        tier        = TIER_CONFIG["premium" if is_premium else "free"]
        max_videos  = tier["max_videos"]
        max_images  = tier["max_images"]
        cur_v, cur_i = self._count_media()

        # 영상·이미지 둘 다 한도 도달 → 진입 차단
        if cur_v >= max_videos and cur_i >= max_images:
            # 한도 도달 안내 — 구매 유도 대신 '업데이트 예정' 통일
            messagebox.showinfo(t("lic_pro_guide", L), t("msg_pro_limit", L),
                                parent=self.root)
            return

        exts = " ".join(f"*{e}" for e in sorted(IMG_EXTS | VIDEO_EXTS))
        paths = filedialog.askopenfilenames(
            title=t("dlg_media_select", L),
            filetypes=[(t("ft_media", L), exts),
                       (t("ft_video", L), " ".join(f"*{e}" for e in sorted(VIDEO_EXTS))),
                       (t("ft_image", L),  " ".join(f"*{e}" for e in sorted(IMG_EXTS)))],
            parent=self.root
        )
        if not paths:
            return
        added = add_v = add_i = 0
        hit_v = hit_i = False        # 종류별 한도 도달 여부
        added_paths = []
        for p in paths:
            pp = Path(p)
            if any(f.get("path","") == str(pp) for f in self.favorites):
                continue
            ext = pp.suffix.lower()
            if ext in VIDEO_EXTS:
                if cur_v + add_v >= max_videos:
                    hit_v = True
                    continue
                add_v += 1
            elif ext in IMG_EXTS:
                if cur_i + add_i >= max_images:
                    hit_i = True
                    continue
                add_i += 1
            else:
                continue
            self.favorites.append({
                "name": pp.stem, "path": str(pp),
                "type": "user", "tier": "free",
                "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            added += 1
            added_paths.append(str(pp))
        if added:
            save_favorites(self.favorites)
            # 실제 추가된 파일만 자동 선택 (selected_media 동기화)
            sel = self.config.get("selected_media", [])
            for sp in added_paths:
                if sp not in sel:
                    sel.append(sp)
            self.config["selected_media"] = sel
            save_config(self.config)
            # 갤러리 갱신을 다이얼로그 콜백 밖(after_idle)으로 지연 → 네이티브 재진입 크래시 방지
            self.root.after_idle(self._refresh_galleries)

        # 일부 파일이 한도로 스킵됨 → 안내
        if hit_v or hit_i:
            # 한도 초과분 스킵 안내 — 구매 유도 대신 '업데이트 예정' 통일
            messagebox.showinfo(t("lic_pro_guide", L), t("msg_pro_limit", L),
                                parent=self.root)

    def _show_upgrade_dialog(self):
        """라이선스 키 입력 창 (추후 결제 연동)."""
        L = self.config.get("language", "ko")
        top = tk.Toplevel(self.root)
        top.title(t("dlg_pro_upgrade", L))
        top.resizable(False, False)
        tk.Label(top, text=t("lbl_enter_key", L), padx=16, pady=8).pack()
        var_key = tk.StringVar()
        ent = ttk.Entry(top, textvariable=var_key, width=32)
        ent.pack(padx=16, pady=4)
        ent.focus_set()

        def _apply():
            key = var_key.get().strip()
            if _verify_master(key):
                self.config["is_premium"] = True
                save_config(self.config)
                messagebox.showinfo(t("msg_success", L), t("msg_pro_on", L), parent=top)
                top.destroy()
                self._refresh_galleries()
            else:
                messagebox.showerror(t("msg_error", L), t("msg_invalid_key", L), parent=top)

        frm_btn = tk.Frame(top)
        frm_btn.pack(pady=(4, 12))
        ttk.Button(frm_btn, text=t("btn_ok", L), command=_apply, width=10).pack(side="left", padx=4)
        ttk.Button(frm_btn, text=t("btn_cancel2", L), command=top.destroy, width=10).pack(side="left", padx=4)

    # ── 갤러리 새로고침 ──────────────────────────
    def _refresh_galleries(self):
        if hasattr(self, '_thumb_photos'):
            self._thumb_photos.clear()
        self._build_media_grid()
        self._update_selection_label()

    # ── 선택 상태 라벨 갱신 ──────────────────────
    def _update_selection_label(self):
        L = self.config.get("language", "ko")
        sel = self.config.get("selected_media", [])
        cnt = len(sel)
        if cnt:
            names = [Path(fp).stem for fp in sel[:3]]
            txt = f"선택됨: {', '.join(names)}"
            if cnt > 3:
                txt += f" 외 {cnt-3}개"
            txt += f" ({cnt}개)"
        else:
            txt = t("lbl_no_media", L)
        if hasattr(self, 'lbl_selected'):
            self.lbl_selected.config(text=txt)
