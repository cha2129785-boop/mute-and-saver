# -*- coding: utf-8 -*-
"""
lifecycle — 트레이/단축키 실행/잠금/PIN/종료 (Mixin)
"""
import os
import sys
import logging
import time
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

LOG = logging.getLogger("MuteAndSaver")

_HAS_WIN32 = False
try:
    import win32api
    import win32con
    import win32gui
    _HAS_WIN32 = True
except ImportError:
    pass

from ..i18n import t
from ..constants import APP_DISPLAY, PRESETS, ICON_PATH, DEFAULT_MANUAL_MEDIA, DEFAULT_SS_HOTKEY, DEFAULT_QM_HOTKEY, manual_media_for
from ..persistence import save_config, load_config, get_all_presets, save_favorites
from ..services import set_pin, clear_pin, verify_pin, _verify_master
from ..features.screensaver import ScreensaverWindow
from ..platform.windows.tray import TrayHotkeySystem
from ..platform.windows import IdleMonitor
from ..platform.windows.monitor import _get_monitors_info
from ..features.memo.editor import FullscreenMemoEditor


class LifecycleMixin:
    def _migrate_legacy_hotkey(self):
        """
        기존 'hotkey' 키 → 'hotkey_screensaver'/'hotkey_quick_memo' 마이그레이션.
        load_config() 직후 1회 실행.
        """
        try:
            modified = False
            if "hotkey" in self.config:
                legacy = self.config.pop("hotkey")
                if legacy and legacy != "ctrl+space":
                    self.config["hotkey_screensaver"] = legacy
                    LOG.info(f"[Migration] 기존 단축키 [{legacy}] → hotkey_screensaver 이전")
                modified = True
            if "hotkey_screensaver" not in self.config:
                self.config["hotkey_screensaver"] = DEFAULT_SS_HOTKEY
                modified = True
            if "hotkey_quick_memo" not in self.config:
                self.config["hotkey_quick_memo"] = DEFAULT_QM_HOTKEY
                modified = True
            if modified:
                save_config(self.config)
                LOG.info("[Migration] 단축키 스키마 업그레이드 완료")
        except Exception as e:
            LOG.error(f"[Migration] 마이그레이션 오류: {e}")

    def _seed_default_media(self):
        """번들 사용설명서를 미디어 라이브러리에 '자동 복구' 시드.
        매 실행 시 builtin 설명서가 없으면 재추가, 경로가 설치 위치와 다르면 자동 교정.
        (사용자가 삭제해도 다음 실행에 복구됨 — 기본 제공 도움말 항상 유지)
        builtin 항목은 미디어 갯수 제한에 포함되지 않음(_count_media에서 제외)."""
        try:
            manual = manual_media_for(self.config.get("language", "ko"))
            if not os.path.exists(manual):
                manual = DEFAULT_MANUAL_MEDIA   # 영문 누락 시 한글 폴백
            if not os.path.exists(manual):
                return   # 번들 경로 못 찾음 → 다음 실행 재시도
            _name = {"ko": "사용설명서", "en": "User Guide", "zh": "使用说明",
                     "ja": "使用説明", "ru": "Руководство"}.get(
                        self.config.get("language", "ko"), "User Guide")
            builtin  = next((f for f in self.favorites if f.get("type") == "builtin"), None)
            old_path = builtin.get("path") if builtin else None
            fav_changed = False
            if builtin is None:
                self.favorites.append({
                    "name": _name, "path": manual,
                    "type": "builtin", "tier": "free",
                    "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                })
                fav_changed = True
            elif old_path != manual:
                builtin["path"] = manual   # 언어·설치위치 변경 시 경로 자동 교정
                builtin["name"] = _name
                fav_changed = True
            if fav_changed:
                save_favorites(self.favorites)
            # 기본 선택(selected_media) 동기화 — stale 경로를 현재 경로로 교체
            sel = list(self.config.get("selected_media", []))
            cfg_changed = False
            if old_path and old_path != manual and old_path in sel:
                sel = [manual if s == old_path else s for s in sel]
                cfg_changed = True
            if manual not in sel:
                sel.append(manual)
                cfg_changed = True
            if cfg_changed:
                self.config["selected_media"] = sel
            if self.config.get("first_run", True):
                self.config["first_run"] = False
                cfg_changed = True
            if cfg_changed:
                save_config(self.config)
            if fav_changed:
                LOG.info("[Seed] 기본 미디어(사용설명서) 자동 복구/교정 완료")
        except Exception as e:
            LOG.error(f"[Seed] 기본 미디어 시드 오류: {e}")

    def _setup_quick_memo_hotkey(self):
        """
        hwnd 안정화(500ms) 후 ID=2 퀵 메모 단축키만 등록.
        ID=1은 백그라운드 스레드(_run_loop L6209)에서 초기 등록하므로 중복 금지.
        """
        try:
            if hasattr(self, '_tray_hk') and self._tray_hk:
                memo_key = self.config.get("hotkey_quick_memo", "ctrl+m")
                self._tray_hk.register_quick_memo_hotkey(memo_key)
                LOG.info(f"[QuickMemo] ID=2 퀵 메모 단축키 등록 완료: [{memo_key}]")
        except Exception as e:
            LOG.error(f"[QuickMemo] 퀵 메모 단축키 등록 오류: {e}")

    def _execute_quick_memo_toggle(self):
        """
        메인 스레드에서 실행 — 퀵 메모 단축키 → FSEditor 직통 호출.
        screensaver_mode를 임시 "memo" 강제하여 FSEditor 내부 경로 보장.
        500ms 디바운싱으로 연타 방지.
        """
        if getattr(self, '_is_toggling_memo', False):
            LOG.warning("[QuickMemo] ⚠️ 전환 진행 중 — 중복 단축키 무시")
            return
        self._is_toggling_memo = True
        try:
            # 화면보호기 실행 중이면 무시
            if hasattr(self, '_screensaver') and self._screensaver:
                LOG.warning("[QuickMemo] 🔒 화면보호기 실행 중 — 단축키 무시")
                return
            # FSEditor 이미 열려있으면 포커스
            existing = getattr(self, '_fs_editor', None)
            if existing:
                try:
                    if existing.overlay.winfo_exists():
                        existing.overlay.lift()
                        existing.overlay.focus_force()
                        LOG.info("[QuickMemo] 기존 FSEditor에 포커스")
                        return
                except Exception:
                    pass
                self._fs_editor = None
            # screensaver_mode 임시 "memo" 강제 → FSEditor 전체화면 메모 경로 보장
            old_mode = self.config.get("screensaver_mode", "media")
            self.config["screensaver_mode"] = "memo"
            LOG.info(f"[QuickMemo] 🚀 FSEditor 직통 호출 (원래 mode={old_mode} → 임시 memo)")
            try:
                monitors = _get_monitors_info()
                self._fs_editor = FullscreenMemoEditor(self, monitors)
            finally:
                self.config["screensaver_mode"] = old_mode   # 원복 (저장 안 함)
                LOG.info(f"[QuickMemo] mode 원복: {old_mode}")
        except Exception as e:
            LOG.error(f"[QuickMemo] FSEditor 호출 오류: {e}")
        finally:
            if hasattr(self, 'root') and self.root:
                self.root.after(500, lambda: setattr(self, '_is_toggling_memo', False))
            else:
                self._is_toggling_memo = False

    def _register_console_ctrl_handler(self):
        """
        CMD 창 X 버튼 강제 종료 방어.

        CMD 창 X 클릭 시 OS가 CTRL_CLOSE_EVENT(값=2)를 발생시키고
        파이썬 코드를 즉시 kill — _on_close() 미실행 → NIM_DELETE 미전송 → 고스트.

        SetConsoleCtrlHandler로 커널 단에 가로채기 등록:
          → 핸들러가 True 반환 시 OS 즉각 종료 차단
          → _on_close() 실행 → NIM_DELETE 전송 → 고스트 방지
        pywin32 없거나 IDE 환경이면 등록 실패해도 계속 진행.
        """
        if not _HAS_WIN32:
            return
        try:
            import win32api, win32con

            def _console_ctrl_handler(ctrl_type):
                if ctrl_type == win32con.CTRL_CLOSE_EVENT:
                    LOG.info(
                        "[Kernel_Signal] 🚨 CMD 창 X 버튼 감지! "
                        "강제 파괴 차단 → 메인 스레드로 순정 종료 위임"
                    )
                    try:
                        # OS 신호 핸들러는 백그라운드 스레드 → 직접 호출 금지
                        # root.after(0)으로 메인 스레드에 위임 (Tkinter 스레드 안전)
                        if hasattr(self, 'root') and self.root:
                            self.root.after(0, self._on_close)
                        else:
                            self._on_close()
                    except Exception as e:
                        LOG.error(f"[Kernel_Signal] _on_close 위임 오류: {e}")
                    return True   # True = OS 즉각 종료 차단
                return False

            win32api.SetConsoleCtrlHandler(_console_ctrl_handler, True)
            LOG.info(
                "[Kernel_Signal] ✅ CMD X 버튼 방어벽(ConsoleCtrlHandler) 등록 완료"
            )
        except Exception as e:
            LOG.error(f"[Kernel_Signal] 핸들러 등록 실패 (IDE 또는 권한 부족): {e}")

    def _start_tray(self):
        """Stage 8 v7 — 트레이 + 단축키 통합 시스템 시작"""
        if not _HAS_WIN32:
            LOG.warning("pywin32 미설치 — Tray+Hotkey 비활성")
            return
        self._tray_hk = TrayHotkeySystem(self, ICON_PATH, tooltip=APP_DISPLAY)
        ok = self._tray_hk.start()
        if not ok:
            self._tray_hk = None
            return
        # 단축키는 _run_loop에서 백그라운드 스레드 권한으로 자동 등록됨

    def _stop_tray(self):
        LOG.info("[App_Exit] 🛑 _stop_tray() 장갑차 가동")
        if self._tray_hk:
            try:
                self._tray_hk.stop()
                t = getattr(self._tray_hk, '_thread', None)
                if t and t.is_alive():
                    LOG.info("[App_Exit] 트레이 스레드 살아있음 → 1.0초 동기화 대기...")
                    t.join(timeout=1.0)
                    if t.is_alive():
                        LOG.warning(
                            "[App_Exit] ⚠️ [위험] 1.0초 타임아웃 발생! "
                            "트레이 스레드가 PumpMessages에 갇혀 종료 안됨 (고스트 유발 인자)"
                        )
                    else:
                        LOG.info("[App_Exit] ✅ 트레이 스레드 정상 병합 — 고스트 없음")
                else:
                    LOG.info("[App_Exit] 트레이 스레드 이미 종료 상태")
            except Exception as e:
                LOG.error(f"[App_Exit] 🚨 _stop_tray 예외: {e}")
            self._tray_hk = None

    # ── X 버튼 → 트레이로 최소화 ───────────────
    def _minimize_to_tray(self):
        L = self.config.get("language", "ko")
        # ── FSEditor grab_set 중이면 종료 차단 ──────────────
        # grab_set 상태에서 root.destroy() 시 Tkinter grab 해제 오류 → 비정상 종료
        fs = getattr(self, '_fs_editor', None)
        if fs and getattr(fs, '_grab_active', False):
            try:
                # FSEditor 창을 최상단으로 올려서 사용자에게 알림
                fs.overlay.lift()
                fs.overlay.focus_force()
                import tkinter.messagebox as _mb
                _mb.showinfo(
                    t("lbl_editing", L),
                    t("lbl_close_edit", L),
                    parent=fs.overlay
                )
            except Exception:
                pass
            return   # 종료 차단

        if getattr(self, '_tray_hk', None):
            self.root.withdraw()
            LOG.info("트레이로 최소화")
        else:
            self._on_close()

    # ── 트레이 좌클릭 → 메인 창 표시 ───────────
    def _show_main_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception as e:
            LOG.error(f"메인 창 표시 오류: {e}")

    # ── 트레이 메뉴 — 화면보호기 토글 ──────────
    def _toggle_ss_from_tray(self):
        cur = self.config.get("screensaver_enabled", True)
        self.var_ss_enabled.set(not cur)
        self.config["screensaver_enabled"] = not cur
        save_config(self.config)
        LOG.info(f"화면보호기 {'ON' if not cur else 'OFF'} (트레이)")
        if getattr(self, "_tray_hk", None):
            self._tray_hk.update_status()

    # ── 트레이 메뉴 — 절전 모드 토글 ───────────
    def _apply_preset(self):
        """선택된 프리셋 config 적용 → 설정 탭 UI 갱신."""
        L = self.config.get("language", "ko")
        name   = getattr(self, 'var_preset', tk.StringVar()).get()
        internal = getattr(self, '_preset_map', {}).get(name, name)
        preset = get_all_presets().get(internal, {})
        if not preset:
            return
        # Model B1: 라이브러리(favorites)는 전역 — 프리셋이 안 건드림(추가 미디어 보존).
        #  선택(selected_media)만 프리셋에 연동 — 단, 라이브러리에 '남아있는' 파일만 복원
        #  (삭제된 미디어는 호출 안 됨). favorites/selected_media는 일반 update에서 제외 후 개별 처리.
        _skip = ("favorites", "selected_media")
        _cfg_preset = {k: v for k, v in preset.items() if k not in _skip}
        self.config.update(_cfg_preset)
        # 선택 복원: 프리셋 selected_media ∩ 현재 라이브러리(favorites) 경로
        _preset_sel = preset.get("selected_media", None)
        if _preset_sel is not None:
            _lib_paths = {f.get("path", "") for f in getattr(self, "favorites", [])}
            self.config["selected_media"] = [p for p in _preset_sel if p in _lib_paths]
        self.config["active_preset"] = internal   # Stage F: 적용 중 프리셋 표시용
        save_config(self.config)
        # ⚠️ FIX: 기본설정 Tk 변수는 __init__에서 1회 생성 → _build_tab_setting이
        #    재생성하지 않음. config만 갱신하면 체크박스/타임아웃이 옛 값 그대로 표시되고
        #    이후 _on_settings_change가 옛 var를 config에 되써 적용 결과 훼손됨 → 명시 동기화
        try:
            self.var_ss_enabled.set(self.config.get("screensaver_enabled", True))
            self.var_ps_enabled.set(self.config.get("power_save_enabled", False))
            self.var_mute_enabled.set(self.config.get("mute_on_screensaver", False))
            self.var_timeout.set(max(1, int(self.config.get("timeout_seconds", 300)) // 60))
            self.var_slide_mode.set(self.config.get("slide_mode", "random"))
            self.var_interval.set(int(self.config.get("media_interval_seconds", 10)))
        except Exception as e:
            LOG.error(f"[Preset] 기본설정 var 동기화 오류: {e}")
        # 설정 탭 + 미디어 탭 + 메모 탭 + 단축키 탭 UI 갱신 (확장 항목 반영)
        # ⚠️ FIX: Stage A에서 미디어 갤러리가 settings_tab → media_tab으로 분리되며
        #    _apply_preset이 media_tab을 재빌드하지 않아 preset의 selected_media가
        #    갤러리 선택 표시에 반영되지 않던 회귀 수정
        self._build_tab_setting()
        self._build_tab_media()
        self._build_tab_memo()
        try:
            self._build_tab_hotkey()
        except Exception:
            pass
        # var 동기화
        if "screensaver_mode" in preset:
            self.var_ss_mode.set(preset["screensaver_mode"])
        if "split_ratio" in preset:
            self.var_split_ratio.set(preset["split_ratio"])
        LOG.info(f"[Preset] '{name}' 적용 완료")
        # Stage E: 차단형 팝업 → 인라인 피드백(설정 탭 재빌드 후 라벨 존재)
        self._flash_label("_preset_fb", "_preset_fb_job", t("fb_applied", L), "#27ae60")

    def _preview_screensaver(self):
        """
        실제 화면보호기를 1/4 크기 창에서 30초간 미리보기.
        화면보호기 실행 중이면 차단.
        """
        L = self.config.get("language", "ko")
        if hasattr(self, '_screensaver') and self._screensaver:
            try:
                if self.root.winfo_exists():
                    tk.messagebox.showinfo(
                        t("lbl_preview2", L),
                        t("lbl_ss_running", L),
                        parent=self.root
                    )
            except Exception:
                pass
            return

        try:
            import ctypes as _ctypes
            sw = _ctypes.windll.user32.GetSystemMetrics(0)
            sh = _ctypes.windll.user32.GetSystemMetrics(1)
        except Exception:
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()

        pw, ph = sw // 4, sh // 4
        px, py = sw // 2 - pw // 2, sh // 2 - ph // 2

        prev = tk.Toplevel(self.root)
        prev.title(t("dlg_preview_30s", L))
        prev.geometry(f"{pw}x{ph}+{px}+{py}")
        prev.resizable(False, False)
        prev.attributes("-topmost", True)

        tk.Label(prev, text=t("lbl_memo_preview", L),
                 bg="#0a0a0f", fg="#9ca3af",
                 font=("Malgun Gothic", 9), justify="center"
                 ).pack(expand=True)

        tk.Button(prev, text=t("btn_close", L),
                  command=prev.destroy,
                  bg="#374151", fg="white",
                  relief="flat", padx=8
                  ).pack(pady=8)

        # 30초 자동 닫기
        prev.after(30000, lambda: prev.destroy() if prev.winfo_exists() else None)
        LOG.info("[Preview] 화면보호기 미리보기 시작 (30초)")

    def _toggle_ps_from_tray(self):
        cur = self.config.get("power_save_enabled", False)
        self.var_ps_enabled.set(not cur)
        self.config["power_save_enabled"] = not cur
        save_config(self.config)
        LOG.info(f"절전 모드 {'ON' if not cur else 'OFF'} (트레이)")
        if getattr(self, "_tray_hk", None):
            self._tray_hk.update_status()

    # ── 메인 스레드 메시지 펌프 (단축키 스코프 보강) ─
    def _start_message_pump(self):
        """
        TrayHotkeySystem은 별도 스레드에서 PumpMessages() 무한 루프 실행.
        그러나 일부 환경에서 메인 스레드 차단 시 메시지 전달이 지연될 수 있음.
        이 보조 펌프는 메인 스레드 Tkinter after 루프 안에서
        win32gui.PumpWaitingMessages()를 100ms마다 호출.
        """
        if not _HAS_WIN32:
            return
        try:
            win32gui.PumpWaitingMessages()
        except Exception as e:
            LOG.debug(f"PumpWaitingMessages 오류: {e}")
        try:
            self.root.after(100, self._start_message_pump)
        except (RuntimeError, tk.TclError):
            pass

        # ── Stage 9 v7 — IdleMonitor 시작/정지 ──────
    def _start_idle_monitor(self):
        if self._idle_monitor:
            return
        self._idle_monitor = IdleMonitor(self)
        self._idle_monitor.start()

    def _stop_idle_monitor(self):
        if self._idle_monitor:
            try:
                self._idle_monitor.stop()
            except Exception as e:
                LOG.error(f"IdleMonitor 정지 오류: {e}")
            self._idle_monitor = None

    def _restore_power_state(self):
        """_on_close 호환용 — IdleMonitor.allow_sleep() 위임"""
        if self._idle_monitor:
            self._idle_monitor.allow_sleep()

    # ══════════════════════════════════════════════
    # Stage 5 — 화면보호기 활성화
    # ══════════════════════════════════════════════
    def _lock_screen(self):
        """화면보호기 생성 및 잠금 진입 (단축키 연타 레이싱 완벽 방어)."""
        # 1차 물리 가드: 이미 생성된 객체 있으면 즉시 차단 (기존 순정 문법 유지)
        if hasattr(self, '_screensaver') and self._screensaver:
            return
        # 2차 논리 가드: after(0) 큐 연속 진입으로 인한 레이스 컨디션 차단
        if getattr(self, '_is_locking', False):
            LOG.warning("[App] ⚠️ 화면보호기 생성 중 — 중복 진입 차단")
            return
        self._is_locking = True
        try:
            self._ss_closed_at = 0.0
            self.audio_controller.mute_if_needed(
                self.config.get("mute_on_screensaver", False)
            )
            self._screensaver = ScreensaverWindow(self)
            LOG.info("화면보호기 활성화")
        except Exception as e:
            LOG.error(f"[App] 🚨 화면보호기 생성 오류: {e}")
        finally:
            self._is_locking = False   # 성공/실패 무관 반드시 해제

    def _lock_screen_immediate(self):
        """Stage 11 v7 — /s 모드: 즉시 실행 + 종료 시 앱도 종료"""
        self._lock_screen()
        # ScreensaverWindow.close()가 호출되면 앱 전체 종료하도록
        # _ss_closed_at 사용해서 폴링하는 방식
        self._monitor_screensaver_for_exit()

    def _monitor_screensaver_for_exit(self):
        """/s 모드: 화면보호기가 종료되면 앱 전체 종료"""
        if not hasattr(self, '_screensaver') or not self._screensaver:
            # 종료 감지 → 앱 전체 종료
            LOG.info("/s 모드 화면보호기 종료 감지 → 앱 종료")
            self.root.after(100, self._on_close)
            return
        # 0.5초 후 재확인
        self.root.after(500, self._monitor_screensaver_for_exit)

    def _check_pin_attempt(self) -> bool:
        L = self.config.get("language", "ko")
        if self._pin_locked_until > time.time():
            remaining = int(self._pin_locked_until - time.time())
            messagebox.showwarning(
                t("pin_locked", L),
                t("pin_locked_msg", L).format(remaining=remaining),
                parent=self.root
            )
            return False
        return True

    def _on_pin_fail(self):
        self._pin_fail_count += 1
        LOG.warning(f"PIN 실패 {self._pin_fail_count}회")
        if self._pin_fail_count >= 5:
            self._pin_locked_until = time.time() + 30
            self._pin_fail_count   = 0
            LOG.warning("PIN 5회 실패 → 30초 잠금")

    # ── PIN 설정 다이얼로그 ──────────────────────
    def _open_pin_dialog(self):
        L = self.config.get("language", "ko")
        if not self._check_pin_attempt():
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(t("dlg_pin_set", L))
        dlg.transient(self.root)

        # 명시적 고정 크기 (자동 계산 미사용 — 버튼 누락 방지)
        is_change = self.config.get("pin_set", False)
        win_w = 360
        win_h = 320 if is_change else 280
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        x = (sw - win_w) // 2
        y = (sh - win_h) // 2
        dlg.geometry(f"{win_w}x{win_h}+{x}+{y}")
        dlg.resizable(False, False)

        # 단일 부모 프레임 — grid 통합 사용 (pack 충돌 제거)
        frm = tk.Frame(dlg, padx=18, pady=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        entries = {}
        row = 0

        if is_change:
            tk.Label(frm, text=t("lbl_cur_pin", L)).grid(row=row, column=0, sticky="e", pady=4)
            e_cur = ttk.Entry(frm, show="●", width=20)
            e_cur.grid(row=row, column=1, padx=(8,0), pady=4, sticky="ew")
            entries["current"] = e_cur
            row += 1

        tk.Label(frm, text=t("lbl_new_pin", L)).grid(row=row, column=0, sticky="e", pady=4)
        e_new = ttk.Entry(frm, show="●", width=20)
        e_new.grid(row=row, column=1, padx=(8,0), pady=4, sticky="ew")
        entries["new"] = e_new
        row += 1

        tk.Label(frm, text=t("lbl_confirm_pin", L)).grid(row=row, column=0, sticky="e", pady=4)
        e_conf = ttk.Entry(frm, show="●", width=20)
        e_conf.grid(row=row, column=1, padx=(8,0), pady=4, sticky="ew")
        entries["confirm"] = e_conf
        row += 1

        lbl_err = tk.Label(frm, text="", fg="#e74c3c", font=("Arial", 9))
        lbl_err.grid(row=row, column=0, columnspan=2, pady=(6,2))
        row += 1

        tk.Label(
            frm, text=t("lbl_pin_note", L),
            fg="#999999", font=("Arial", 8)
        ).grid(row=row, column=0, columnspan=2, pady=(0,8))
        row += 1

        def do_save():
            lbl_err.config(text="", fg="#e74c3c")
            # 현재 PIN 검증
            if self.config.get("pin_set"):
                if not verify_pin(entries["current"].get(), self.config):
                    self._on_pin_fail()
                    if self._pin_locked_until > time.time():
                        lbl_err.config(text=t("msg_5fail", L))
                        dlg.after(800, lambda: dlg.destroy() if dlg.winfo_exists() else None)
                    else:
                        lbl_err.config(text=t("msg_pin_wrong", L))
                    return

            new_pin  = entries["new"].get()
            conf_pin = entries["confirm"].get()

            if len(new_pin) < 4:
                lbl_err.config(text=t("msg_pin_short", L))
                return
            if new_pin != conf_pin:
                lbl_err.config(text=t("msg_pin_mismatch", L))
                return
            if _verify_master(new_pin):
                lbl_err.config(text=t("msg_pin_master", L))
                return

            set_pin(new_pin, self.config)
            save_config(self.config)
            self._refresh_pin_label()
            self.root.update_idletasks()
            self._pin_fail_count = 0
            LOG.info("PIN 설정 완료")
            # 시각적 성공 표시 후 자동 닫기 (messagebox 가림 이슈 회피)
            lbl_err.config(text=t("lbl_pin_set_done", L), fg="#27ae60")
            for w in (entries.get("current"), entries["new"], entries["confirm"]):
                if w:
                    try: w.config(state="disabled")
                    except Exception: pass
            dlg.after(900, lambda: dlg.destroy() if dlg.winfo_exists() else None)

        # 버튼 영역 — frm 내부 grid에 배치 (pack 충돌 제거)
        frm_btn = tk.Frame(frm)
        frm_btn.grid(row=row, column=0, columnspan=2, pady=(8, 0), sticky="ew")
        frm_btn.columnconfigure(0, weight=1)
        frm_btn.columnconfigure(1, weight=1)

        btn_save = ttk.Button(frm_btn, text=t("btn_save", L), command=do_save, width=12)
        btn_save.grid(row=0, column=0, padx=4, sticky="ew")

        btn_cancel = ttk.Button(frm_btn, text=t("btn_cancel2", L), command=dlg.destroy, width=12)
        btn_cancel.grid(row=0, column=1, padx=4, sticky="ew")

        dlg.bind("<Return>", lambda _: do_save())
        dlg.bind("<Escape>", lambda _: dlg.destroy())

        # 포커스
        if is_change:
            entries["current"].focus_set()
        else:
            entries["new"].focus_set()

        dlg.grab_set()

    # ── PIN 초기화 다이얼로그 ────────────────────
    def _reset_pin_dialog(self):
        L = self.config.get("language", "ko")
        if not self.config.get("pin_set"):
            messagebox.showinfo(t("msg_pin_reset", L), t("msg_no_pin", L), parent=self.root)
            return
        if not self._check_pin_attempt():
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(t("dlg_pin_reset", L))
        dlg.transient(self.root)

        # 명시적 고정 크기
        win_w, win_h = 380, 240
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        x = (sw - win_w) // 2
        y = (sh - win_h) // 2
        dlg.geometry(f"{win_w}x{win_h}+{x}+{y}")
        dlg.resizable(False, False)

        frm = tk.Frame(dlg, padx=18, pady=14)
        frm.pack(fill="both", expand=True)

        tk.Label(frm, text=t("lbl_pin_enter", L),
                 font=("Arial", 9)).pack(anchor="w")
        e = ttk.Entry(frm, show="●", width=28)
        e.pack(pady=(6, 4), fill="x")

        lbl_err = tk.Label(frm, text="", fg="#e74c3c", font=("Arial", 9))
        lbl_err.pack(pady=(4, 4))

        tk.Label(
            frm,
            text=t("lbl_master_note", L),
            fg="#999999", font=("Arial", 8)
        ).pack(pady=(4, 8))

        def do_reset():
            lbl_err.config(text="", fg="#e74c3c")
            pin_input = e.get()
            if not verify_pin(pin_input, self.config):
                self._on_pin_fail()
                if self._pin_locked_until > time.time():
                    lbl_err.config(text=t("msg_5fail", L))
                    dlg.after(800, lambda: dlg.destroy() if dlg.winfo_exists() else None)
                else:
                    lbl_err.config(text=t("msg_pin_wrong2", L))
                return

            was_master = _verify_master(pin_input)
            clear_pin(self.config)
            save_config(self.config)
            self._refresh_pin_label()
            self.root.update_idletasks()
            self._pin_fail_count = 0
            LOG.info(f"PIN 초기화 완료 (마스터키 사용: {was_master})")
            lbl_err.config(text=t("lbl_pin_reset_done", L), fg="#27ae60")
            try: e.config(state="disabled")
            except Exception: pass

            def _after_reset():
                try:
                    if dlg.winfo_exists():
                        dlg.destroy()
                except Exception:
                    pass
                if messagebox.askyesno(
                    t("pin_reset_done", L),
                    t("pin_reset_msg", L),
                    parent=self.root
                ):
                    self._open_pin_dialog()
            dlg.after(900, _after_reset)

        # 버튼 — frm 내부에 pack
        frm_btn = tk.Frame(frm)
        frm_btn.pack(fill="x", pady=(8, 0))
        ttk.Button(frm_btn, text=t("btn_reset", L), command=do_reset,
                   width=12).pack(side="left", padx=4, expand=True, fill="x")
        ttk.Button(frm_btn, text=t("btn_cancel2", L),   command=dlg.destroy,
                   width=12).pack(side="left", padx=4, expand=True, fill="x")

        dlg.bind("<Return>", lambda _: do_reset())
        dlg.bind("<Escape>", lambda _: dlg.destroy())

        e.focus_set()
        dlg.grab_set()
