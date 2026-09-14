# -*- coding: utf-8 -*-
"""
main — 진입점. 모드 분기 + 최상위 예외 경계.
"""
import sys
import ctypes
import traceback
import logging

from .bootstrap import init_runtime, LOG
from .constants import LOG_PATH
from .i18n import t
from .platform.windows.single_instance import ensure_single_instance
from .ui.main_window import ScreesaverApp

def parse_scr_args(argv):
    """
    Windows 화면보호기 표준 인수:
      /s            : 전체화면 즉시 실행
      /c, /c:HWND   : 설정 창 (제어판에서 [설정] 클릭 시)
      /p HWND       : 작은 미리보기 (제어판 미리보기 영역)
      (인수 없음)   : 일반 앱 모드 (트레이 + 메인 창)

    반환: (mode, parent_hwnd)
        mode ∈ {"normal", "screensaver", "config", "preview"}
    """
    mode = "normal"
    parent_hwnd = None

    if len(argv) > 1:
        arg = argv[1].lower().strip()
        if arg.startswith("/s"):
            mode = "screensaver"
        elif arg.startswith("/c"):
            mode = "config"
            # /c:12345 형태의 HWND 파싱
            if ":" in arg:
                try:
                    parent_hwnd = int(arg.split(":")[1])
                except (ValueError, IndexError):
                    parent_hwnd = None
        elif arg == "/p":
            mode = "preview"
            if len(argv) > 2:
                try:
                    parent_hwnd = int(argv[2])
                except ValueError:
                    parent_hwnd = None

    return mode, parent_hwnd


def _set_dpi_awareness():
    """HiDPI 폰트 흐림 방지 — Tk() 생성 전 1회 호출 필수.
    ✅확신: System DPI Aware면 OS 비트맵 확대(흐림) 중단. 다중모니터라도 시스템 배율 기준 스케일 유지.
    shcore(Win8.1+) 우선, 실패 시 user32(Vista+) 폴백. 비-Windows는 무시."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    """
    모드별 진입점 분기.
    최상위 try/except: 어떤 예외도 로그에 기록 후 메시지박스 표시.
    Silent Crash 방지 — _global_exc_handler가 잡지 못하는 케이스 보완.
    """
    L = "ko"   # main()은 모듈 레벨 — config 접근 전이므로 기본 언어

    # ⚠️ 모든 진입 경로(run.pyw 임포트 실행 포함)에서 반드시 실행.
    # 이전엔 __main__ 가드 안에만 있어 run.pyw 경로에서 faulthandler·excepthook·단일인스턴스가 미실행됐음.
    init_runtime()             # faulthandler(fault.log)·sys.excepthook·번들 폰트
    ensure_single_instance()   # 중복 실행 방지

    _set_dpi_awareness()   # ⚠️ Tk() 생성(ScreesaverApp)보다 먼저

    # 작업표시줄 아이콘 — 고유 AppUserModelID 지정(창 아이콘이 표시줄·핀에 정확히 반영).
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Shugle.MuteAndSaver")
    except Exception:
        pass

    # ⚠️ 자동 순환 GC 끔(A): comtypes(pycaw) 프록시가 json.dump/import 등 불안전 시점에
    #  자동 GC로 Release되며 access violation(확진). 사이클 수거는 메인스레드 유휴에서만
    #  제어적으로 수행(main_window._periodic_gc). refcount 해제는 그대로 동작.
    import gc as _gc
    _gc.disable()

    # 콘솔 분리 (ShowWindow 대신 FreeConsole — 단축키 RegisterHotKey 호환)
    try:
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

    LOG.info(f"[Main] 로그 파일 위치: {LOG_PATH}")

    try:
        mode, parent_hwnd = parse_scr_args(sys.argv)
        LOG.info(f"실행 모드: {mode} (parent_hwnd={parent_hwnd})")

        if mode == "preview":
            LOG.info("미리보기 모드 — 빈 처리 후 종료")
            sys.exit(0)

        if mode == "screensaver":
            app = ScreesaverApp(mode="screensaver")
            app.run()
            return

        if mode == "config":
            app = ScreesaverApp(mode="config")
            app.run()
            return

        # 일반 실행 — 첫 실행 사용권 계약 동의 게이트 (normal 모드 한정)
        from .persistence import load_config, save_config
        from .constants import EULA_VERSION
        from .ui.eula_dialog import needs_eula, show_eula_dialog
        _cfg = load_config()
        if needs_eula(_cfg):
            _lang = _cfg.get("language", "ko")
            if not show_eula_dialog(_lang):
                LOG.info("[Main] 사용권 계약 미동의 — 종료")
                try:
                    ctypes.windll.user32.MessageBoxW(
                        0, t("eula_decline_msg", _lang),
                        t("eula_decline_title", _lang), 0x40)  # MB_ICONINFORMATION
                except Exception:
                    pass
                sys.exit(0)
            _cfg["eula_accepted"] = EULA_VERSION
            save_config(_cfg)
            LOG.info(f"[Main] 사용권 계약 동의 저장 (v{EULA_VERSION})")

        app = ScreesaverApp(mode="normal")
        app.run()

    except SystemExit:
        raise   # sys.exit() 은 그대로 전파
    except Exception as e:
        # Silent Crash 포착 — 로그 + 메시지박스로 원인 노출
        tb_str = traceback.format_exc()
        LOG.critical(
            f"[Main] 치명적 오류로 앱 종료:\n{tb_str}"
        )
        try:
            import ctypes as _ct
            _ct.windll.user32.MessageBoxW(
                0,
                f"Mute&Saver 시작 중 오류가 발생했습니다.\n\n"
                f"{type(e).__name__}: {e}\n\n"
                f"로그 파일을 확인하세요:\n{LOG_PATH}",
                t("msg_err_fatal", L),
                0x10   # MB_ICONERROR
            )
        except Exception:
            pass
        raise



if __name__ == "__main__":
    main()   # init_runtime()·ensure_single_instance()는 main() 최상단에서 실행
