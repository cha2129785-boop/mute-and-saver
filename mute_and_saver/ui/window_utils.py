# -*- coding: utf-8 -*-
"""window_utils — 창 배치 유틸"""
import tkinter as tk

def center_window(win, min_w: int = 0, min_h: int = 0, resizable: bool = False):
    win.update_idletasks()
    w  = max(win.winfo_reqwidth(),  min_w)
    h  = max(win.winfo_reqheight(), min_h)
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    # 화면 밖으로 넘치지 않도록 상한(작업표시줄 여유 포함)
    w  = min(w, sw - 40)
    h  = min(h, sh - 80)
    x  = max(0, (sw - w) // 2)
    y  = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")
    win.resizable(resizable, resizable)
    if resizable:
        # 시작은 측정된 내용 크기로 열되, 하한은 설계 최소치(min_w/min_h)로 → 그만큼 축소 허용.
        # (이전: minsize(w,h)=측정크기 → 시작크기 이하로 못 줄이는 버그)
        win.minsize(min(min_w or w, w), min(min_h or h, h))


class _Tooltip:
    """호버 시 위젯 아래 툴팁 표시 (아이콘 전용 버튼 설명용). 공용 헬퍼."""
    def __init__(self, widget, text: str, delay: int = 500):
        self.widget = widget
        self.text   = text
        self.delay  = delay
        self.tip      = None
        self.after_id = None
        widget.bind("<Enter>",       self._schedule, add="+")
        widget.bind("<Leave>",       self._hide,     add="+")
        widget.bind("<ButtonPress>", self._hide,     add="+")

    def _schedule(self, _e=None):
        self._cancel()
        try:
            self.after_id = self.widget.after(self.delay, self._show)
        except Exception:
            self.after_id = None

    def _show(self):
        if self.tip or not self.text:
            return
        try:
            if not self.widget.winfo_exists():
                return
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            tk.Label(self.tip, text=self.text,
                     bg="#333333", fg="#ffffff",
                     font=("Malgun Gothic", 9), padx=6, pady=3,
                     relief="solid", borderwidth=1, justify="left").pack()
        except Exception:
            self.tip = None

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None

    def _cancel(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None


def add_tooltip(widget, text: str, delay: int = 500):
    """위젯에 툴팁 부착. text는 호출 시점의 (번역된) 문자열."""
    if not text:
        return None
    return _Tooltip(widget, text, delay)
