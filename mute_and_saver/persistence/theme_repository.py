# -*- coding: utf-8 -*-
"""
theme_repository — 사용자 테마 로드/저장 + 병합
"""
import json
import logging

from .atomic_file import _atomic_save
from ..constants import USER_THEMES_PATH, MEMO_BG_THEMES

LOG = logging.getLogger("MuteAndSaver")

def load_user_themes() -> dict:
    """
    user_themes.json 로드. 없으면 빈 dict 반환.
    내장 MEMO_BG_THEMES와 병합해서 사용 → 키 충돌 시 사용자 테마 우선.
    """
    try:
        if USER_THEMES_PATH.exists():
            with open(USER_THEMES_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        LOG.warning(f"[UserThemes] 로드 실패: {e}")
    return {}


def save_user_themes(themes: dict):
    """user_themes.json 원자적 저장."""
    try:
        _atomic_save(USER_THEMES_PATH, themes)
    except Exception as e:
        LOG.error(f"[UserThemes] 저장 실패: {e}")


def get_all_themes() -> dict:
    """
    내장 테마 + 사용자 테마 병합.
    사용자 테마가 같은 key 존재 시 덮어씀 (사용자 우선).
    """
    merged = dict(MEMO_BG_THEMES)
    merged.update(load_user_themes())
    return merged
