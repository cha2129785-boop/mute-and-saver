# -*- coding: utf-8 -*-
"""
eula_dialog — 첫 실행 사용권 계약 동의창.
독립 Tk 루트(ScreesaverApp 생성 전 1회). 끝까지 스크롤해야 '동의' 활성.
동의 안 함 → False 반환 → 호출부에서 종료.
"""
import tkinter as tk
from tkinter import font as tkfont

from ..constants import EULA_VERSION, ICON_PATH
from ..i18n import t

# 사용권 계약 본문 (한/영) — EULA.md 와 동일 내용 유지
# ⚠️추정: 법적 강제력은 대한민국 현행법이 정함. 본 문구는 사용허락·금지·면책 고지 목적.
EULA_BODY = {
    "ko": """Mute&Saver 최종 사용자 사용권 계약 (EULA)  —  버전 {ver}

본 소프트웨어(이하 "프로그램")를 설치·실행함으로써, 귀하(이하 "이용자")는
아래 조건에 동의하는 것으로 간주됩니다.

1. 사용 허락
   본 프로그램은 MIT 라이선스 기반 소프트웨어입니다.

2. 금지 행위
   이용자는 다음 행위를 하여서는 안 됩니다.
   (1) 악성코드·백도어를 결합하여 재배포하는 행위
   (2) 타인의 기기를 동의 없이 감시·사찰하는 등 불법 목적 사용
   (3) 저작자 또는 배포자를 사칭하거나 출처 표시를 위·변조하는 행위
   (4) 관련 법령을 위반하는 일체의 목적으로 프로그램을 이용하는 행위

3. 무보증
   본 프로그램은 "있는 그대로" 제공되며, 상품성·특정 목적 적합성 등 어떠한
   명시적·묵시적 보증도 하지 않습니다.

4. 책임의 제한
   본 프로그램의 사용 또는 사용 불능으로 발생한 직접·간접·부수적 손해에 대하여
   저작자 및 배포자는 책임을 지지 않습니다.
   꼭 필요한 내용은 반드시 별도로 백업·저장 하십시오.

5. 데이터·개인정보
   본 프로그램은 외부로 어떠한 데이터도 전송하지 않습니다. 모든 설정·메모는
   이용자 PC(%LOCALAPPDATA%\\MuteAndSaver)에만 저장됩니다.

6. 위반의 효과
   이용자가 제2조를 위반할 경우 본 사용권은 자동 종료되며, 그로 인한 민·형사상
   책임은 전적으로 이용자 본인에게 귀속됩니다. 저작자는 위반 행위에 대하여
   관련 법령에 따른 조치를 취할 수 있습니다.

— 동의하지 않으시면 '동의 안 함'을 눌러 설치를 취소할 수 있습니다. —
""",
    "en": """Mute&Saver End-User License Agreement (EULA)  —  Version {ver}

By installing and running this software (the "Program"), you (the "User")
are deemed to agree to the terms below.

1. License Grant
   The Program is software based on the MIT License.

2. Prohibited Conduct
   The User shall not:
   (1) redistribute the Program bundled with malware or backdoors;
   (2) use it for unlawful purposes such as monitoring another person's device
       without consent;
   (3) impersonate the author or distributor, or falsify attribution;
   (4) use the Program for any purpose that violates applicable law.

3. No Warranty
   The Program is provided "AS IS", without warranty of any kind, express or
   implied, including merchantability or fitness for a particular purpose.

4. Limitation of Liability
   The author and distributor shall not be liable for any direct, indirect, or
   incidental damages arising from use or inability to use the Program.
   Please be sure to separately back up and save any important content.

5. Data & Privacy
   The Program transmits no data externally. All settings and memos are stored
   only on the User's PC (%LOCALAPPDATA%\\MuteAndSaver).

6. Effect of Violation
   If the User breaches Article 2, this license terminates automatically, and
   all civil and criminal liability arising therefrom rests solely with the
   User. The author may take action under applicable law.

— If you do not agree, click "Decline" to cancel the installation. —
""",
}

