# -*- coding: utf-8 -*-
"""
single_instance — Named Mutex 단일 인스턴스 보장
PID 강제 종료 없음 — Mutex 충돌/권한 오류 시 알림 후 종료.
"""
import sys
import ctypes
import logging

from ...constants import APP_DISPLAY, MUTEX_NAME, LOCK_FILE

LOG = logging.getLogger("MuteAndSaver")

_mutex_handle = None

def ensure_single_instance():
    """
    Named Mutex 기반 단일 인스턴스 보장.
    PID Lock 파일은 진단 로그 용도만 — 다른 프로세스를 절대 강제 종료하지 않음.
    """
    global _mutex_handle
    import os
    current_pid = os.getpid()

    # ══ 1단계: PID Lock 진단 (강제 종료 없음) ══════════════
    if LOCK_FILE.exists():
        try:
            old_pid_str = LOCK_FILE.read_text(encoding="utf-8").strip()
            if old_pid_str.isdigit():
                old_pid = int(old_pid_str)
                if old_pid == current_pid:
                    LOG.info(f"[Singleton] 고스트 Lock (PID 재할당: {old_pid}) → 무시")
                else:
                    LOG.info(f"[Singleton] 이전 Lock 파일: PID={old_pid} (진단 전용, 강제 종료 안 함)")
            else:
                LOG.warning(f"[Singleton] Lock 파일 값 비정상: '{old_pid_str}' → 무시")
        except Exception as e:
            LOG.error(f"[Singleton] Lock 파일 읽기 오류 (무시됨): {e}")

    # ══ 2단계: Named Mutex 획득 ═════════════════════════════
    try:
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, MUTEX_NAME
        )
        err = ctypes.windll.kernel32.GetLastError()

        if not _mutex_handle:
            # Mutex 핸들 생성 자체 실패
            LOG.error(f"[Singleton] Mutex 핸들 생성 실패 (err={err}) → 알림 후 종료")
            try:
                ctypes.windll.user32.MessageBoxW(
                    0, f"{APP_DISPLAY} 시작 오류\nMutex 생성 실패 (코드 {err})",
                    APP_DISPLAY, 0x10)
            except Exception:
                pass
            sys.exit(1)

        if err == 183:   # ERROR_ALREADY_EXISTS → 중복 실행
            LOG.warning("[Singleton] Mutex 충돌 → 중복 실행 → 종료")
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"{APP_DISPLAY}가 이미 실행 중입니다.\n"
                    "트레이 아이콘을 확인하세요.",
                    APP_DISPLAY, 0x40)
            except Exception:
                pass
            sys.exit(0)

        elif err == 5:   # ERROR_ACCESS_DENIED → 알림 후 종료
            LOG.error("[Singleton] Mutex 접근 권한 없음 (코드 5) → 알림 후 종료")
            try:
                ctypes.windll.user32.MessageBoxW(
                    0, f"{APP_DISPLAY} 권한 오류\n관리자 권한으로 실행하세요.",
                    APP_DISPLAY, 0x10)
            except Exception:
                pass
            sys.exit(1)

        else:
            LOG.info("[Singleton] Named Mutex 획득 성공")

    except Exception as e:
        LOG.error(f"[Singleton] Mutex 생성 중 오류 → 알림 후 종료: {e}")
        try:
            ctypes.windll.user32.MessageBoxW(
                0, f"{APP_DISPLAY} 시작 오류\n{e}", APP_DISPLAY, 0x10)
        except Exception:
            pass
        sys.exit(1)

    # ══ 3단계: PID Lock 기록 (진단용) ══════════════════════
    try:
        LOCK_FILE.write_text(str(current_pid), encoding="utf-8")
        LOG.info(f"[Singleton] Lock 파일 기록: PID={current_pid}")
    except Exception as e:
        LOG.error(f"[Singleton] Lock 파일 갱신 실패: {e}")

    # ══ 종료 시 정리 ══════════════════════════════════════
    import atexit as _atexit
    def _cleanup():
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        if _mutex_handle:
            try:
                ctypes.windll.kernel32.CloseHandle(_mutex_handle)
            except Exception:
                pass
    _atexit.register(_cleanup)
