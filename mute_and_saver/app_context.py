# -*- coding: utf-8 -*-
"""
app_context — 거대 클래스가 기대하는 app 인터페이스 (Protocol)
런타임 강제 없음 — 타입 힌트 + 문서 전용. 기존 duck typing 유지.
"""
from typing import Protocol, Any


class AppContext(Protocol):
    """ScreesaverApp이 충족해야 하는 인터페이스."""
    # 상태
    config: dict
    root: Any                  # tk.Tk
    audio_controller: Any      # SystemAudioController
    _screensaver: Any
    _fs_editor: Any
    _pin_fail_count: int
    _pin_locked_until: float
    _ss_closed_at: float

    # 콜백 (Tray/Window가 호출)
    def _lock_screen(self) -> None: ...
    def _preview_screensaver(self) -> None: ...
    def _open_fullscreen_editor(self) -> None: ...
    def _execute_quick_memo_toggle(self) -> None: ...
    def _show_main_window(self) -> None: ...
    def _toggle_ss_from_tray(self) -> None: ...
    def _toggle_ps_from_tray(self) -> None: ...
    def _on_close(self) -> None: ...
    def _refresh_memo_summary(self) -> None: ...