_BG   = "#2b2e35"
_FG   = "#e5e7eb"
_CARD = "#1f2228"


def needs_eula(cfg: dict) -> bool:
    """현재 EULA 버전 미동의 시 True."""
    return cfg.get("eula_accepted", "") != EULA_VERSION


def show_eula_dialog(lang: str = "ko") -> bool:
    """동의창 표시. True=동의 / False=거부. 자체 mainloop 블로킹."""
    result = {"ok": False}
    view = {"lang": lang if lang in EULA_BODY else "en"}

    root = tk.Tk()
    root.title(t("eula_win_title", lang))
    root.configure(bg=_BG)
    try:
        root.iconbitmap(str(ICON_PATH))
    except Exception:
        pass

    W, H = 760, 620
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 3}")
    root.minsize(560, 420)

    base = tkfont.Font(family="Malgun Gothic", size=10)

    # 본문 + 스크롤바
    frm = tk.Frame(root, bg=_BG)
    frm.pack(fill="both", expand=True, padx=14, pady=(14, 6))
    sb = tk.Scrollbar(frm)
    sb.pack(side="right", fill="y")
    txt = tk.Text(frm, wrap="word", bg=_CARD, fg=_FG, font=base,
                  relief="flat", padx=12, pady=10, spacing1=1, spacing3=3,
                  insertbackground=_FG)
    txt.pack(side="left", fill="both", expand=True)
    sb.config(command=txt.yview)

    hint = tk.Label(root, bg=_BG, fg="#9ca3af", font=(base.cget("family"), 9))
    hint.pack(fill="x", padx=16)

    btns = tk.Frame(root, bg=_BG)
    btns.pack(fill="x", padx=14, pady=(4, 14))

    def _on_scroll(first, last):
        sb.set(first, last)
        if float(last) >= 0.999:          # 끝까지 확인 → 동의 활성
            agree.config(state="normal")
            hint.config(text="")
    txt.config(yscrollcommand=_on_scroll)

    def _load_body():
        txt.config(state="normal")
        txt.delete("1.0", "end")
        txt.insert("1.0", EULA_BODY[view["lang"]].format(ver=EULA_VERSION))
        txt.config(state="disabled")
        txt.yview_moveto(0.0)
        agree.config(state="disabled")
        hint.config(text=t("eula_scroll_hint", lang))
        root.after(50, _recheck)

    def _recheck():
        # 내용이 창보다 짧아 스크롤 불필요하면 즉시 활성
        f, l = txt.yview()
        if float(l) >= 0.999:
            agree.config(state="normal")
            hint.config(text="")

    def _toggle_lang():
        view["lang"] = "en" if view["lang"] == "ko" else "ko"
        _load_body()

    def _agree():
        result["ok"] = True
        root.destroy()

    def _decline():
        result["ok"] = False
        root.destroy()

    tk.Button(btns, text=t("eula_lang_toggle", lang), command=_toggle_lang,
              bg="#4b5563", fg="white", relief="flat", padx=12, pady=6,
              activebackground="#5b6573", cursor="hand2").pack(side="left")
    tk.Button(btns, text=t("eula_disagree", lang), command=_decline,
              bg="#6b7280", fg="white", relief="flat", padx=16, pady=6,
              activebackground="#7b8290", cursor="hand2").pack(side="right")
    agree = tk.Button(btns, text=t("eula_agree", lang), command=_agree,
                      bg="#059669", fg="white", relief="flat", padx=20, pady=6,
                      activebackground="#0ea371", cursor="hand2",
                      state="disabled")
    agree.pack(side="right", padx=(0, 8))

    root.protocol("WM_DELETE_WINDOW", _decline)   # 창 닫기 = 거부
    _load_body()
    try:
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
    except Exception:
        pass
    root.mainloop()
    return result["ok"]
