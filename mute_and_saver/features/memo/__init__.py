# -*- coding: utf-8 -*-
"""
features.memo — 메모 기능
⚠️ viewer/editor는 persistence에 의존하므로 패키지 로드 시점에 import하지 않음.
   (persistence.memo_repository가 coordinates를 import → 순환 방지)
   필요 시 `from mute_and_saver.features.memo.viewer import MemoBoardViewer` 직접 import.
"""
from .coordinates import _abs_to_rel
from .models import (
    new_memo_template, _memo_text_color,
    _get_visible_memos, _is_scheduled_now,
)

__all__ = [
    "_abs_to_rel",
    "new_memo_template", "_memo_text_color",
    "_get_visible_memos", "_is_scheduled_now",
]


def __getattr__(name):
    # lazy import — MemoBoardViewer / FullscreenMemoEditor
    if name == "MemoBoardViewer":
        from .viewer import MemoBoardViewer
        return MemoBoardViewer
    if name == "FullscreenMemoEditor":
        from .editor import FullscreenMemoEditor
        return FullscreenMemoEditor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
