# -*- coding: utf-8 -*-
"""
monitor — Windows 모니터 감지 (ctypes)
"""
import ctypes
import logging

LOG = logging.getLogger("MuteAndSaver")

_HAS_SCREENINFO = False
try:
    from screeninfo import get_monitors as _si_get_monitors
    _HAS_SCREENINFO = True
except ImportError:
    pass

def _get_monitors_info() -> list:
    """
    연결된 모든 모니터 정보 반환.
    반환: [(x, y, w, h, is_primary), ...]
    1단계: screeninfo (pip install screeninfo) — 정확한 is_primary 제공
    2단계: ctypes EnumDisplayMonitors — 추가 라이브러리 없이 동작
    3단계: GetSystemMetrics 단일 모니터 폴백
    """
    # ── 1단계: screeninfo ────────────────────────────
    if _HAS_SCREENINFO:
        try:
            result = []
            for m in _si_get_monitors():
                is_primary = bool(getattr(m, 'is_primary', False)) or (m.x == 0 and m.y == 0)
                result.append((m.x, m.y, m.width, m.height, is_primary))
            if result:
                LOG.info(f"[Monitor] screeninfo 감지: {len(result)}대 → {result}")
                return result
        except Exception as e:
            LOG.warning(f"[Monitor] screeninfo 실패, ctypes 폴백: {e}")

    # ── 2단계: ctypes EnumDisplayMonitors ─────────────
    monitors = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.c_double
    )
    def _cb(hMon, hdcMon, lprc, data):
        r = lprc.contents
        x, y = r.left, r.top
        w = r.right  - r.left
        h = r.bottom - r.top
        monitors.append((x, y, w, h, (x == 0 and y == 0)))
        return 1
    try:
        cb = MONITORENUMPROC(_cb)
        ctypes.windll.user32.EnumDisplayMonitors(None, None, cb, 0)
        if monitors:
            LOG.info(f"[Monitor] ctypes 감지: {len(monitors)}대 → {monitors}")
            return monitors
    except Exception as e:
        LOG.error(f"[Monitor] EnumDisplayMonitors 오류: {e}")

    # ── 3단계: 단일 모니터 폴백 ──────────────────────
    # GetSystemMetrics(0/1): DPI Aware 선언 시 물리 픽셀 반환
    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)
    LOG.warning(f"[Monitor] 감지 실패 — 단일 모니터 폴백 ({sw}×{sh})")
    return [(0, 0, sw, sh, True)]
