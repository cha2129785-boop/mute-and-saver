# -*- coding: utf-8 -*-
"""
license_lang_tab — 라이선스 + 언어·정보 탭
⚠️ Mixin — ScreesaverApp에 다중상속됨. self 속성은 App.__init__에 정의.
"""
import logging
import os
import sys
import time
import json
import threading
import webbrowser
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

LOG = logging.getLogger("MuteAndSaver")

from ...i18n import t
from ...constants import (
    APP_VERSION, APP_DISPLAY, PRESETS, TIER_CONFIG,
    MEMO_BG_THEMES, CUSTOM_BGS_DIR, THUMBS_DIR, IMG_EXTS, VIDEO_EXTS,
    APP_AUTHOR_DISPLAY, ADMIN_UNLOCK_LEN, DONATE_URL, KAKAO_QR_PATH,
    LOG_PATH, APPDATA_DIR,
    GITHUB_API_LATEST, GITHUB_RELEASES_URL,

    LANGUAGES,)
from ...persistence import (
    load_config, save_config, load_favorites, save_favorites,
    load_memos, save_memos, load_user_themes, save_user_themes, get_all_themes,
)
from ...services import verify_pin, set_pin, clear_pin, _verify_admin, _verify_license, _generate_activation_code, _get_hardware_id, _verify_master
from ...media import generate_thumb, _safe_font
from ...platform.windows.monitor import _get_monitors_info


