# -*- coding: utf-8 -*-
"""
idle_monitor — 유휴 감지 + 절전 차단 (after 기반 메인스레드 폴링)
"""
import ctypes
import logging
import time

LOG = logging.getLogger("MuteAndSaver")

_HAS_WIN32 = False
try:
    import win32api
    import win32con
    import win32gui
    _HAS_WIN32 = True
except ImportError:
    pass

class _LastInputInfo(ctypes.Structure):
    """LASTINPUTINFO 구조체 (Windows API) — 매 호출 재정의 방지"""
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class IdleMonitor:
    """
    LASTINPUTINFO + SetThreadExecutionState 통합.
    daemon 스레드 대신 Tkinter after()로 메인 스레드 안에서 폴링.
    화면보호기 실행 중에만 절전 차단을 적용.
    """

    # SetThreadExecutionState 플래그
    ES_CONTINUOUS       = 0x80000000
    ES_SYSTEM_REQUIRED  = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    POLL_MS = 5000   # 5초마다 체크 (사용자 입력 감지 지연 허용)
    MIN_TIMEOUT_SEC = 10  # config 비정상값 방어
    GRACE_SEC = 30   # 화면보호기 종료 후 재잠금 방지

    def __init__(self, app):
        self.app = app
        self._after_id    = None
        self._running     = False
        self._sleep_blocked = False  # 절전 차단 중 여부

    # ── 시작 / 중지 ──────────────────────
    def start(self):
        if self._running:
            return
        self._running = True
        LOG.info("유휴 감지 시작 (after 기반)")
        self._after_id = self.app.root.after(self.POLL_MS, self._tick)

    def stop(self):
        self._running = False
        if self._after_id:
            try:
                self.app.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        # 종료 시 절전 차단 원복
        self.allow_sleep()

    # ── OS 마지막 입력 시각 ────────────────
    def get_idle_seconds(self) -> float:
        """
        Windows GetLastInputInfo + GetTickCount.
        47.9일 wrap-around 방어 포함.
        """
        if not _HAS_WIN32:
            return 0.0
        try:
            lii = _LastInputInfo()
            lii.cbSize = ctypes.sizeof(_LastInputInfo)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                tick = ctypes.windll.kernel32.GetTickCount()
                diff = (tick - lii.dwTime) & 0xFFFFFFFF
                return diff / 1000.0
        except Exception as e:
            LOG.error(f"GetLastInputInfo 오류: {e}")
        return 0.0

    # ── 절전 차단 / 허용 ──────────────────
    def prevent_sleep(self):
        """화면보호기 실행 중 시스템 절전 모드 차단"""
        if not _HAS_WIN32 or self._sleep_blocked:
            return
        try:
            flags = self.ES_CONTINUOUS | self.ES_DISPLAY_REQUIRED | self.ES_SYSTEM_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
            self._sleep_blocked = True
            LOG.debug("절전 차단 ON")
        except Exception as e:
            LOG.error(f"절전 차단 오류: {e}")

    def allow_sleep(self):
        """절전 차단 해제 — OS 기본 동작 복귀"""
        if not _HAS_WIN32 or not self._sleep_blocked:
            return
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
            self._sleep_blocked = False
            LOG.debug("절전 차단 OFF")
        except Exception as e:
            LOG.error(f"절전 허용 오류: {e}")

    # ── 주기적 체크 (메인 스레드) ──────────
    def _tick(self):
        if not self._running:
            return
        try:
            self._check_once()
        except Exception as e:
            LOG.error(f"idle 체크 오류: {e}")
        # 다음 체크 예약
        if self._running:
            self._after_id = self.app.root.after(self.POLL_MS, self._tick)

    def _check_once(self):
        cfg = self.app.config

        # 화면보호기가 꺼져 있으면: 잠금 트리거 안 함 + 절전 허용
        if not cfg.get("screensaver_enabled", True):
            self.allow_sleep()
            return

        # 이미 화면보호기 실행 중이면: 절전 차단 (사용자 설정에 따라)
        ss_active = bool(getattr(self.app, '_screensaver', None))
        if ss_active:
            ps_on = cfg.get("power_save_enabled", False)
            if ps_on:
                # 절전 ON: 윈도우즈 절전 타이머를 막지 않음(차단 해제) → OS가 처리
                self.allow_sleep()
            else:
                self.prevent_sleep()
            return

        # 화면보호기 종료 직후 grace 기간 (재잠금 방지)
        if self.app._ss_closed_at > 0:
            elapsed = time.time() - self.app._ss_closed_at
            if elapsed < self.GRACE_SEC:
                self.allow_sleep()
                return
            else:
                self.app._ss_closed_at = 0.0

        # 유휴 시간 체크 → 임계 초과 시 잠금 트리거
        idle_sec = self.get_idle_seconds()
        timeout  = max(self.MIN_TIMEOUT_SEC,
                       int(cfg.get("timeout_seconds", 300)))
        if idle_sec >= timeout:
            LOG.info(f"유휴 {idle_sec:.0f}초 \u2265 {timeout}초 \u2192 화면보호기 활성화")
            self.app._lock_screen()
        else:
            # 유휴 측정 중에는 절전 허용 (사용자가 일시 자리 비움)
            self.allow_sleep()
