# -*- coding: utf-8 -*-
"""
hotkey_tab — 단축키 탭 + 캡처/검증
⚠️ Mixin — ScreesaverApp에 다중상속됨. self 속성은 App.__init__에 정의.
"""
import logging
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

LOG = logging.getLogger("MuteAndSaver")

_HAS_WIN32 = False
try:
    import win32api
    import win32con
    import win32gui
    _HAS_WIN32 = True
except ImportError:
    pass

from ..window_utils import center_window
from ...i18n import t
from ...constants import (
    APP_VERSION, APP_DISPLAY, PRESETS, TIER_CONFIG,
    MEMO_BG_THEMES, CUSTOM_BGS_DIR, THUMBS_DIR, IMG_EXTS, VIDEO_EXTS,

    MODIFIER_ONLY, RECOMMENDED_HOTKEYS, RESERVED_HOTKEYS,
    DEFAULT_SS_HOTKEY, DEFAULT_QM_HOTKEY,)
from ...persistence import (
    load_config, save_config, load_favorites, save_favorites,
    load_memos, save_memos, load_user_themes, save_user_themes, get_all_themes,
)
from ...services import verify_pin, set_pin, clear_pin, _verify_admin, _verify_license, _generate_activation_code, _get_hardware_id
from ...media import generate_thumb, _safe_font
from ...platform.windows.monitor import _get_monitors_info
from ...platform.windows.tray import TrayHotkeySystem


