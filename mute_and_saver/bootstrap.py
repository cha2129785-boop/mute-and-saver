# -*- coding: utf-8 -*-
"""
bootstrap — 로깅 설정 + 전역 예외 핸들러 + 디렉토리/폰트 초기화
"""
import sys
import logging
import traceback
from logging.handlers import RotatingFileHandler

from .constants import LOG_PATH, FONTS_DIR, APP_NAME
from .platform.windows.font_engine import FontEngine

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(funcName)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    try:
        fh = RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding='utf-8'
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)
    return logger

LOG = _setup_logger()

font_engine = None   # init_runtime() 실행 후 FontEngine 인스턴스 보관 (main_window._on_close 참조용)

def _global_exc_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    LOG.critical(
        "처리되지 않은 예외:\n" +
        "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    )


def init_runtime():
    """로깅 + 예외 핸들러 + 폰트 로딩 일괄 초기화."""
    sys.excepthook = _global_exc_handler
    # ⚠️ 진단용: 네이티브 크래시(access violation) C 스택 기록
    try:
        import faulthandler
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)   # 로그 폴더 보장(없으면 open 실패)
        _fault_path = LOG_PATH.parent / "fault.log"
        _fault_file = open(_fault_path, "a", encoding="utf-8")
        faulthandler.enable(file=_fault_file, all_threads=True)
        LOG.info(f"[Diag] faulthandler 활성화: {_fault_path}")
    except Exception as _e:
        LOG.warning(f"[Diag] faulthandler 실패: {_e}")
    global font_engine
    font_engine = FontEngine()
    try:
        loaded = font_engine.load_directory(FONTS_DIR)
        LOG.info(f"번들 폰트 로딩: {loaded}개" if loaded else "번들 폰트 디렉토리 비어있음 — 시스템 폰트 사용")
    except Exception as e:
        LOG.warning(f"폰트 로딩 실패: {e}")
    return font_engine
