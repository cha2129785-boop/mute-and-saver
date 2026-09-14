# -*- coding: utf-8 -*-
"""
memo_tab — 메모보드 탭 + 테마/블러
⚠️ Mixin — ScreesaverApp에 다중상속됨. self 속성은 App.__init__에 정의.
"""
import logging
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

LOG = logging.getLogger("MuteAndSaver")

from ...i18n import t
from ...constants import (
    APP_VERSION, APP_DISPLAY, PRESETS, TIER_CONFIG,
    MEMO_BG_THEMES, CUSTOM_BGS_DIR, THUMBS_DIR, IMG_EXTS, VIDEO_EXTS,
)
from ...persistence import (
    load_config, save_config, load_favorites, save_favorites,
    load_memos, save_memos, load_user_themes, save_user_themes, get_all_themes,
)
from ...services import verify_pin, set_pin, clear_pin, _verify_admin, _verify_license, _generate_activation_code, _get_hardware_id
from ...media import generate_thumb, _safe_font
from ...platform.windows.monitor import _get_monitors_info
from ...features.memo.editor import FullscreenMemoEditor


class MemoTabMixin:
    def _build_tab_memo(self):
        L = self.config.get("language", "ko")
        parent = self.tab_memo
        for w in parent.winfo_children():
            w.destroy()
        # 기존 에디터 파기
        if getattr(self, '_editor', None):
            try:
                self._editor.destroy()
            except Exception:
                pass
            self._editor = None

        # ── Zero-Dashboard 런처 UI ────────────────
        # DashboardEditor 완전 제거 → 런처 버튼 + 현황 요약만 존재
        # 좌표 동기화 로직 불필요 — FSEditor가 실제 픽셀 기준으로 모든 편집 종결
        frm_launch = tk.Frame(parent, bg="#0d0f18")
        frm_launch.pack(fill="both", expand=True, padx=8, pady=8)

        tk.Label(frm_launch,
                 text=t("btn_memo_edit", L),
                 fg="#e5e7eb", bg="#0d0f18",
                 font=("Malgun Gothic", 15, "bold")
                 ).pack(pady=(20, 6))

        tk.Label(frm_launch,
                 text=("실제 모니터 해상도 위에서 메모를 직접 배치합니다.\n"
                       "위치·크기·내용·글꼴·색상을 실제 화면에서 편집하고 저장하세요.\n"
                       "저장한 내용은 화면보호기 실행 시 오차 없이 그대로 표시됩니다."),
                 fg="#9ca3af", bg="#0d0f18",
                 font=("Malgun Gothic", 13),
                 justify="center"
                 ).pack(pady=(0, 16))

        frm_edit_row = tk.Frame(frm_launch, bg="#0d0f18")
        frm_edit_row.pack(pady=(0, 8))
        tk.Button(frm_edit_row,
                  text=t("btn_memo_edit", L),
                  bg="#5b8dee", fg="white",
                  font=("Malgun Gothic", 13, "bold"),
                  command=self._open_fullscreen_editor,
                  relief="flat", padx=14, pady=10,
                  cursor="hand2"
                  ).pack(side="left", padx=(0, 6))
        tk.Button(frm_edit_row,
                  text=t("btn_export_txt", L),
                  bg="#5b8dee", fg="white",
                  font=("Malgun Gothic", 13, "bold"),
                  command=self._export_memos_txt,
                  relief="flat", padx=14, pady=10,
                  cursor="hand2"
                  ).pack(side="left")

        frm_set_row = tk.Frame(frm_launch, bg="#0d0f18")
        frm_set_row.pack(pady=(0, 8))
        tk.Button(frm_set_row,
                  text=t("btn_memo_set_save", L),
                  bg="#3a3f4b", fg="#e5e7eb",
                  font=("Malgun Gothic", 13),
                  command=self._export_memo_set,
                  relief="flat", padx=12, pady=6,
                  cursor="hand2"
                  ).pack(side="left", padx=(0, 6))
        tk.Button(frm_set_row,
                  text=t("btn_memo_set_load", L),
                  bg="#3a3f4b", fg="#e5e7eb",
                  font=("Malgun Gothic", 13),
                  command=self._import_memo_set,
                  relief="flat", padx=12, pady=6,
                  cursor="hand2"
                  ).pack(side="left")

        # 배경 테마 설정 (MemoBoardViewer가 사용)
        frm_theme = tk.Frame(frm_launch, bg="#0d0f18")
        frm_theme.pack(pady=(14, 0))
        tk.Label(frm_theme, text=t("lbl_memo_bg", L),
                 fg="#9ca3af", bg="#0d0f18",
                 font=("Malgun Gothic", 13)).pack(side="left")

        all_themes = get_all_themes()
        cur_key    = self.config.get("memo_bg_theme", "paper")
        # 내장 테마는 t()로 번역, 사용자 테마는 원래 label 유지
        _builtin = {"white","grid","paper","forest","ocean"}
        def _theme_display(k, v):
            return t("theme_" + k, L) if k in _builtin else v.get("label", k)
        _display_list = [_theme_display(k, v) for k, v in all_themes.items()]
        self._theme_display_map = dict(zip(_display_list, all_themes.keys()))
        cur_display = _theme_display(cur_key, all_themes.get(cur_key, {}))
        self.var_memo_theme = tk.StringVar(value=cur_display)
        self._theme_cb = ttk.Combobox(
            frm_theme, textvariable=self.var_memo_theme,
            values=_display_list,
            state="readonly", width=12
        )
        self._theme_cb.pack(side="left", padx=(4, 4))
        self.var_memo_theme.trace_add("write", self._on_memo_theme_change)

        # 이미지 배경 추가 버튼
        tk.Button(frm_theme, text=t("btn_add_image", L),
                  bg="#374151", fg="#e5e7eb",
                  font=("Malgun Gothic", 13),
                  relief="flat", padx=4,
                  command=self._add_image_theme
                  ).pack(side="left", padx=(0, 2))

        # 사용자 이미지 테마 삭제 버튼
        tk.Button(frm_theme, text="🗑",
                  bg="#374151", fg="#e5e7eb",
                  font=("Malgun Gothic", 13),
                  relief="flat", padx=4,
                  command=self._delete_image_theme
                  ).pack(side="left")

        # fit_mode 선택 (사용자 이미지 테마 전용)
        self._fit_mode_values = {"contain": t("fit_contain", L),
                                  "cover":   t("fit_cover", L),
                                  "stretch": t("fit_stretch", L)}
        self._fit_mode_rev = {v: k for k, v in self._fit_mode_values.items()}
        cur_theme = all_themes.get(cur_key, {})
        cur_fit   = cur_theme.get("fit_mode", "contain")
        self.var_fit_mode = tk.StringVar(value=self._fit_mode_values.get(cur_fit, t("fit_contain", L)))
        self._fit_cb = ttk.Combobox(
            frm_theme, textvariable=self.var_fit_mode,
            values=list(self._fit_mode_values.values()),
            state="readonly" if cur_theme.get("user_defined") else "disabled",
            width=9
        )
        self._fit_cb.pack(side="left", padx=(4, 0))
        self.var_fit_mode.trace_add("write", self._on_fit_mode_change)

        # 회전 (90도 단위, 사용자 이미지 테마 전용) — °기호라 번역 불필요
        self._rotate_values = ["0°", "90°", "180°", "270°"]
        cur_rot = int(cur_theme.get("rotate", 0)) % 360
        self.var_rotate = tk.StringVar(value=f"{cur_rot}°")
        self._rotate_cb = ttk.Combobox(
            frm_theme, textvariable=self.var_rotate,
            values=self._rotate_values,
            state="readonly" if cur_theme.get("user_defined") else "disabled",
            width=5
        )
        self._rotate_cb.pack(side="left", padx=(4, 0))
        self.var_rotate.trace_add("write", self._on_rotate_change)

        # 메모 조정: 투명도 + 배경블러(토글/강도) — 가로 1줄, 슬라이더 제거·Entry 입력만
        frm_adjust = tk.Frame(frm_launch, bg="#0d0f18")
        frm_adjust.pack(pady=(6, 0))

        # --- 투명도 ---
        tk.Label(frm_adjust, text=t("lbl_opacity", L),
                 fg="#9ca3af", bg="#0d0f18",
                 font=("Malgun Gothic", 13)).pack(side="left")
        # __init__에서 선언된 변수 .set() 동기화 (재선언 금지)
        self.var_memo_opacity.set(self.config.get("memo_opacity", 0.0))
        self.var_memo_opacity_str.set(str(int(self.var_memo_opacity.get() * 100)))

        def _on_opacity_entry_change(event=None):
            if getattr(self, '_updating_opacity', False):
                return
            try:
                val_int = int(self.var_memo_opacity_str.get())
                if 10 <= val_int <= 100:
                    self._updating_opacity = True
                    self.var_memo_opacity.set(val_int / 100.0)
                    self.config["memo_opacity"] = val_int / 100.0
                    save_config(self.config)
                    self._updating_opacity = False
            except ValueError:
                pass

        ent_opacity = tk.Entry(
            frm_adjust, width=4,                       # ⚠️ 12pt 폭 — Windows 실측 검증 필요
            font=("Malgun Gothic", 12),
            justify="center",
            textvariable=self.var_memo_opacity_str
        )
        ent_opacity.pack(side="left", padx=(4, 2))
        ent_opacity.bind("<Return>",   _on_opacity_entry_change)
        ent_opacity.bind("<FocusOut>", _on_opacity_entry_change)
        tk.Label(frm_adjust, text="%",
                 fg="#9ca3af", bg="#0d0f18",
                 font=("Malgun Gothic", 13)).pack(side="left", padx=(0, 12))

        # --- 배경 블러 토글 + 강도 ---
        self.var_memo_blur = tk.BooleanVar(
            value=self.config.get("memo_bg_blur", False)
        )
        ttk.Checkbutton(
            frm_adjust,
            text=t("lbl_blur_effect", L),
            variable=self.var_memo_blur,
            command=self._on_memo_blur_change
        ).pack(side="left")
        tk.Label(frm_adjust, text=t("lbl_pil_needed", L),
                 fg="#6b7280", bg="#0d0f18",
                 font=("Malgun Gothic", 13)
                 ).pack(side="left", padx=(4, 8))
        # 핑퐁 루프 방어: _updating_blur 플래그로 상호 갱신 시 단 1회만 실행
        tk.Label(frm_adjust, text=t("lbl_blur_str", L),
                 fg="#9ca3af", bg="#0d0f18",
                 font=("Malgun Gothic", 13)).pack(side="left")
        self.var_blur_radius = tk.IntVar(
            value=self.config.get("memo_blur_radius", 1)
        )
        self._updating_blur = False   # 핑퐁 루프 방어 플래그
        self._ent_blur = tk.Entry(
            frm_adjust, width=4,                       # ⚠️ 12pt 폭 — Windows 실측 검증 필요
            font=("Malgun Gothic", 12),
            justify="center"
        )
        self._ent_blur.insert(0, str(self.var_blur_radius.get()))
        self._ent_blur.pack(side="left", padx=(4, 2))
        tk.Label(frm_adjust, text="(0~10)",
                 fg="#6b7280", bg="#0d0f18",
                 font=("Malgun Gothic", 13)).pack(side="left")
        self._ent_blur.bind("<Return>",   lambda e: self._on_blur_entry_change())
        self._ent_blur.bind("<FocusOut>", lambda e: self._on_blur_entry_change())

        # (현재 메모 현황 요약 섹션 제거 — 사용자 요청)

        # 보조 모니터 안내
        tk.Label(parent,
                 text=t("lbl_dual_sync", L),
                 fg="#888888", font=("Arial", 13)
                 ).pack(anchor="w", padx=4, pady=(4, 0))

    def _open_fullscreen_editor(self):
        """FullscreenMemoEditor 실행 — Singleton 보장."""
        L = self.config.get("language", "ko")
        # ── Singleton 체크 — 고스트 인스턴스 방어 ──────
        existing = getattr(self, '_fs_editor', None)
        if existing:
            try:
                if existing.overlay.winfo_exists():
                    existing.overlay.lift()
                    existing.overlay.focus_force()
                    return
            except Exception:
                pass
            self._fs_editor = None

        # 모드 무관 편집 허용 — 단축키 경로와 동작 통일 (memo/split 아니어도 실행)
        monitors = _get_monitors_info()
        self._fs_editor = FullscreenMemoEditor(self, monitors)

    def _export_memo_set(self):
        """현재 메모 전체를 .json 세트 파일로 저장."""
        L = self.config.get("language", "ko")
        import json as _json
        memos = load_memos()
        if not memos:
            tk.messagebox.showinfo(t("btn_memo_set_save", L), t("msg_no_memo", L), parent=self.root)
            return
        fpath = filedialog.asksaveasfilename(
            title=t("btn_memo_set_save", L),
            defaultextension=".json", initialfile="memo_set.json",
            filetypes=[("Memo Set", "*.json")], parent=self.root
        )
        if not fpath:
            return
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                _json.dump({"schema_version": 2, "memos": memos}, f, ensure_ascii=False, indent=2)
            tk.messagebox.showinfo(t("btn_memo_set_save", L),
                t("msg_memo_set_saved", L).format(n=len(memos)), parent=self.root)
        except Exception as e:
            tk.messagebox.showerror(t("msg_error", L), str(e), parent=self.root)

    def _import_memo_set(self):
        """세트 .json 불러와 현재 메모를 교체 (교체 전 자동 백업)."""
        L = self.config.get("language", "ko")
        import json as _json, time as _time
        from ...constants import APPDATA_DIR
        fpath = filedialog.askopenfilename(
            title=t("btn_memo_set_load", L),
            filetypes=[("Memo Set", "*.json"), ("All", "*.*")], parent=self.root
        )
        if not fpath:
            return
        try:
            with open(fpath, encoding="utf-8") as f:
                data = _json.load(f)
            new_memos = data.get("memos", []) if isinstance(data, dict) else data
            if not isinstance(new_memos, list):
                tk.messagebox.showerror(t("msg_error", L), t("msg_memo_set_invalid", L), parent=self.root)
                return
        except Exception as e:
            tk.messagebox.showerror(t("msg_error", L), str(e), parent=self.root)
            return
        if not tk.messagebox.askyesno(t("btn_memo_set_load", L),
                t("msg_memo_set_confirm", L).format(n=len(new_memos)), parent=self.root):
            return
        # 교체 전 현재 메모 자동 백업
        try:
            cur = load_memos()
            bak = APPDATA_DIR / f"memo_backup_{int(_time.time())}.json"
            with open(bak, "w", encoding="utf-8") as f:
                _json.dump({"schema_version": 2, "memos": cur}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        save_memos(new_memos)
        self._refresh_memo_summary()
        tk.messagebox.showinfo(t("btn_memo_set_load", L),
            t("msg_memo_set_loaded", L).format(n=len(new_memos)), parent=self.root)

    def _export_memos_txt(self):
        """메모를 제목별 개별 txt로 내보내기 (created_at 순, utf-8-sig)."""
        L = self.config.get("language", "ko")
        import re as _re

        memos = load_memos()
        if not memos:
            tk.messagebox.showinfo(t("btn_export_txt", L), t("msg_no_memo", L), parent=self.root)
            return

        dst_dir = filedialog.askdirectory(title=t("dlg_export_dir", L))
        if not dst_dir:
            return

        memos_sorted = sorted(memos, key=lambda m: m.get("created_at", ""))
        _used = {}          # 파일명 중복 방지 (세션 내)
        plan = []           # (fpath, title, body)
        for m in memos_sorted:
            title = (m.get("title") or "").strip() or t("lbl_untitled", L)
            body  = m.get("body", "")
            # 파일시스템 금지문자 제거 + 길이 제한(50)
            safe = _re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip()[:50] or "memo"
            n = _used.get(safe, 0) + 1
            _used[safe] = n
            fname = f"{safe}.txt" if n == 1 else f"{safe}_{n}.txt"
            plan.append((Path(dst_dir) / fname, title, body))

        saved = 0
        for fpath, title, body in plan:
            # 파일별 개별 덮어쓰기 확인 — 예=덮어씀 / 아니오=건너뜀
            if fpath.exists() and not tk.messagebox.askyesno(
                t("btn_export_txt", L),
                t("msg_overwrite_confirm", L).format(name=fpath.name),
                parent=self.root
            ):
                continue
            try:
                with open(fpath, "w", encoding="utf-8-sig") as f:
                    f.write(f"{title}\n\n{body}")
                saved += 1
            except Exception as e:
                LOG.warning(f"[Export] {fpath.name} 저장 실패: {e}")

        tk.messagebox.showinfo(
            t("msg_success", L),
            t("msg_export_done", L).format(n=saved, dir=dst_dir),
            parent=self.root
        )
        LOG.info(f"[Export] TXT {saved}개 저장 → {dst_dir}")

    def _refresh_memo_summary(self):
        """FSEditor 저장 후 호출 — 메모 현황 텍스트 갱신."""
        L = self.config.get("language", "ko")
        try:
            memos = load_memos()
            lbl   = getattr(self, '_memo_summary_lbl', None)
            if not lbl:
                return
            if not memos:
                lbl.config(text=t("lbl_no_memo", L))
                return
            lines = []
            for m in memos[:5]:
                title = m.get("title", t("lbl_title_none", L))[:22]
                pin   = "📌 " if m.get("pinned")    else ""
                col   = "📁 " if m.get("collapsed") else ""
                lines.append(f"  {pin}{col}{title}")
            if len(memos) > 5:
                lines.append(f"  ... 외 {len(memos)-5}개")
            lbl.config(text="\n".join(lines))
        except Exception:
            pass

    def _add_editor_memo(self):
        if getattr(self, '_editor', None):
            self._editor.add_memo()

    def _on_blur_scale_change(self, val=None):
        """
        Scale 변경 → Entry 동기화 + 적용.
        핑퐁 가드: _updating_blur 플래그로 Entry→Scale→Entry 무한 루프 방지.
        """
        if getattr(self, '_updating_blur', False):
            return
        radius = int(float(self.var_blur_radius.get()))
        self._updating_blur = True
        try:
            # Entry 값이 다를 때만 갱신 (가드 조건)
            if hasattr(self, '_ent_blur'):
                current = self._ent_blur.get()
                if current != str(radius):
                    self._ent_blur.delete(0, "end")
                    self._ent_blur.insert(0, str(radius))
        finally:
            self._updating_blur = False
        self._apply_blur_radius(radius)

    def _on_blur_entry_change(self):
        """
        Entry 변경 → 클램핑(0~10) → Scale 동기화 + 적용.
        핑퐁 가드: _updating_blur 플래그로 Scale→Entry→Scale 무한 루프 방지.
        비숫자 입력 → 직전 유효값으로 복원.
        """
        if getattr(self, '_updating_blur', False):
            return
        try:
            raw = self._ent_blur.get().strip()
            if not raw.lstrip('-').isdigit():
                raise ValueError
            val = max(0, min(10, int(raw)))   # 클램핑 (0~10)
        except (ValueError, AttributeError):
            # 비숫자 → 직전 유효값으로 복원
            val = self.config.get("memo_blur_radius", 1)

        self._updating_blur = True
        try:
            # Entry 보정값 반영
            if hasattr(self, '_ent_blur'):
                self._ent_blur.delete(0, "end")
                self._ent_blur.insert(0, str(val))
            # Scale 값이 다를 때만 갱신 (가드 조건)
            if hasattr(self, 'var_blur_radius'):
                if self.var_blur_radius.get() != val:
                    self.var_blur_radius.set(val)
        finally:
            self._updating_blur = False
        self._apply_blur_radius(val)

    def _apply_blur_radius(self, radius: int):
        """공통 후처리: config 저장 + 블러 캐시 무효화. radius 0~10 저장."""
        self.config["memo_blur_radius"] = radius
        save_config(self.config)
        # 블러 캐시 무효화 → 다음 render() 시 재계산
        if hasattr(self, '_screensaver') and self._screensaver:
            viewer = getattr(self._screensaver, '_memo_viewer', None)
            if viewer:
                viewer._blur_cache      = None
                viewer._blur_cache_size = (0, 0)

    def _on_memo_blur_change(self):
        """블러 토글 변경 → config 저장 + 블러 캐시 무효화."""
        val = getattr(self, 'var_memo_blur', None)
        if val is None:
            return
        self.config["memo_bg_blur"] = val.get()
        save_config(self.config)
        # 블러 캐시 무효화 — 다음 render() 시 재계산
        if hasattr(self, '_screensaver') and self._screensaver:
            viewer = getattr(self._screensaver, '_memo_viewer', None)
            if viewer:
                viewer._blur_cache      = None
                viewer._blur_cache_size = (0, 0)

    def _add_image_theme(self):
        """
        사용자 이미지 배경 추가.
        Copy & Isolate: 선택 이미지를 custom_bgs/ 에 복사 → 원본 삭제 무관.
        """
        L = self.config.get("language", "ko")
        import tkinter.filedialog as _fd
        import shutil, uuid as _uuid

        path = _fd.askopenfilename(
            title=t("dlg_bg_image", L),
            filetypes=[(t("ft_imgfile", L), "*.jpg *.jpeg *.png *.bmp *.webp *.gif")]
        )
        if not path:
            return

        LOG.info(f"[Theme_Registry] 🛑 사용자 테마 등록 요청 — 원본 경로: {path}")

        # 1. 파일 물리적 존재 여부 검증
        if not Path(path).exists():
            LOG.error(f"[Theme_Registry] 🚨 파일이 디스크에 존재하지 않음: {path}")
            tk.messagebox.showerror(t("msg_error", L), t("msg_file_404", L) + "\n" + str(path), parent=self.root)
            return

        # 이름 입력 다이얼로그
        import tkinter.simpledialog as _sd
        name = _sd.askstring(
            t("lbl_theme_name", L), t("msg_enter_theme", L),
            initialvalue=Path(path).stem,
            parent=self.root
        )
        if not name or not name.strip():
            return
        name = name.strip()[:30]
        LOG.info(f"[Theme_Registry] -> 테마 이름: '{name}'")

        # 2. Copy & Isolate
        try:
            CUSTOM_BGS_DIR.mkdir(parents=True, exist_ok=True)
            uid      = _uuid.uuid4().hex[:8]
            # ⚠️ 복사본 파일명은 순수 ASCII(uid+확장자)로 — 한글/공백 경로 네이티브 크래시 차단.
            #    원본명은 theme label에 보존되므로 파일명에 불필요.
            _ext     = Path(path).suffix.lower() or ".png"
            dst_name = f"{uid}{_ext}"
            dst_path = CUSTOM_BGS_DIR / dst_name
            LOG.info(f"[Theme_Registry] 2. 복사본 생성 중: {dst_path}")
            shutil.copy2(path, dst_path)
            if not dst_path.exists():
                raise FileNotFoundError(f"복사 후 파일 미확인: {dst_path}")
            LOG.info(f"[Theme_Registry] 2. ✅ 복사 완료 — 복사본 크기: {dst_path.stat().st_size} bytes")
        except Exception as e:
            LOG.error(f"[Theme_Registry] 🚨 이미지 복사 실패: {e}")
            tk.messagebox.showerror(t("msg_error", L), t("msg_img_fail", L) + "\n" + str(e), parent=self.root)
            return

        # 3. user_themes.json 에 등록
        user_themes = load_user_themes()
        theme_key   = f"user_{uid}"
        theme_data  = {
            "label":        name,
            "bg_type":      "image",
            "image_path":   str(dst_path),
            "fit_mode":     "contain",
            "rotate":       0,
            "user_defined": True,
        }
        user_themes[theme_key] = theme_data
        LOG.info(f"[Theme_Registry] 3. 메모리 등록 완료: {theme_data}")
        save_user_themes(user_themes)
        LOG.info(f"[Theme_Registry] 3. ✅ user_themes.json 저장 완료")

        # 4. Combobox + config 갱신
        self.config["memo_bg_theme"] = theme_key
        save_config(self.config)
        self._refresh_theme_combobox(select_key=theme_key)
        LOG.info(f"[Theme_Registry] 🏁 테마 등록 완전 완료: key={theme_key} name={name}")

    def _delete_image_theme(self):
        """
        현재 선택된 사용자 정의 테마 삭제.
        내장 테마 삭제 불가 (user_defined=True인 것만 허용).
        복사본 파일도 함께 삭제 (고아 파일 방지).
        """
        L = self.config.get("language", "ko")
        import shutil
        cur_key    = self.config.get("memo_bg_theme", "paper")
        all_themes = get_all_themes()
        theme      = all_themes.get(cur_key, {})

        if not theme.get("user_defined", False):
            tk.messagebox.showinfo(
                t("lbl_theme_del_err", L), t("msg_builtin_no_del", L), parent=self.root
            )
            return

        # 테마 표시명: 역매핑에서 조회 (내장=번역명, 사용자=원래이름)
        _disp_map = getattr(self, '_theme_display_map', {})
        _rev_map  = {v: k for k, v in _disp_map.items()}
        theme_display = _rev_map.get(cur_key, theme.get('label', cur_key))

        if not tk.messagebox.askyesno(
            t("lbl_theme_del", L),
            f"'{theme_display}'\n" + t("lbl_theme_del_msg", L),
            parent=self.root
        ):
            return

        # 복사본 파일 삭제
        img_path = theme.get("image_path", "")
        if img_path:
            try:
                Path(img_path).unlink(missing_ok=True)
            except Exception as e:
                LOG.warning(f"[UserTheme] 이미지 파일 삭제 실패: {e}")

        # user_themes.json 에서 제거
        user_themes = load_user_themes()
        user_themes.pop(cur_key, None)
        save_user_themes(user_themes)

        # 기본 테마로 폴백
        self.config["memo_bg_theme"] = "paper"
        save_config(self.config)
        self._refresh_theme_combobox(select_key="paper")
        LOG.info(f"[UserTheme] 테마 삭제: {cur_key}")

    def _refresh_theme_combobox(self, select_key: str = ""):
        """
        Combobox 값 목록 갱신 + 선택 테마 반영.
        ⚠️ var_memo_theme.set() → trace_add("write") → _on_memo_theme_change 발동
        → 무한 루프 방지: _theme_switching_now 플래그로 재진입 차단
        """
        # 루프 차단 플래그 설정 — trace 콜백이 다시 들어와도 즉시 return
        if getattr(self, '_theme_switching_now', False):
            LOG.warning("[Theme_Freeze_Check] ⚠️ 중복 진입 감지 → 무한 루프 차단")
            return
        self._theme_switching_now = True
        LOG.info(f"[Theme_Freeze_Check] 🛑 Combobox 갱신 시작: select_key={select_key}")
        try:
            L = self.config.get("language", "ko")
            all_themes = get_all_themes()
            _builtin = {"white","grid","paper","forest","ocean"}
            def _td(k, v):
                return t("theme_" + k, L) if k in _builtin else v.get("label", k)
            _display_list = [_td(k, v) for k, v in all_themes.items()]
            self._theme_display_map = dict(zip(_display_list, all_themes.keys()))
            if hasattr(self, '_theme_cb'):
                self._theme_cb["values"] = _display_list
            target_display = _td(select_key, all_themes.get(select_key, {})) if select_key in all_themes else _display_list[0] if _display_list else ""
            if hasattr(self, 'var_memo_theme'):
                LOG.info(f"[Theme_Freeze_Check] -> var_memo_theme.set('{target_display}')")
                self.var_memo_theme.set(target_display)
                LOG.info("[Theme_Freeze_Check] ✅ Combobox 갱신 완료")
        finally:
            self._theme_switching_now = False   # 반드시 해제

    def _on_fit_mode_change(self, *_):
        """fit_mode 콤보박스 변경 → user_themes.json의 해당 테마 fit_mode 갱신."""
        if not hasattr(self, 'var_fit_mode'):
            return
        display = self.var_fit_mode.get()
        fit_val = getattr(self, '_fit_mode_rev', {}).get(display)
        if not fit_val:
            return
        theme_key = self.config.get("memo_bg_theme", "paper")
        user_themes = load_user_themes()
        theme = user_themes.get(theme_key)
        if theme and theme.get("user_defined"):
            theme["fit_mode"] = fit_val
            save_user_themes(user_themes)
            LOG.info(f"[FitMode] {theme_key} → {fit_val}")

    def _on_rotate_change(self, *_):
        """회전 콤보 변경 → user_themes.json rotate 갱신 (fit_mode와 동일: 저장 후 재실행 반영)."""
        if not hasattr(self, 'var_rotate'):
            return
        try:
            rot_val = int(self.var_rotate.get().rstrip("°"))
        except ValueError:
            return
        if rot_val not in (0, 90, 180, 270):
            return
        theme_key = self.config.get("memo_bg_theme", "paper")
        user_themes = load_user_themes()
        theme = user_themes.get(theme_key)
        if theme and theme.get("user_defined"):
            theme["rotate"] = rot_val
            save_user_themes(user_themes)
            LOG.info(f"[Rotate] {theme_key} → {rot_val}°")

    def _on_memo_theme_change(self, *_):
        """
        배경 테마 콤보박스 변경 → config 저장.
        _theme_switching_now True = _refresh_theme_combobox 내부에서 발동된 것
        → 무한 루프 차단을 위해 즉시 return.
        """
        # 루프 차단 — Combobox 갱신 중 trace 발동 시 무시
        if getattr(self, '_theme_switching_now', False):
            LOG.debug("[Theme_Freeze_Check] trace 발동 무시 (Combobox 갱신 중)")
            return

        if not hasattr(self, 'var_memo_theme'):
            return
        label      = self.var_memo_theme.get()
        all_themes = get_all_themes()
        # 역매핑으로 내부 key 조회 (번역 표시명 → 내부 key)
        key = getattr(self, '_theme_display_map', {}).get(label)
        if not key:
            key = next(
                (k for k, v in all_themes.items() if v.get("label") == label),
                "paper"
            )
        LOG.info(f"[Theme_Freeze_Check] 🛑 테마 변경 감지: '{label}' → key={key}")
        theme = all_themes.get(key, {})

        # 이미지 테마 사전 진단 (응답 없음 예방)
        if theme.get("bg_type") == "image":
            img_path = theme.get("image_path", "")
            LOG.info(f"[Theme_Freeze_Check] 1. 이미지 테마 경로: {img_path}")
            if img_path and Path(img_path).exists():
                try:
                    size = Path(img_path).stat().st_size
                    LOG.info(f"[Theme_Freeze_Check] 2. 파일 크기: {size//1024}KB")
                    if size > 10 * 1024 * 1024:   # 10MB 초과 경고
                        LOG.warning(
                            f"[Theme_Freeze_Check] ⚠️ 대용량 이미지({size//1024//1024}MB) — "
                            "LANCZOS 리사이즈 중 응답 없음 발생 가능"
                        )
                except Exception:
                    pass
            elif img_path:
                LOG.error(f"[Theme_Freeze_Check] 🚨 이미지 파일 없음: {img_path}")

        self.config["memo_bg_theme"] = key
        save_config(self.config)
        LOG.info(f"[Theme_Freeze_Check] ✅ 테마 변경 저장 완료: {key}")

        # fit_mode 콤보박스 동기화
        if hasattr(self, '_fit_cb') and hasattr(self, '_fit_mode_values'):
            is_user = theme.get("user_defined", False)
            self._fit_cb.config(state="readonly" if is_user else "disabled")
            cur_fit = theme.get("fit_mode", "contain")
            display = self._fit_mode_values.get(cur_fit, self._fit_mode_values.get("contain", ""))
            self.var_fit_mode.set(display)

        # 회전 콤보박스 동기화 — 테마 전환 시 항상 0° 초기화 (이전 설정값 미표시·미기억)
        if hasattr(self, '_rotate_cb') and hasattr(self, 'var_rotate'):
            is_user = theme.get("user_defined", False)
            self._rotate_cb.config(state="readonly" if is_user else "disabled")
            self.var_rotate.set("0°")   # → trace → _on_rotate_change 가 rotate=0 저장
