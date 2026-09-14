# -*- coding: utf-8 -*-
"""
preset_repository — 사용자 프리셋 로드/저장 + 병합 (오버라이드 레이어)
내장 PRESETS 와 병합해 사용 → 키 충돌 시 사용자 프리셋 우선(내장 수정 효과).
사용자 프리셋 삭제 시: 내장 키면 기본값 복귀, 순수 사용자 키면 소멸.
"""
import json
import logging

from .atomic_file import _atomic_save
from ..constants import USER_PRESETS_PATH, PRESETS

LOG = logging.getLogger("MuteAndSaver")


def load_user_presets() -> dict:
    """user_presets.json 로드. 없으면 빈 dict."""
    try:
        if USER_PRESETS_PATH.exists():
            with open(USER_PRESETS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        LOG.warning(f"[UserPresets] 로드 실패: {e}")
    return {}


def save_user_presets(presets: dict):
    """user_presets.json 원자적 저장."""
    try:
        _atomic_save(USER_PRESETS_PATH, presets)
    except Exception as e:
        LOG.error(f"[UserPresets] 저장 실패: {e}")


def get_all_presets() -> dict:
    """내장 PRESETS + 사용자 프리셋 병합 (사용자 우선)."""
    merged = dict(PRESETS)
    merged.update(load_user_presets())
    return merged
