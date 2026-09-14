# -*- coding: utf-8 -*-
"""
favorites_repository — 즐겨찾기 로드/저장
"""
import json
import logging

from .atomic_file import _atomic_save
from ..constants import FAVORITES_PATH

LOG = logging.getLogger("MuteAndSaver")

def load_favorites() -> list:
    if FAVORITES_PATH.exists():
        try:
            with open(FAVORITES_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("favorites", [])
        except Exception as e:
            LOG.error(f"즐겨찾기 로드 실패: {e}")
    return []

def save_favorites(favs: list):
    _atomic_save(FAVORITES_PATH, {"favorites": favs})
