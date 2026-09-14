# -*- coding: utf-8 -*-
"""
atomic_file — 원자적 파일 저장
실패 시 예외 전파 + 임시파일 정리 + fsync
"""
import os
import json
import logging
from pathlib import Path

LOG = logging.getLogger("MuteAndSaver")

def _atomic_save(path: Path, data: dict):
    """tempfile → os.replace 원자적 저장. 실패 시 예외 전파."""
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        LOG.debug(f"저장 완료: {path.name}")
    except Exception:
        LOG.exception(f"저장 실패: {path}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            LOG.exception(f"임시 파일 삭제 실패: {tmp}")
        raise