class HotkeyTabMixin:
    # 단축키 탭 공통 폰트 (식별력 향상: 본문 13 / 보조 13 / 현재값 18)
    _HK_FNT      = ("Malgun Gothic", 13)
    _HK_FNT_SM   = ("Malgun Gothic", 13)
    _HK_FNT_DISP = ("Consolas", 18, "bold")

    def _build_tab_hotkey(self):
        parent = self.tab_hotkey
        L = self.config.get("language", "ko")
        for w in parent.winfo_children():
            w.destroy()

        # ttk 위젯 글자 크기 통일 (라디오/버튼)
        _style = ttk.Style()
        _style.configure("HK.TRadiobutton", font=self._HK_FNT)
        _style.configure("HK.TButton", font=self._HK_FNT_SM)

        FNT, FSM, FDISP = self._HK_FNT, self._HK_FNT_SM, self._HK_FNT_DISP

        if not _HAS_WIN32:
            tk.Label(parent, text=t("warn_no_win32", L),
                     fg="#e67e22", font=FSM, justify="center").pack(pady=(0, 6))

        # 초기 모드 (기본 단축키와 일치하면 default)
        cur_ss = self.config.get("hotkey_screensaver", DEFAULT_SS_HOTKEY)
        self.var_hk_mode = tk.StringVar(
            value="default" if cur_ss == DEFAULT_SS_HOTKEY else "custom")
        self.var_qm_hk_mode.set(self.config.get("qm_hotkey_mode", "default"))
        self.var_qm_hotkey_disp.set(
            self._fmt_hotkey(self.config.get("hotkey_quick_memo", DEFAULT_QM_HOTKEY)))

        def _make_card(title, disp_var, mode_var, default_key, mode_cmd,
                        cap_cmd, save_cmd, example_key):
            """화면보호기·퀵메모 공통 카드 — 완전 동일 레이아웃."""
            card = ttk.LabelFrame(parent, text=" " + title + " ", padding=(14, 12))
            card.pack(fill="x", padx=4, pady=(0, 12))

            # 1줄: 현재 <값>
            top = tk.Frame(card); top.pack(fill="x")
            tk.Label(top, text=t("lbl_hk_current", L) + " :",
                     font=FSM, fg="#888888").pack(side="left")
            tk.Label(top, textvariable=disp_var,
                     font=FDISP, fg="#2980b9").pack(side="left", padx=(8, 0))

            # 2줄: 모드 라디오 (기본값/직접)
            mrow = tk.Frame(card); mrow.pack(fill="x", pady=(10, 2))
            is_custom = mode_var.get() == "custom"
            ttk.Radiobutton(
                mrow, style="HK.TRadiobutton",
                text=t("rb_default_fmt", L).format(k=self._fmt_hotkey(default_key)),
                variable=mode_var, value="default", command=mode_cmd
            ).pack(side="left", padx=(0, 18))
            ttk.Radiobutton(
                mrow, style="HK.TRadiobutton", text=t("rb_hk_custom", L),
                variable=mode_var, value="custom", command=mode_cmd
            ).pack(side="left")

            # 3줄: 입력란 + 캡처 버튼 + 상태 라벨 (양 카드 대칭)
            irow = tk.Frame(card); irow.pack(fill="x", pady=(8, 2))
            st = "normal" if is_custom else "disabled"
            entry = ttk.Entry(irow, width=24, font=FSM)
            entry.pack(side="left")
            capbtn = ttk.Button(irow, style="HK.TButton",
                                text=t("btn_key_capture", L),
                                command=cap_cmd, state=st)
            capbtn.pack(side="left", padx=(8, 0))
            status_lbl = tk.Label(irow, text="", font=FSM, fg="#666666")
            status_lbl.pack(side="left", padx=(8, 0))
            # 예시
            tk.Label(card, text=t(example_key, L),
                     font=FSM, fg="#999999").pack(anchor="w", pady=(2, 0))

            # 4줄: 저장
            ttk.Separator(card, orient="horizontal").pack(fill="x", pady=(10, 8))
            ttk.Button(card, style="HK.TButton",
                       text=t("btn_save_hotkey", L),
                       command=save_cmd).pack(anchor="e")
            return card, entry, capbtn, status_lbl

        # ── 화면보호기 단축키 카드 ──
        _, self.entry_hotkey, self.btn_capture, self.lbl_capture_status = _make_card(
            t("frm_ss_hotkey", L), self.var_hotkey_disp, self.var_hk_mode,
            DEFAULT_SS_HOTKEY, self._on_hk_mode_change,
            self._start_hotkey_capture, self._apply_hotkey_save, "lbl_hk_example")
        self.entry_hotkey.config(textvariable=self.var_hotkey)
        self.frm_capture = self.btn_capture.master
        if self.var_hk_mode.get() == "custom":
            self.lbl_capture_status.config(text=t("lbl_hk_guide_arrow", L))
        self.var_hotkey.set(getattr(self, "temp_new_hotkey", "") or "")
        _restore = self.temp_new_hotkey or ""
        self.root.after(50, lambda v=_restore: self.var_hotkey.set(v))
        self.btn_save_hotkey = None   # (하위호환 — 참조 방지)

        # ── 퀵 메모 단축키 카드 ──
        _, self.entry_qm_hotkey, self.btn_qm_cap, self.lbl_qm_capture_status = _make_card(
            t("frm_qm_hotkey", L), self.var_qm_hotkey_disp, self.var_qm_hk_mode,
            DEFAULT_QM_HOTKEY, self._on_qm_mode_change,
            self._start_qm_hotkey_capture, self._apply_qm_hotkey_save, "lbl_qm_example")
        self.entry_qm_hotkey.config(textvariable=self.var_qm_hotkey)
        self.var_qm_hotkey.set(
            self.config.get("hotkey_quick_memo", DEFAULT_QM_HOTKEY)
            if self.var_qm_hk_mode.get() == "custom" else "")
        if self.var_qm_hk_mode.get() == "custom":
            self.lbl_qm_capture_status.config(text=t("lbl_hk_guide_arrow", L))

    # ── 표시용 포맷 ─────────────────────────────
    _HK_SYM = {
        "semicolon": ";", "space": "Space", "grave": "`", "comma": ",",
        "period": ".", "slash": "/", "minus": "-", "equal": "=",
        "bracketleft": "[", "bracketright": "]", "backslash": "\\",
        "apostrophe": "'", "plus": "+",
    }

    def _fmt_hotkey(self, hk: str) -> str:
        if not hk:
            return "(없음)"
        out = []
        for p in hk.split("+"):
            low = p.strip().lower()
            out.append(self._HK_SYM.get(low, p.strip().capitalize()))
        return " + ".join(out)

    # ── 모드 변경 ──────────────────────────────
    def _on_hk_mode_change(self):
        L = self.config.get("language", "ko")
        # 캡처 진행 중에는 모드 변경 차단 (race 방어)
        try:
            if str(self.btn_capture.cget("state")) == "disabled" and \
               self.var_hk_mode.get() == "custom":
                pass  # custom으로 막 변경된 경우는 정상
        except Exception:
            pass

        if self.var_hk_mode.get() == "default":
            self.btn_capture.config(state="disabled")
            self.lbl_capture_status.config(text="")
            if self.config.get("hotkey_screensaver") != DEFAULT_SS_HOTKEY:
                self.config["hotkey_screensaver"] = DEFAULT_SS_HOTKEY
                save_config(self.config)
                self.var_hotkey_disp.set(self._fmt_hotkey(DEFAULT_SS_HOTKEY))
                self._reregister_hotkey()
                LOG.info(f"단축키 → 기본값({DEFAULT_SS_HOTKEY})")
        else:
            self.btn_capture.config(state="normal")
            self.lbl_capture_status.config(
                text=t("lbl_hk_guide_arrow", L), fg="#666666"
            )

    # ── 퀵 메모 단축키 핸들러 ───────────────────
    def _on_qm_mode_change(self):
        """라디오 버튼 변경 시 버튼 상태 + 커널 재등록. 프로그램적 변경 시 가드로 차단."""
        if getattr(self, '_updating_qm_ui_now', False):
            return
        L = self.config.get("language", "ko")
        mode    = self.var_qm_hk_mode.get()
        old_key = self.config.get("hotkey_quick_memo", DEFAULT_QM_HOTKEY)
        self.config["qm_hotkey_mode"] = mode
        # 버튼 상태 갱신
        if hasattr(self, 'btn_qm_cap') and self.btn_qm_cap:
            try:
                if self.btn_qm_cap.winfo_exists():
                    self.btn_qm_cap.config(
                        state="disabled" if mode == "default" else "normal"
                    )
            except Exception:
                pass
        # 상태 라벨 (화면보호기 카드와 동일 동작)
        if hasattr(self, 'lbl_qm_capture_status') and self.lbl_qm_capture_status:
            try:
                if self.lbl_qm_capture_status.winfo_exists():
                    self.lbl_qm_capture_status.config(
                        text=t("lbl_hk_guide_arrow", L) if mode == "custom" else "")
            except Exception:
                pass
        target_key = DEFAULT_QM_HOTKEY if mode == "default" else self.config.get("hotkey_quick_memo", DEFAULT_QM_HOTKEY)
        if old_key != target_key:
            self.config["hotkey_quick_memo"] = target_key
            save_config(self.config)
            self.var_qm_hotkey_disp.set(self._fmt_hotkey(target_key))
            if hasattr(self, '_tray_hk') and self._tray_hk:
                self._tray_hk.register_quick_memo_hotkey(target_key)
                LOG.info(f"[QuickMemo] 모드 변경 → 단축키 재적용: [{target_key}]")

    def _start_qm_hotkey_capture(self):
        """퀵 메모 전용 키 캡처 모달 (Toplevel + grab_set)."""
        L = self.config.get("language", "ko")
        if getattr(self, '_is_capturing_qm', False):
            return
        self._is_capturing_qm = True
        cap = tk.Toplevel(self.root)
        cap.title(t("lbl_qm_cap_title", L))
        cap.geometry("340x140")
        cap.resizable(False, False)
        cap.transient(self.root)
        tk.Label(
            cap,
            text=t("lbl_capture_title", L),
            font=("Malgun Gothic", 13), justify="center"
        ).pack(expand=True, fill="both", padx=12, pady=18)
        cap.grab_set()
        cap.focus_force()
        cap.bind("<Key>", lambda e: self._on_qm_key_captured_modal(e, cap))
        cap.protocol("WM_DELETE_WINDOW", lambda: self._close_qm_capture_modal(cap))

    def _on_qm_key_captured_modal(self, event, dialog_win):
        """퀵 메모 키 캡처 인라인 파서 (Ctrl 필수 + ALLOWED 필터)."""
        try:
            if event.keysym == "Escape":
                self._close_qm_capture_modal(dialog_win)
                return
            state    = event.state
            is_ctrl  = bool(state & 0x0004)
            if not is_ctrl:
                return
            key_char = event.keysym.lower()
            if key_char in ("control_l","control_r","shift_l","shift_r",
                            "alt_l","alt_r","caps_lock","win_l","win_r"):
                return
            ALLOWED_SPECIALS = {
                "space","semicolon","quoteleft","grave",
                "backslash","bracketright","bracketleft",
                "minus","equal","apostrophe","comma","period","slash"
            }
            is_valid_special = key_char in ALLOWED_SPECIALS
            is_pure_alpha    = (len(key_char) == 1 and 'a' <= key_char <= 'z')
            is_valid_fkey    = (key_char.startswith('f') and key_char[1:].isdigit()
                                and 3 <= int(key_char[1:]) <= 12)
            if not (is_valid_special or is_pure_alpha or is_valid_fkey):
                return
            mods = ["ctrl"]
            if state & 0x0001: mods.append("shift")
            if state & 0x0008: mods.append("alt")
            parsed_key = "+".join(mods) + "+" + key_char
            self.config["qm_hotkey_mode"]   = "custom"
            self.config["hotkey_quick_memo"] = parsed_key
            save_config(self.config)
            if hasattr(self, '_tray_hk') and self._tray_hk:
                self._tray_hk.register_quick_memo_hotkey(parsed_key)
            self.var_qm_hotkey_disp.set(self._fmt_hotkey(parsed_key))
            # 연쇄 발동 차단 후 라디오 상태 갱신
            self._updating_qm_ui_now = True
            self.var_qm_hk_mode.set("custom")
            self._updating_qm_ui_now = False
            LOG.info(f"[QuickMemo] 단축키 캡처 완료: [{parsed_key}]")
            self._close_qm_capture_modal(dialog_win)
        except Exception as e:
            LOG.error(f"[QuickMemo] 캡처 파싱 오류: {e}")
            self._close_qm_capture_modal(dialog_win)

    def _close_qm_capture_modal(self, dialog_win):
        """캡처 모달 grab 해제 + 파괴."""
        try:
            if dialog_win and dialog_win.winfo_exists():
                dialog_win.grab_release()
                dialog_win.destroy()
        except Exception:
            pass
        self._is_capturing_qm = False

    # ── 단축키 캡처 (Tkinter KeyPress 바인딩) ─────
    def _start_hotkey_capture(self):
        L = self.config.get("language", "ko")
        if not _HAS_WIN32:
            messagebox.showwarning(
                t("lbl_pywin32", L),
                t("lbl_pywin32_msg", L),
                parent=self.root
            )
            return

        # 캡처 다이얼로그 (KeyPress 받을 수 있음)
        top = tk.Toplevel(self.root)
        top.title(t("dlg_key_wait", L))
        top.transient(self.root)
        top.grab_set()
        top.resizable(False, False)

        win_w, win_h = 360, 180
        sw = top.winfo_screenwidth()
        sh = top.winfo_screenheight()
        x = (sw - win_w) // 2
        y = (sh - win_h) // 2
        top.geometry(f"{win_w}x{win_h}+{x}+{y}")

        frm = tk.Frame(top, padx=20, pady=18)
        frm.pack(fill="both", expand=True)

        tk.Label(
            frm, text="\U0001F3AF",
            font=("Arial", 28)
        ).pack()
        tk.Label(
            frm, text=t("lbl_capture_press", L),
            font=("Arial", 13)
        ).pack(pady=(4, 2))
        lbl_preview = tk.Label(
            frm, text=t("lbl_capture_mod", L),
            font=("Consolas", 13, "bold"), fg="#2980b9"
        )
        lbl_preview.pack()
        tk.Label(
            frm, text=t("lbl_capture_esc", L),
            font=("Arial", 13), fg="#888888"
        ).pack(pady=(8, 0))

        self._hk_capture_top = top
        top.bind("<KeyPress>", lambda e: self._on_capture_key(e, lbl_preview, top))
        top.protocol("WM_DELETE_WINDOW", top.destroy)
        top.focus_force()

    def _on_capture_key(self, event, lbl_preview, top):
        L = self.config.get("language", "ko")
        # ESC = 취소
        if event.keysym == "Escape":
            top.destroy()
            return

        # 수식키 단독 입력 무시
        if event.keysym in ("Control_L","Control_R","Alt_L","Alt_R",
                            "Shift_L","Shift_R","Win_L","Win_R",
                            "Super_L","Super_R","Meta_L","Meta_R",
                            "Num_Lock","Caps_Lock","Hangul","Hangul_Hanja"):
            return

        # Ctrl만 엄격하게 확인 (0x4 비트만 — Alt/NumLock 오인 완전 차단)
        is_ctrl = bool(event.state & 0x0004)
        if not is_ctrl:
            lbl_preview.config(text=t("lbl_ctrl_required", L), fg="#e74c3c")
            return

        # 허용 키 목록 (Ctrl 조합만)
        ALLOWED = {
            "space": "space",
            "semicolon": ";", "quoteleft": "`", "grave": "`",
            "backslash": "\\", "bracketright": "]", "bracketleft": "[",
            "minus": "-", "equal": "=", "apostrophe": "'",
            "comma": ",", "period": ".", "slash": "/",
        }
        # F3~F12 도 허용
        ks = event.keysym.lower()
        if ks in {f"f{i}" for i in range(3, 13)}:
            char = ks
        else:
            char = ALLOWED.get(ks)

        if not char:
            lbl_preview.config(
                text=t("msg_invalid_keysym", L).format(key=event.keysym),
                fg="#e74c3c"
            )
            return

        # Alt 등 다른 수식키는 무조건 제거 — 강제로 ctrl+char만 구성
        hk_norm = f"ctrl+{char}"
        lbl_preview.config(text=self._fmt_hotkey(hk_norm), fg="#2980b9")
        top.after(400, lambda: self._finalize_capture(hk_norm, top))

    def _finalize_capture(self, hk_norm, top):
        try:
            if top.winfo_exists():
                top.destroy()
        except Exception:
            pass
        self._on_hotkey_captured(hk_norm)

    def _on_hotkey_captured(self, hk):
        L = self.config.get("language", "ko")
        print(f"🔍 [추적 1] 캡처 함수 진입, 넘어온 값: '{hk}'")
        if not hk:
            if hasattr(self, "lbl_capture_status"):
                self.lbl_capture_status.config(
                    text=t("lbl_capture_fail", L), fg="#e74c3c"
                )
            if hasattr(self, "btn_capture"):
                self.btn_capture.config(state="normal")
            return

        hk_norm = self._normalize_hotkey(hk)
        try:
            ok, reason = self._validate_hotkey(hk_norm, target_type="screensaver")
        except Exception as e:
            LOG.error(f"[추적] _validate_hotkey 예외 발생: {e}")
            print(f"❌ [추적] _validate_hotkey 예외: {e}")
            ok, reason = False, str(e)

        if ok:
            self._hk_capture_fail = 0
            print(f"🔍 [추적 2] 유효성 검사 통과, root에 저장 시작: '{hk_norm}'")
            # ⭐ 절대 파괴되지 않는 메인 창(root)에 강제 주입
            self.root._immortal_hotkey = hk_norm
            # 기존 저장소도 병행 유지
            self.config["_draft_hotkey"] = hk_norm
            self.temp_new_hotkey = hk_norm
            print(f"🔍 [추적 3] root 저장 완료: '{getattr(self.root, '_immortal_hotkey', '증발함!')}'")
            # StringVar 동기화 + after(50) 재주입
            self.var_hotkey.set(hk_norm)
            self.var_hotkey_disp.set(self._fmt_hotkey(hk_norm))
            self.root.after(50, lambda v=hk_norm: self.var_hotkey.set(v))
            if hasattr(self, "lbl_capture_status"):
                self.lbl_capture_status.config(
                    text=t("lbl_capture_ok", L),
                    fg="#f39c12"
                )
            LOG.info(f"단축키 캡처 임시 저장: {hk_norm}")
        else:
            self._hk_capture_fail += 1
            if hasattr(self, "lbl_capture_status"):
                self.lbl_capture_status.config(
                    text=f"\u26A0 {reason} ({self._hk_capture_fail}/3)",
                    fg="#e74c3c"
                )
            if self._hk_capture_fail >= 3:
                self._show_hotkey_recommendations()
                self._hk_capture_fail = 0

        if hasattr(self, "btn_capture"):
            self.btn_capture.config(state="normal")

    def _apply_hotkey_save(self):
        """[저장] 버튼 클릭 — root 문신 → config 대기실 → StringVar 순서."""
        L = self.config.get("language", "ko")
        is_default = hasattr(self, "var_hk_mode") and self.var_hk_mode.get() == "default"

        if is_default:
            target = DEFAULT_SS_HOTKEY
        else:
            # 0순위: root에 새긴 불멸 값
            target = getattr(self.root, "_immortal_hotkey", "").strip()
            print(f"🔍 [추적 4] 저장 버튼 누름! root에서 꺼낸 값: '{target}'")

            # 1순위: config 대기실
            if not target:
                target = self.config.get("_draft_hotkey", "").strip()
                print(f"💾 [저장 시도] 대기실에서 꺼낸 값: '{target}'")

            # 2순위: StringVar
            if not target and hasattr(self, "var_hotkey") and self.var_hotkey.get().strip():
                target = self.var_hotkey.get().strip()

            # 3순위: Entry 위젯 직접 읽기
            if not target and hasattr(self, "entry_hotkey") and self.entry_hotkey.get().strip():
                target = self.entry_hotkey.get().strip()

            target = target.lower()
            LOG.info(f"[DEBUG] 최종 확인된 저장 값: '{target}'")

            if not target:
                messagebox.showwarning(t("msg_warning", L),
                    t("msg_hk_no_key", L),
                    parent=self.root)
                return

        # 시스템 등록 먼저 — 성공 시에만 저장
        if getattr(self, "_tray_hk", None):
            ok = self._tray_hk.update_hotkey(target)
            if not ok:
                messagebox.showerror(t("msg_error", L),
                    t("msg_hk_reg_fail", L).format(target=target),
                    parent=self.root)
                return

        # 대기실 값을 진짜 설정으로 승격
        self.config["hotkey_screensaver"] = target
        self.config["_draft_hotkey"] = ""
        self.root._immortal_hotkey = ""
        self.temp_new_hotkey = None
        save_config(self.config)

        self.var_hotkey.set("")
        self.var_hotkey_disp.set(self._fmt_hotkey(target))
        if hasattr(self, "lbl_capture_status"):
            self.lbl_capture_status.config(text=t("lbl_save_done", L), fg="#27ae60")
        messagebox.showinfo(t("msg_hk_saved", L),
                            t("msg_hk_saved_fmt", L).format(target=target),
                            parent=self.root)
        LOG.info(f"단축키 저장 완료: {target}")

    # ── 정규화 ─────────────────────────────────
    def _normalize_hotkey(self, hk: str) -> str:
        parts = [p.strip().lower() for p in hk.split("+") if p.strip()]
        order = {"ctrl":0,"alt":1,"shift":2,"windows":3,"cmd":3,"meta":3}
        mods = sorted([p for p in parts if p in order], key=lambda x: order[x])
        keys = [p for p in parts if p not in order]
        return "+".join(mods + keys)

    # ── 유효성 검사 ─────────────────────────────
    def _validate_hotkey(self, hk: str, target_type: str = "screensaver"):
        # OEM 특수키 (세미콜론, 백틱, 역슬래시 등 허용 키 목록)
        OEM_ALLOWED = {";", "`", "\\", "]", "[", "-", "=", "'", ",", ".", "/"}
        try:
            if not hk:
                return False, "빈 입력"
            parts = hk.split("+")
            if hk in RESERVED_HOTKEYS:
                return False, "시스템 예약 조합 사용 불가"
            # 수식키만 입력
            if all(p in MODIFIER_ONLY for p in parts):
                return False, "수식키 단독 사용 불가"
            non_mod = [p for p in parts if p not in MODIFIER_ONLY]
            if len(non_mod) != 1:
                return False, "주 키 1개만 지정 가능"
            main = non_mod[0]
            # F1~F12 단독 허용
            if len(parts) == 1:
                if main in {"f3","f4","f5","f6","f7","f8","f9","f10","f11","f12"}:
                    return True, hk
                return False, "수식키 없는 단독 문자 불가"
            if main in {"f1","f2"}:
                return False, "F1/F2는 시스템 예약"
            # OEM 특수키 명시 허용 (;  `  \  ]  [  -  =  '  ,  .  /)
            if main in OEM_ALLOWED:
                pass
            # 영문·숫자·F키 허용
            elif len(main) == 1 and (main.isalnum()):
                pass
            elif main.startswith("f") and main[1:].isdigit():
                pass
            # 그 외도 일단 허용

            # ── 교차 중복 검증 (화면보호기 ↔ 퀵 메모 충돌 방지) ──
            cleaned = hk.replace(" ", "").lower()
            ss_key  = self.config.get("hotkey_screensaver", "ctrl+shift+l").replace(" ", "").lower()
            qm_key  = self.config.get("hotkey_quick_memo",  "ctrl+m").replace(" ", "").lower()
            if target_type == "quick_memo" and cleaned == ss_key:
                return False, "⚠️ 화면보호기 잠금 단축키와 동일한 키는 지정할 수 없습니다."
            if target_type == "screensaver" and cleaned == qm_key:
                return False, "⚠️ 퀵 메모 단축키와 동일한 키는 지정할 수 없습니다."

            return True, hk
        except Exception as e:
            LOG.error(f"_validate_hotkey 오류: {e}")
            return False, f"유효성 검사 오류: {e}"

    # ── 추천 다이얼로그 ──────────────────────────
    def _show_hotkey_recommendations(self):
        L = self.config.get("language", "ko")
        dlg = tk.Toplevel(self.root)
        dlg.title(t("dlg_recommend_hk", L))
        dlg.grab_set()

        tk.Label(
            dlg, text=t("lbl_3fail", L),
            font=("Arial", 13), padx=14, pady=8
        ).pack()

        for hk in RECOMMENDED_HOTKEYS:
            ttk.Button(
                dlg, text=self._fmt_hotkey(hk), width=22,
                command=lambda h=hk: self._apply_recommended(h, dlg)
            ).pack(pady=2, padx=14)

        ttk.Button(dlg, text=t("btn_close", L), command=dlg.destroy, width=22).pack(pady=(8, 12), padx=14)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        center_window(dlg, min_w=240, min_h=240)

    def _apply_recommended(self, hk, dlg):
        ok, _ = self._validate_hotkey(hk, target_type="screensaver")
        if not ok:
            return
        self.config["hotkey_screensaver"] = hk

    # ── 퀵 메모 단축키 저장 ──────────────────────
    def _apply_qm_hotkey_save(self):
        """퀵 메모 단축키 저장 및 커널 즉시 적용."""
        L = self.config.get("language", "ko")
        raw = self.var_qm_hotkey.get().strip().lower()
        if not raw:
            messagebox.showwarning(
                t("msg_warning", L), t("msg_qm_no_key", L),
                parent=self.root
            )
            return
        ok, result = self._validate_hotkey(raw, target_type="quick_memo")
        if not ok:
            messagebox.showwarning(t("msg_hk_error", L), result, parent=self.root)
            return
        # 저장
        self.config["hotkey_quick_memo"] = raw
        self.config["qm_hotkey_mode"]   = "custom"
        save_config(self.config)
        # 커널 즉시 적용
        if hasattr(self, '_tray_hk') and self._tray_hk:
            self._tray_hk.register_quick_memo_hotkey(raw)
        # UI 갱신
        self.var_qm_hotkey_disp.set(self._fmt_hotkey(raw))
        self._updating_qm_ui_now = True
        self.var_qm_hk_mode.set("custom")
        self._updating_qm_ui_now = False
        self.var_qm_hotkey.set("")
        messagebox.showinfo(
            t("msg_save_done", L), t("msg_qm_saved_fmt", L).format(hk=self._fmt_hotkey(raw)),
            parent=self.root
        )
        LOG.info(f"[QuickMemo] 단축키 저장 완료: {raw}")

    # ── 전역 단축키 (TrayHotkeySystem 통합 위임) ─────
    def _register_global_hotkey(self):
        """스레드 안전: update_hotkey(PostMessage) 경유. 백그라운드 직접 호출 금지."""
        if self._tray_hk and self._tray_hk._running:
            hk = self.config.get("hotkey_screensaver", "ctrl+shift+l")
            ok = self._tray_hk.update_hotkey(hk)
            if not ok and hk != "ctrl+shift+l":
                self._tray_hk.update_hotkey("ctrl+shift+l")
                LOG.warning(f"[Hotkey] [{hk}] 등록 실패 → 기본값(ctrl+shift+l) 폴백")

    def _unregister_global_hotkey(self):
        if self._tray_hk:
            self._tray_hk.unregister_hotkey()

    def _reregister_hotkey(self):
        """설정 변경 후 단축키 재적용. update_hotkey(PostMessage) 경유."""
        try:
            hk = self.config.get("hotkey_screensaver", "ctrl+shift+l")
            if hasattr(self, '_tray_hk') and self._tray_hk:
                self._tray_hk.update_hotkey(hk)
                LOG.info(f"[Hotkey] 화면보호기 단축키 재적용: [{hk}]")
        except Exception as e:
            LOG.error(f"[Hotkey] 재등록 오류: {e}")