class LicenseLangTabMixin:
    def _build_tab_license(self):
        """💎 라이선스 탭 — 활성화 코드 입력 + 현재 상태 표시."""
        L = self.config.get("language", "ko")
        parent = self.tab_license
        for w in parent.winfo_children():
            w.destroy()

        is_premium = self.config.get("is_premium", False)
        hw_id      = _get_hardware_id()

        tk.Label(parent,
                 text=t("frm_license", L),
                 font=("Malgun Gothic", 14, "bold"),
                 fg="#5b8dee"
                 ).pack(pady=(20, 6))

        # 현재 상태
        status_text  = t("lic_pro_on", L) if is_premium else t("lic_free", L)
        status_color = "#34d399" if is_premium else "#9ca3af"
        tk.Label(parent, text=status_text,
                 fg=status_color, font=("Malgun Gothic", 13, "bold")
                 ).pack(pady=(0, 12))

        # 하드웨어 ID (구매 시 제공)
        frm_hw = ttk.LabelFrame(parent, text=t("frm_hwid", L), padding=(8, 4))
        frm_hw.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(frm_hw, text=hw_id,
                 fg="#e5e7eb", font=("Courier New", 13),
                 cursor="xterm"
                 ).pack(side="left")
        ttk.Button(frm_hw, text=t("btn_copy", L),
                   command=lambda: (
                       parent.clipboard_clear(),
                       parent.clipboard_append(hw_id),
                       tk.messagebox.showinfo(t("btn_copy", L), t("msg_hwid_copied", L))
                   )).pack(side="right")

        # 활성화 코드 입력
        frm_code = ttk.LabelFrame(parent, text=t("frm_activate", L), padding=(8, 4))
        frm_code.pack(fill="x", padx=20, pady=(0, 8))
        self.var_act_code = tk.StringVar(
            value=self.config.get("activation_code", "")
        )
        tk.Entry(frm_code, textvariable=self.var_act_code,
                 width=22, font=("Courier New", 13)
                 ).pack(side="left", padx=(0, 8))
        ttk.Button(frm_code, text=t("btn_activate", L),
                   command=self._activate_license
                   ).pack(side="left")

        # 관리자 코드 (Pro 강제 해제/재설정)
        # 히든 언락: 앱 어디서든 마스터 시크릿 타이핑(해시 검증) → 언어·정보 탭 작성자 이메일 클릭 시 노출
        if getattr(self, "_admin_section_shown", False):
            frm_adm = ttk.LabelFrame(parent, text=t("frm_admin", L), padding=(8, 4))
            frm_adm.pack(fill="x", padx=20, pady=(4, 0))
            self.var_admin_code = tk.StringVar()
            tk.Entry(frm_adm, textvariable=self.var_admin_code,
                     width=22, show="*", font=("Malgun Gothic", 13)
                     ).pack(side="left", padx=(0, 8))
            ttk.Button(frm_adm, text=t("lbl_admin_verify", L),
                       command=self._verify_admin_ui
                       ).pack(side="left")

        tk.Label(parent,
                 text=t("lbl_act_note", L),
                 fg="#6b7280", font=("Malgun Gothic", 13)
                 ).pack(pady=(12, 0))

    def _activate_license(self):
        """활성화 코드 로컬 HMAC 검증 → is_premium 설정."""
        L = self.config.get("language", "ko")
        code = self.var_act_code.get().strip()
        if not code:
            tk.messagebox.showwarning(t("btn_activate", L), t("msg_enter_code", L))
            return
        result = _verify_license({**self.config, "activation_code": code})
        if result:
            self.config["is_premium"]          = True
            self.config["activation_code"]     = code
            self.config["license_verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            save_config(self.config)
            tk.messagebox.showinfo(t("msg_act_done", L), t("msg_pro_on", L))
            self._build_tab_license()
        else:
            tk.messagebox.showerror(t("msg_act_fail", L),
                                    t("lic_invalid_code", L))

    def _verify_admin_ui(self):
        """관리자 코드 PBKDF2 검증 → Pro 강제 설정 / 초기화."""
        L = self.config.get("language", "ko")
        code = self.var_admin_code.get().strip()
        if not code:
            return
        if _verify_admin(code):
            # 관리자 확인 시 Pro 토글
            self.config["is_premium"] = not self.config.get("is_premium", False)
            save_config(self.config)
            state = "ON" if self.config["is_premium"] else "OFF"
            tk.messagebox.showinfo(t("frm_admin", L), f"✅ Pro {state}")
            self._build_tab_license()
        else:
            tk.messagebox.showerror(t("frm_admin", L), t("msg_invalid_key", L))
        self.var_admin_code.set("")

    # ── 관리자 키 히든 언락 ──────────────────────
    def _on_admin_secret_keypress(self, event=None):
        """앱 내 아무 위젯에 타이핑해도 감지 (root.bind_all). 시크릿 완성 시 클릭 대기 상태로 전환."""
        ch = getattr(event, "char", "")
        if not ch or not ch.isprintable():
            return
        # 슬라이딩 윈도우 유지 → 평문 비교 대신 PBKDF2 해시 검증(_verify_master) 재사용
        self._admin_secret_buf = (self._admin_secret_buf + ch)[-ADMIN_UNLOCK_LEN:]
        if len(self._admin_secret_buf) == ADMIN_UNLOCK_LEN and _verify_master(self._admin_secret_buf):
            self._admin_unlock_armed = True
            self._admin_secret_buf = ""

    def _on_admin_email_click(self, event=None):
        """언어·정보 탭 작성자 이메일 라벨 클릭. armed 상태일 때만 라이선스(관리자) 탭 노출."""
        if not getattr(self, "_admin_unlock_armed", False):
            return  # 시크릿 미입력 상태 — 아무 반응 없음 (숨김 유지)
        self._admin_unlock_armed = False
        self._admin_section_shown = True
        # 숨긴 라이선스 탭 복원 (세션 한정 — 재시작 시 다시 숨김)
        try:
            self.nb.add(self.tab_license)
        except Exception:
            pass
        self._build_tab_license()
        try:
            self.nb.select(self.tab_license)
        except Exception:
            pass

    def _build_tab_lang(self):
        parent = self.tab_lang
        for w in parent.winfo_children():
            w.destroy()

        cur_lang = self.config.get("language", "ko")

        # ── 언어 선택 ─────────────────────────
        frm_lang = ttk.LabelFrame(
            parent, text=" " + t("lang_label", cur_lang) + " ",
            padding=(10, 8)
        )
        frm_lang.pack(fill="x", pady=(0, 8))

        self.var_language = tk.StringVar(value=cur_lang)
        for code, name in LANGUAGES:
            ttk.Radiobutton(
                frm_lang, text=name,
                variable=self.var_language, value=code,
                command=self._on_language_change
            ).pack(anchor="w", pady=1)

        # ── About 정보 ────────────────────────
        frm_about = ttk.LabelFrame(
            parent, text=" " + t("about_title", cur_lang) + " ",
            padding=(10, 8)
        )
        frm_about.pack(fill="both", expand=True, pady=(0, 4))

        tk.Label(
            frm_about, text=APP_DISPLAY,
            font=("Arial", 13, "bold"), fg="#2980b9"
        ).pack(anchor="w")

        info_text = (
            f"{t('version', cur_lang)}: v{APP_VERSION}\n"
            f"{t('author', cur_lang)}: {APP_AUTHOR_DISPLAY}\n"
            f"{t('copyright', cur_lang)}"
        )
        lbl_info = tk.Label(
            frm_about, text=info_text,
            font=("Arial", 13), fg="#555555", justify="left"
        )
        lbl_info.pack(anchor="w", pady=(4, 0))
        # 히든 언락 트리거 — 시크릿 문자열 입력 후 이 제작자 라벨 클릭 → 라이선스 탭 노출
        lbl_info.bind("<Button-1>", self._on_admin_email_click)

        # ── 업데이트 확인 (옵트인 수동) — 클릭 시에만 GitHub 릴리스 조회 ──
        upd_row = tk.Frame(frm_about)
        upd_row.pack(fill="x", pady=(8, 0))
        self._upd_btn = ttk.Button(
            upd_row, text=t("btn_check_update", cur_lang),
            command=self._check_update, width=20)
        self._upd_btn.pack(side="left")
        self._upd_status = tk.Label(
            upd_row, text="", font=("Arial", 12), fg="#888888")
        self._upd_status.pack(side="left", padx=(8, 0))

        # 로그 경로 (버그 리포트용)
        log_frame = tk.Frame(frm_about)
        log_frame.pack(fill="x", pady=(8, 0))

        tk.Label(
            log_frame, text=f"{t('log_path', cur_lang)}:",
            font=("Arial", 13), fg="#888888"
        ).pack(anchor="w")

        log_path_str = str(LOG_PATH.parent)
        tk.Label(
            log_frame, text=log_path_str,
            font=("Consolas", 13), fg="#666666",
            wraplength=360, justify="left"
        ).pack(anchor="w")

        ttk.Button(
            log_frame, text=t("open_log_dir", cur_lang),
            command=self._open_log_folder, width=20
        ).pack(anchor="w", pady=(4, 0))

        # ── 설정 백업 / 복원 ─────────────────────────
        bk_frame = ttk.LabelFrame(frm_about, text=" " + t("frm_backup", cur_lang) + " ",
                                  padding=(10, 6))
        bk_frame.pack(fill="x", pady=(12, 0))
        bk_row = tk.Frame(bk_frame); bk_row.pack(fill="x")
        ttk.Button(bk_row, text=t("btn_backup", cur_lang),
                   command=self._backup_settings, width=20).pack(side="left")
        ttk.Button(bk_row, text=t("btn_restore", cur_lang),
                   command=self._restore_settings, width=20).pack(side="left", padx=(8, 0))
        tk.Label(bk_frame, text=t("lbl_backup_hint", cur_lang),
                 font=("Malgun Gothic", 11), fg="#888888", justify="left",
                 wraplength=420).pack(anchor="w", pady=(4, 0))

        # ── 후원(도네이션) ─────────────────────────
        # "유용하셨다면 ❤️" 버튼 클릭 → 후원 방법 선택 팝업
        donate_frame = tk.Frame(frm_about)
        donate_frame.pack(fill="x", pady=(12, 0))
        ttk.Button(
            donate_frame, text=t("donate_note", cur_lang),
            command=lambda: self._open_donate_choice(cur_lang), width=30
        ).pack(anchor="w")

    # ── 언어 변경 핸들러 ─────────────────────────
    def _on_language_change(self):
        new_lang = self.var_language.get()
        old_lang = self.config.get("language", "ko")
        if new_lang == old_lang:
            return
        self.config["language"] = new_lang
        save_config(self.config)
        LOG.info(f"언어 변경: {old_lang} → {new_lang}")
        # 모든 탭 즉시 재빌드 (FIX: 언어 미적용 문제)
        self._retranslate_ui()

    # ── FIX (언어 즉시 반영): 모든 탭 재빌드 ─────
    def _retranslate_ui(self):
        """언어 변경 시 모든 위젯 텍스트 즉시 갱신"""
        try:
            cur_lang = self.config.get("language", "ko")
            self.root.title(f"{APP_DISPLAY} v{APP_VERSION}")
            # 탭 라벨 갱신
            tab_labels = {
                "ko": (" \u2699 설정 ", " \u2328 단축키 ", " \U0001F310 언어\u00B7정보 "),
                "en": (" \u2699 Settings ", " \u2328 Hotkey ", " \U0001F310 Language\u00B7Info "),
                "zh": (" \u2699 设置 ", " \u2328 快捷键 ", " \U0001F310 语言\u00B7信息 "),
                "ja": (" \u2699 設定 ", " \u2328 ショートカット ", " \U0001F310 言語\u00B7情報 "),
                "ru": (" \u2699 Настройки ", " \u2328 Горячая клавиша ", " \U0001F310 Язык\u00B7Инфо "),
            }
            labels = tab_labels.get(cur_lang, tab_labels["ko"])
            try:
                self.nb.tab(self.tab_setting, text=labels[0])
                self.nb.tab(self.tab_media,   text=t("tab_media", cur_lang))
                self.nb.tab(self.tab_hotkey,  text=labels[1])
                self.nb.tab(self.tab_memo,    text=t("tab_memo", cur_lang))
                self.nb.tab(self.tab_license, text=t("tab_license", cur_lang))
                self.nb.tab(self.tab_lang,    text=labels[2])
            except Exception:
                pass
            # 각 탭 콘텐츠 재빌드
            self._build_tab_setting()
            self._build_tab_media()
            self._build_tab_hotkey()
            self._build_tab_memo()
            self._build_tab_license()
            self._build_tab_lang()
            self.root.update_idletasks()
        except Exception as e:
            LOG.error(f"_retranslate_ui 오류: {e}")

    # ── 설정 전체 백업 / 복원 ─────────────────────
    _BACKUP_ITEMS = ["config.json", "memo.json", "favorites.json",
                     "user_themes.json", "user_presets.json"]

    def _backup_settings(self):
        """설정·메모·즐겨찾기·테마·프리셋 + 사용자 이미지(custom_bgs)를 zip으로 저장."""
        import zipfile
        L = self.config.get("language", "ko")
        default = f"MuteAndSaver_backup_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        try:
            path = filedialog.asksaveasfilename(
                parent=self.root, title=t("btn_backup", L),
                defaultextension=".zip", initialfile=default,
                filetypes=[("Zip", "*.zip")])
        except Exception:
            path = None
        if not path:
            return
        try:
            # 저장 직전 현재 설정 반영
            save_config(self.config)
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for name in self._BACKUP_ITEMS:
                    fp = APPDATA_DIR / name
                    if fp.exists():
                        z.write(fp, name)
                cbg = APPDATA_DIR / "custom_bgs"
                if cbg.is_dir():
                    for f in cbg.rglob("*"):
                        if f.is_file():
                            z.write(f, str(f.relative_to(APPDATA_DIR)))
            messagebox.showinfo(t("btn_backup", L),
                                t("msg_backup_done", L).format(path=path),
                                parent=self.root)
            LOG.info(f"[Backup] 설정 백업 완료: {path}")
        except Exception as e:
            LOG.error(f"[Backup] 백업 실패: {e}")
            messagebox.showerror(t("btn_backup", L),
                                 t("msg_backup_fail", L), parent=self.root)

    def _restore_settings(self):
        """백업 zip을 선택 → 현재 데이터 폴더에 복원(덮어쓰기). 재시작 후 적용."""
        import zipfile
        L = self.config.get("language", "ko")
        try:
            path = filedialog.askopenfilename(
                parent=self.root, title=t("btn_restore", L),
                filetypes=[("Zip", "*.zip")])
        except Exception:
            path = None
        if not path:
            return
        if not messagebox.askyesno(t("btn_restore", L),
                                   t("msg_restore_confirm", L), parent=self.root):
            return
        try:
            with zipfile.ZipFile(path, "r") as z:
                # 경로 탈출 방지 — 이름 정규화 후 APPDATA_DIR 하위만 허용
                base = APPDATA_DIR.resolve()
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    dest = (APPDATA_DIR / info.filename).resolve()
                    if base not in dest.parents and dest != base:
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(dest, "wb") as out:
                        out.write(src.read())
            messagebox.showinfo(t("btn_restore", L),
                                t("msg_restore_done", L), parent=self.root)
            LOG.info(f"[Restore] 설정 복원 완료: {path}")
        except Exception as e:
            LOG.error(f"[Restore] 복원 실패: {e}")
            messagebox.showerror(t("btn_restore", L),
                                 t("msg_restore_fail", L), parent=self.root)

    # ── 후원 방법 선택 팝업 ──────────────────────
    def _open_donate_choice(self, L):
        """[Buy Me a Coffee] | [카카오페이] 선택 팝업."""
        dlg = tk.Toplevel(self.root)
        dlg.title(t("donate_note", L))
        dlg.transient(self.root)
        dlg.resizable(False, False)
        win_w, win_h = 380, 300
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"{win_w}x{win_h}+{(sw-win_w)//2}+{(sh-win_h)//2}")

        tk.Label(dlg, text=t("donate_choose", L),
                 font=("Malgun Gothic", 13), justify="left",
                 wraplength=win_w - 40).pack(padx=20, pady=(16, 14))
        ttk.Button(
            dlg, text=t("btn_donate", L), width=30,
            command=lambda: (dlg.destroy(), self._open_donate(DONATE_URL))
        ).pack(pady=4)
        ttk.Button(
            dlg, text=t("btn_donate_kakao", L), width=30,
            command=lambda: (dlg.destroy(), self._show_kakao_qr(L))
        ).pack(pady=4)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        try:
            dlg.grab_set()
        except Exception:
            pass

    # ── 카카오페이 QR 팝업 (버튼 클릭 시) ────────────
    def _show_kakao_qr(self, L):
        """카카오페이 후원 QR을 팝업 창으로 표시 (폰으로 스캔)."""
        try:
            from PIL import Image, ImageTk
            with Image.open(str(KAKAO_QR_PATH)) as im:
                im = im.convert("RGB").resize((300, 300), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
        except Exception as e:
            LOG.warning(f"카카오 QR 로드 실패: {e}")
            messagebox.showinfo(t("btn_donate_kakao", L),
                                "(QR 이미지를 불러올 수 없습니다)", parent=self.root)
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(t("btn_donate_kakao", L))
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.configure(bg="#FEE500")
        win_w, win_h = 380, 560
        sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
        dlg.geometry(f"{win_w}x{win_h}+{(sw-win_w)//2}+{(sh-win_h)//2}")

        tk.Label(dlg, text=t("kakao_scan_note", L),
                 font=("Malgun Gothic", 13), fg="#3c1e1e", bg="#FEE500",
                 wraplength=win_w - 40, justify="left"
                 ).pack(padx=20, pady=(16, 10))
        lbl = tk.Label(dlg, image=photo, bg="#FEE500")
        lbl.image = photo               # GC 방지 참조 유지
        self._kakao_qr_photo = photo
        lbl.pack()
        ttk.Button(dlg, text=t("btn_close", L),
                   command=dlg.destroy, width=12).pack(pady=(12, 0))
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        try:
            dlg.grab_set()
        except Exception:
            pass

    # ── 후원 링크 열기 ──────────────────────────
    def _open_donate(self, url=None):
        target = url or DONATE_URL
        try:
            import webbrowser
            webbrowser.open(target)
            LOG.info(f"후원 링크 열기: {target}")
        except Exception as e:
            LOG.error(f"후원 링크 열기 실패: {e}")

    # ── 로그 폴더 열기 ──────────────────────────
    def _open_log_folder(self):
        try:
            import subprocess
            log_dir = str(LOG_PATH.parent)
            if sys.platform == "win32":
                os.startfile(log_dir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", log_dir])
            else:
                subprocess.Popen(["xdg-open", log_dir])
            LOG.info(f"로그 폴더 열기: {log_dir}")
        except Exception as e:
            LOG.error(f"로그 폴더 열기 실패: {e}")

    # ── 업데이트 확인 (옵트인 수동) ──────────────────────────
    @staticmethod
    def _ver_tuple(s):
        """'vX.Y.Z' → (X,Y,Z) 정수 튜플. 접두 v·부가문자 무시."""
        import re
        nums = re.findall(r"\d+", s or "")
        return tuple(int(n) for n in nums[:3]) if nums else (0,)

    def _check_update(self):
        """클릭 시에만 GitHub 릴리스 조회(백그라운드 스레드). 사용자 데이터 미전송."""
        L = self.config.get("language", "ko")
        try:
            self._upd_btn.config(state="disabled")
            self._upd_status.config(text=t("upd_checking", L), fg="#888888")
        except Exception:
            return
        threading.Thread(target=self._do_check_update, args=(L,), daemon=True).start()

    def _do_check_update(self, L):
        latest, err = None, None
        try:
            req = urllib.request.Request(
                GITHUB_API_LATEST,
                headers={"Accept": "application/vnd.github+json",
                         "User-Agent": "MuteAndSaver"})   # GitHub API는 UA 필수
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            latest = data.get("tag_name") or ""
        except Exception as e:
            err = str(e)
            LOG.warning(f"[Update] 확인 실패: {e}")
        # UI 갱신은 메인 스레드에서
        try:
            self.root.after(0, lambda: self._apply_update_result(L, latest, err))
        except Exception:
            pass

    def _apply_update_result(self, L, latest, err):
        try:
            if not self._upd_btn.winfo_exists():
                return
            self._upd_btn.config(state="normal")
        except Exception:
            return
        if err or not latest:
            self._upd_status.config(text=t("upd_error", L), fg="#c0392b")
            return
        if self._ver_tuple(latest) > self._ver_tuple(APP_VERSION):
            self._upd_status.config(text=latest, fg="#27ae60")
            if messagebox.askyesno(APP_DISPLAY,
                                   t("upd_available", L).format(v=latest)):
                webbrowser.open(GITHUB_RELEASES_URL)
        else:
            self._upd_status.config(text=t("upd_latest", L), fg="#888888")
