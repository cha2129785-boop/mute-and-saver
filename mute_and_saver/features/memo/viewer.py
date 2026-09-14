# -*- coding: utf-8 -*-
"""
viewer — MemoBoardViewer: 화면보호기 메모보드 렌더링 (PIL 합성)
"""
import logging
import threading
import tkinter as tk

LOG = logging.getLogger("MuteAndSaver")

try:
    from PIL import Image, ImageTk, ImageFilter
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from ...constants import MEMO_BG_THEMES, MEMO_COLORS, _CANVAS_BG, _blend_color, TEXT_COLORS, _darken
from ...media.image_rendering import _safe_font, _render_canvas_bg
from ...persistence import load_memos, get_all_themes, _migrate_legacy_memos
from .models import (_get_visible_memos, _is_scheduled_now, _memo_text_color,
                     resolve_text_color)


def _calc_header_h(title_fs: int) -> int:
    """
    제목 폰트 크기 → 헤더 Frame 높이 반환.
    최소 26px 보장 (기존 HEADER_H 하한 유지).
    24pt 시 약 38px — 카드 최소 높이와 충분한 여유.
    """
    return max(26, title_fs + 14)   # 상하 여백 7px × 2


class MemoBoardViewer:
    """
    화면보호기 실행 중 포스트잇 표시 전용 렌더러.
    이벤트 바인딩 없음 — 클릭·드래그 불가.
    에디터 캔버스 좌표를 실제 화면 해상도로 비율 보정하여 배치.
    """
    HEADER_H = 26

    def __init__(self, parent_win: tk.Misc,
                 sw: int, sh: int, app,
                 x: int = 0, y: int = 0, is_secondary: bool = False):
        self.sw      = sw
        self.sh      = sh
        self.app     = app
        self._is_secondary = is_secondary  # 보조 모니터 뷰어 → 전역 media 가드 무시
        self._frames: list = []
        self._blur_cache = None
        self._blur_cache_size = (0, 0)
        LOG.info("[MemoBoard] 3. 새 MemoBoardViewer 캔버스 생성 시작")
        self.canvas  = tk.Canvas(
            parent_win, bg="black",
            highlightthickness=0, bd=0
        )
        self.canvas.place(x=x, y=y, width=sw, height=sh)
        LOG.info("[MemoBoard] 4. 새 MemoBoardViewer 캔버스 메모리 할당 완료")

    def render(self):
        # ── 모드 체크: 미디어 전용 모드면 캔버스 숨기고 종료 ────
        # 미디어 모드에서 render()가 강제 호출될 경우 canvas가 lbl_bg 위를 덮어
        # 영상이 보이지 않는 현상 방지. place_forget()으로 완전 격리.
        # 보조 모니터 뷰어(is_secondary)는 별도 창이라 전역 media 모드와 무관하게 항상 렌더.
        mode = self.app.config.get("screensaver_mode", "media")
        if mode == "media" and not self._is_secondary:
            try:
                self.canvas.place_forget()
            except Exception:
                pass
            return

        # ── 배경 테마 렌더 ──────────────────────────────────
        theme_key  = self.app.config.get("memo_bg_theme", "paper")
        all_themes = get_all_themes()
        theme      = all_themes.get(theme_key, MEMO_BG_THEMES["paper"])
        use_blur   = self.app.config.get("memo_bg_blur", False) and _HAS_PIL
        global_opacity = self.app.config.get("memo_opacity", 0.0)
        use_pil_composite = global_opacity > 0.01

        # 1단계: 배경 테마 렌더 (공통)
        _render_canvas_bg(self.canvas, self.sw, self.sh, theme)

        # 2단계: 블러 처리
        if use_blur:
            if use_pil_composite:
                # PIL 합성 모드: 블러를 동기 실행 → _origin_theme_img 교체
                # 비동기 스레드가 나중에 bg_layer 삭제하는 경쟁 조건 원천 차단
                self._sync_blur_for_composite()
            else:
                # 기존 방식: 비동기 블러 (tk.Frame 카드는 bg_layer 위에 자동 표시)
                cache_valid = (
                    self._blur_cache is not None and
                    self._blur_cache_size == (self.sw, self.sh)
                )
                if cache_valid:
                    self._apply_memo_blur(self._blur_cache)
                else:
                    threading.Thread(
                        target=self._capture_memo_blur,
                        daemon=True
                    ).start()

        is_premium = self.app.config.get("is_premium", False)
        all_memos  = load_memos()
        visible    = _get_visible_memos(all_memos, is_premium)

        # ── 스케줄 필터 (Viewer 전용) ────────────────────────────────
        # FSEditor는 스케줄 무관하게 전체 표시 → 유령 메모 방지
        # Viewer만 현재 시각 기준으로 표시 여부 결정
        visible = [m for m in visible if _is_scheduled_now(m)]

        # ── 좌표 기준 ────────────────────────────────────────────────
        # render()는 rel_* 기반 단일 좌표계만 읽음 (Zero-Dashboard 확정)
        # FSEditor가 실제 픽셀로 저장 → rel_x * self.sw = 정확한 픽셀
        # 구버전(rel_* 없음) 메모는 _migrate_legacy_memos()에서 일괄 변환됨
        # src_w/sx/sy 레거시 계산 완전 삭제:
        #   이전: sx = self.sw / src_w(600) = 3.2 → 폰트/카드 3.2배 왜곡
        #   이후: 폰트는 메모 저장값 그대로 사용, 좌표는 rel_* × sw
        # ─────────────────────────────────────────────────────────────
        MIN_W, MIN_H = 80, 50

        LOG.info(f"[MemoBoard] 5. 메모 데이터 렌더링 루프 진입 (총 {len(visible)}개)")
        if use_pil_composite:
            # PIL 합성: 배경 이미지 위에 반투명 카드 직접 합성
            self._render_cards_pil(visible, global_opacity)
        else:
            for memo in sorted(visible, key=lambda m: m.get("z_order", 0)):
                if "rel_x" in memo:
                    x = int(memo["rel_x"] * self.sw)
                    y = int(memo["rel_y"] * self.sh)
                    w = int(memo["rel_w"] * self.sw)
                    h = int(memo["rel_h"] * self.sh)
                else:
                    LOG.warning(f"[Viewer] rel_* 없는 메모 발견: {memo.get('id')} → 폴백 배치")
                    x = min(memo.get("x", 60),   self.sw - MIN_W)
                    y = min(memo.get("y", 60),   self.sh - MIN_H)
                    w = min(memo.get("width", 220),  self.sw // 3)
                    h = min(memo.get("height", 160), self.sh // 3)
                w = max(MIN_W, w)
                h = max(MIN_H, h)
                LOG.info(f"[MemoBoard] 6. 메모 ID={memo.get('id')} _place_card 시작 (x={x} y={y} w={w} h={h})")
                self._place_card(memo, x=x, y=y, w=w, h=h)
                LOG.info(f"[MemoBoard] 7. 메모 ID={memo.get('id')} _place_card 완료")
        LOG.info("[MemoBoard] 8. 렌더링 루프 완료")

    def _capture_memo_blur(self):
        """
        테마 원본 이미지(canvas._origin_theme_img)를 소스로 GaussianBlur 적용.
        스크린샷 방식 완전 제거 → 테마가 온전히 블러에 반영됨.
        백그라운드 스레드 실행 → 완성 시 _apply_memo_blur로 메인 스레드 전달.
        캐시: 1회 계산 후 재사용 — 해상도 변경 시만 재계산.
        """
        try:
            origin = getattr(self.canvas, '_origin_theme_img', None)
            if origin is None:
                LOG.debug("[MemoBoardBlur] origin_theme_img 없음 → 블러 생략")
                return

            # 사용자 입력 0~10 → PIL GaussianBlur radius 0~5 선형 매핑 (× 0.5)
            user_val = self.app.config.get("memo_blur_radius", 1)
            pil_radius = max(0, min(5, user_val * 0.5))

            if pil_radius == 0:
                blurred = origin.copy()   # 블러 없음 → 원본 그대로
            else:
                blurred = origin.copy().filter(
                    ImageFilter.GaussianBlur(radius=pil_radius)
                )

            self._blur_cache      = blurred
            self._blur_cache_size = (self.sw, self.sh)

            try:
                self.canvas.after(0, lambda: self._apply_memo_blur(blurred))
            except Exception:
                pass
        except Exception as e:
            LOG.warning(f"[MemoBoardBlur] 블러 생성 실패: {e}")

    def _apply_memo_blur(self, pil_img):
        """
        메인 스레드 — 블러 이미지를 Layer 2로 배치.
        레이어 순서:
          Layer 0: canvas.bg (테마 solid 색상)
          Layer 1: bg_layer  (테마 패턴/그라데이션 이미지)
          Layer 1: bg_blur (테마+블러 이미지 단독 — bg_layer 불필요)
          Layer 2: 카드 위젯 (create_window, 항상 Canvas item 위)
        """
        try:
            if not self.canvas.winfo_exists():
                return
            photo = ImageTk.PhotoImage(pil_img)
            # bg_layer(테마 원본)은 bg_blur에 이미 포함 → 삭제
            self.canvas.delete("bg_layer")
            self.canvas.delete("bg_blur")
            self.canvas.create_image(
                0, 0, anchor="nw", image=photo, tags="bg_blur"
            )
            self.canvas._blur_ref = photo     # GC 방지
            self.canvas._blur_img = pil_img   # PIL Image 유지 (재사용)
            # 카드 위젯은 create_window → 항상 Canvas item 위 (tag 불필요)
        except Exception as e:
            LOG.warning(f"[MemoBoardBlur] 적용 실패: {e}")

    def _sync_blur_for_composite(self):
        """
        PIL 합성 모드 전용 — 블러를 동기 실행하여 _origin_theme_img를 교체.
        _apply_memo_blur(bg_layer 삭제)를 호출하지 않으므로
        _render_cards_pil의 itemconfig("bg_layer") 경로와 충돌하지 않음.
        """
        try:
            origin = getattr(self.canvas, '_origin_theme_img', None)
            if origin is None:
                LOG.debug("[SyncBlur] origin_theme_img 없음 → 블러 생략")
                return
            user_val = self.app.config.get("memo_blur_radius", 1)
            pil_radius = max(0, min(5, user_val * 0.5))
            if pil_radius == 0:
                return   # 블러 0 → 원본 유지
            blurred = origin.copy().filter(
                ImageFilter.GaussianBlur(radius=pil_radius)
            )
            # _origin_theme_img를 블러 결과로 교체 → _render_cards_pil이 이것을 사용
            self.canvas._origin_theme_img = blurred
            self._blur_cache      = blurred
            self._blur_cache_size = (self.sw, self.sh)
            LOG.info(f"[SyncBlur] 동기 블러 완료 (radius={pil_radius})")
        except Exception as e:
            LOG.warning(f"[SyncBlur] 블러 실패: {e}")

    def _render_cards_pil(self, visible, global_opacity):
        """
        단일 이미지 합성(Flattening) 방식.
        배경 원본 위에 모든 메모 카드를 PIL alpha_composite로 합성한 뒤
        기존 bg_layer 이미지를 itemconfig로 교체. z-order 조작 불필요.
        텍스트는 canvas.create_text로 배경 위에 직접 표시.
        """
        from PIL import Image, ImageTk, ImageDraw
        origin = getattr(self.canvas, '_origin_theme_img', None)
        LOG.info(f"[PIL_Flatten] 단일 이미지 합성 시작 — origin={origin is not None}, opacity={global_opacity}")
        if origin is None:
            LOG.warning("[PIL_Flatten] origin_theme_img 없음 → 기존 _place_card 폴백")
            for memo in sorted(visible, key=lambda m: m.get("z_order", 0)):
                if "rel_x" in memo:
                    x = int(memo["rel_x"] * self.sw)
                    y = int(memo["rel_y"] * self.sh)
                    w = int(memo["rel_w"] * self.sw)
                    h = int(memo["rel_h"] * self.sh)
                else:
                    x, y = memo.get("x", 60), memo.get("y", 60)
                    w, h = memo.get("width", 220), memo.get("height", 160)
                self._place_card(memo, x=x, y=y, w=max(80,w), h=max(50,h))
            return

        alpha_val = max(0, min(255, int((1.0 - global_opacity) * 255)))
        composite = origin.copy().convert("RGBA")

        # 좀비 텍스트 방지
        self.canvas.delete("memo_text")

        MIN_W, MIN_H = 80, 50
        text_items = []

        for idx, memo in enumerate(sorted(visible, key=lambda m: m.get("z_order", 0))):
            try:
                if "rel_x" in memo:
                    x = int(memo["rel_x"] * self.sw)
                    y = int(memo["rel_y"] * self.sh)
                    w = int(memo["rel_w"] * self.sw)
                    h = int(memo["rel_h"] * self.sh)
                else:
                    x = min(memo.get("x", 60), self.sw - MIN_W)
                    y = min(memo.get("y", 60), self.sh - MIN_H)
                    w = min(memo.get("width", 220), self.sw // 3)
                    h = min(memo.get("height", 160), self.sh // 3)
                w, h = max(MIN_W, w), max(MIN_H, h)
                x = max(0, min(x, self.sw - w))
                y = max(0, min(y, self.sh - h))

                color_key = memo.get("color_key", "yellow")
                if isinstance(color_key, str) and color_key.startswith("#"):
                    bg_hex, hdr_hex = color_key, _darken(color_key)
                else:
                    bg_hex, hdr_hex = MEMO_COLORS.get(color_key, MEMO_COLORS["yellow"])

                def hex2rgb(hx):
                    hx = hx.lstrip("#")
                    return tuple(int(hx[i:i+2], 16) for i in (0, 2, 4))

                bg_rgb  = hex2rgb(bg_hex)
                hdr_rgb = hex2rgb(hdr_hex)
                fg_hex  = _memo_text_color(color_key)
                title_fg_hex = resolve_text_color(memo.get("title_text_color"), fg_hex)
                body_fg_hex  = resolve_text_color(memo.get("body_text_color"),  fg_hex)
                collapsed = memo.get("collapsed", False)
                tfs = max(8, memo.get("title_font_size", 11))
                hdr_h = _calc_header_h(tfs)
                card_h = hdr_h if collapsed else h

                # ── 이미지 메모(폴라로이드): 흰 카드 + 사진 상단 + 제목바 하단 ──
                if not collapsed and memo.get("kind") == "image":
                    hh = min(hdr_h, card_h)
                    ov = Image.new("RGBA", (w, card_h), (255, 255, 255, alpha_val))
                    hdr_ov = Image.new("RGBA", (w, hh), (*hdr_rgb, alpha_val))
                    ov.paste(hdr_ov, (0, card_h - hh))
                    try:
                        im = Image.open(memo.get("image_path")).convert("RGBA")
                        aw = max(1, w - 16); ah = max(1, card_h - hh - 16)
                        im.thumbnail((aw, ah), Image.LANCZOS)
                        ox = max(0, (w - im.width) // 2)
                        oy = 8 + max(0, (ah - im.height) // 2)
                        ov.alpha_composite(im, dest=(ox, oy))
                    except Exception as _ie:
                        LOG.error(f"[PIL_Flatten] 이미지 로드 실패: {_ie}")
                    composite.alpha_composite(ov, dest=(x, y))
                    # 제목(캡션) — 하단 헤더
                    title = memo.get("title", "")[:80]
                    pin = "📌 " if memo.get("pinned") else ""
                    text_items.append({
                        "x": x + 5, "y": y + card_h - hh + max(2, (hh - tfs) // 2 - 2),
                        "text": f"{pin}{title}", "fill": title_fg_hex,
                        "fs": tfs, "bold": True, "width": w - 10,
                        "align": memo.get("title_align", "l"),
                    })
                    LOG.info(f"[PIL_Flatten] 이미지 메모 {idx+1} 합성")
                    continue

                # 메모 카드 오버레이 합성
                overlay = Image.new("RGBA", (w, card_h), (*bg_rgb, alpha_val))
                hdr_overlay = Image.new("RGBA", (w, min(hdr_h, card_h)), (*hdr_rgb, alpha_val))
                overlay.paste(hdr_overlay, (0, 0))
                composite.alpha_composite(overlay, dest=(x, y))

                # 텍스트 정보 저장
                title = memo.get("title", "")[:80]
                pin   = "📌 " if memo.get("pinned") else ""
                mark  = " ▶" if collapsed else ""   # 펼침 시 역삼각형 제거(뷰어)
                text_items.append({
                    "x": x + 5, "y": y + 4,
                    "text": f"{pin}{title}{mark}",
                    "fill": title_fg_hex, "fs": tfs, "bold": True,
                    "width": w - 10,
                    "align": memo.get("title_align", "l"),
                })
                if not collapsed and memo.get("kind") == "table":
                    # 표: 본문 영역에 격자선(ImageDraw) + 셀 텍스트(canvas)
                    tbl   = memo.get("table") or {}
                    rows  = max(1, int(tbl.get("rows", 1)))
                    cols  = max(1, int(tbl.get("cols", 1)))
                    cells = tbl.get("cells") or []
                    by    = y + hdr_h
                    bh    = max(1, card_h - hdr_h)
                    cell_w = w / cols
                    cell_h = bh / rows
                    drw = ImageDraw.Draw(composite)
                    # 표 본문 기본 흰색 선채움(편집기와 동일) — 테마색 비침 방지
                    drw.rectangle([int(x), int(by), int(x + w), int(y + card_h)],
                                  fill=(255, 255, 255, alpha_val))
                    # 셀 배경색 채우기(격자선보다 먼저)
                    cell_bg = tbl.get("cell_bg") or {}
                    cell_fg = tbl.get("cell_fg") or {}
                    cell_align = tbl.get("cell_align") or {}
                    for key, hx in cell_bg.items():
                        try:
                            rr_s, cc_s = key.split(",")
                            rr_i, cc_i = int(rr_s), int(cc_s)
                            if not (0 <= rr_i < rows and 0 <= cc_i < cols):
                                continue
                            cx0 = int(x + cc_i * cell_w); cy0 = int(by + rr_i * cell_h)
                            cx1 = int(x + (cc_i + 1) * cell_w); cy1 = int(by + (rr_i + 1) * cell_h)
                            cr = tuple(int(hx.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
                            drw.rectangle([cx0, cy0, cx1, cy1], fill=(*cr, alpha_val))
                        except Exception:
                            pass
                    cfamily = memo.get("font_family", "Malgun Gothic")
                    # 내부 격자선: 1px 회색(깔끔) — 편집기 #888888 대응
                    line_rgb = (136, 136, 136, 255)
                    for cc in range(cols + 1):
                        lx = int(x + cc * cell_w)
                        drw.line([(lx, by), (lx, y + card_h)], fill=line_rgb, width=1)
                    for rr in range(rows + 1):
                        ly = int(by + rr * cell_h)
                        drw.line([(x, ly), (x + w, ly)], fill=line_rgb, width=1)
                    # 표 바깥 테두리: 헤더~본문 전체를 감싸는 프레임.
                    # 헤더색과 동일하면 헤더 구간에서 묻히므로 살짝 진한 톤(0.65)으로.
                    _bd = tuple(int(c * 0.65) for c in hdr_rgb)
                    drw.rectangle([int(x), int(y), int(x + w) - 1, int(y + card_h) - 1],
                                  outline=(*_bd, 255), width=2)
                    cfs = max(8, memo.get("body_font_size", 10))
                    for rr in range(rows):
                        for cc in range(cols):
                            val = cells[rr][cc] if (rr < len(cells) and cc < len(cells[rr])) else ""
                            if not val:
                                continue
                            text_items.append({
                                "x": int(x + cc * cell_w) + 4,
                                "y": int(by + rr * cell_h) + 3,
                                "text": val,
                                "fill": cell_fg.get(f"{rr},{cc}", body_fg_hex),
                                "fs": cfs, "bold": False,
                                "width": max(10, int(cell_w) - 8),
                                "family": cfamily,
                                "clip": True,   # 셀: 단일행 클립(편집기 Entry와 일치)
                                "align": cell_align.get(f"{rr},{cc}", "l"),
                            })
                elif not collapsed:
                    body = memo.get("body", "")[:300]
                    if body:
                        lc = memo.get("line_colors") or {}
                        la = memo.get("line_align") or {}
                        _bda = memo.get("body_align", "l")
                        lines = body.split("\n")
                        text_items.append({
                            "x": x + 6, "y": y + hdr_h + 6,
                            "body_lines": [
                                (ln, lc.get(str(i), body_fg_hex),
                                 la.get(str(i), _bda))
                                for i, ln in enumerate(lines)
                            ],
                            "fill": body_fg_hex,
                            "fs": max(8, memo.get("body_font_size", 10)),
                            "bold": False, "width": w - 12,
                            "family": cfamily if memo.get("kind") == "table"
                                      else memo.get("font_family", "Malgun Gothic"),
                        })
                LOG.info(f"[PIL_Flatten] 메모 {idx+1} 합성 (x={x} y={y} w={w} h={card_h})")
            except Exception as e:
                import traceback as _tb
                LOG.error(f"[PIL_Flatten] 메모 {idx} 합성 오류: {e}\n{_tb.format_exc()}")

        # 단일 이미지로 bg_layer 교체 (z-order 변동 없음)
        composite_photo = ImageTk.PhotoImage(composite.convert("RGB"))
        try:
            self.canvas.itemconfig("bg_layer", image=composite_photo)
        except Exception:
            # itemconfig 실패 시 create_image 폴백
            self.canvas.delete("bg_layer")
            self.canvas.create_image(0, 0, image=composite_photo,
                                     anchor="nw", tags="bg_layer")
        self.canvas._bg_photo = composite_photo   # GC 방지
        # 진단: bg_layer 아이템 존재 확인 + 화면 즉시 갱신
        bg_items = self.canvas.find_withtag("bg_layer")
        LOG.info(f"[PIL_Flatten] bg_layer 아이템: {bg_items}")
        try:
            self.canvas.update()
        except Exception:
            pass

        # 텍스트 레이어 (배경 위에 자동 표시)
        import tkinter.font as _tkfont

        def _align_pos(align, box_x, box_w, top=False):
            """정렬(l/c/r) → (그릴 x, anchor). top=True면 세로 상단 유지."""
            if align == "c":
                return box_x + box_w / 2, ("n" if top else "n")
            if align == "r":
                return box_x + box_w, ("ne" if top else "ne")
            return box_x, ("nw" if top else "nw")

        for ti in text_items:
            _fnt = _safe_font(ti.get("family", "Arial"), ti["fs"],
                              "bold" if ti["bold"] else "")
            bw = ti.get("width") or 0
            if ti.get("body_lines") is not None:
                # 본문 줄별(색·정렬) 렌더: 각 줄 wrap 그린 뒤 bbox 높이만큼 y 전진
                cur_y = ti["y"]
                for entry in ti["body_lines"]:
                    ln, col = entry[0], entry[1]
                    al = entry[2] if len(entry) > 2 else "l"
                    dx, anc = _align_pos(al, ti["x"], bw)
                    tid = self.canvas.create_text(
                        dx, cur_y, text=ln or " ", fill=col,
                        font=_fnt, anchor=anc, width=bw, tags="memo_text")
                    try:
                        bb = self.canvas.bbox(tid)
                        cur_y += (bb[3] - bb[1]) if bb else (ti["fs"] + 4)
                    except Exception:
                        cur_y += ti["fs"] + 4
                continue
            al = ti.get("align", "l")
            if ti.get("clip"):
                # 셀: 줄바꿈 금지 + 폭 초과분 잘라냄(편집기 Entry와 동일)
                txt = ti["text"]
                try:
                    fm = _tkfont.Font(font=_fnt)
                    if fm.measure(txt) > bw:
                        while txt and fm.measure(txt) > bw:
                            txt = txt[:-1]
                except Exception:
                    pass
                dx, anc = _align_pos(al, ti["x"], bw, top=True)
                self.canvas.create_text(
                    dx, ti["y"], text=txt, fill=ti["fill"],
                    font=_fnt, anchor=anc, tags="memo_text")
            else:
                dx, anc = _align_pos(al, ti["x"], bw)
                self.canvas.create_text(
                    dx, ti["y"], text=ti["text"], fill=ti["fill"],
                    font=_fnt, anchor=anc, width=bw, tags="memo_text")
        LOG.info(f"[PIL_Flatten] 완료 — 메모 {len(text_items)}개 텍스트 배치")

    def _place_card(self, memo: dict, x, y, w, h):
        color_key = memo.get("color_key", "yellow")
        if isinstance(color_key, str) and color_key.startswith("#"):
            bg, hdr = color_key, _darken(color_key)
        else:
            bg, hdr = MEMO_COLORS.get(color_key, MEMO_COLORS["yellow"])
        # global_opacity: 전체 투명도 (0.0=불투명, 1.0=투명)
        global_opacity = self.app.config.get("memo_opacity", 0.0)
        if global_opacity > 0.01:
            theme_key   = self.app.config.get("memo_bg_theme", "paper")
            theme_color = get_all_themes().get(theme_key, {}).get("color", "#fafaf7")
            bg  = _blend_color(bg,  theme_color, 1.0 - global_opacity)
            hdr = _blend_color(hdr, theme_color, 1.0 - global_opacity)
        fg        = _memo_text_color(memo.get("color_key","yellow"))
        title_fg  = resolve_text_color(memo.get("title_text_color"), fg)
        body_fg   = resolve_text_color(memo.get("body_text_color"),  fg)
        family    = memo.get("font_family", "Malgun Gothic")
        collapsed = memo.get("collapsed", False)

        # 폰트 크기: 저장값 그대로 사용 (sx 배율 계산 완전 제거)
        # 이전: tfs = 11 * sx(3.2) = 35pt → 폰트 3.2배 왜곡
        # 이후: 저장된 값 그대로 — FSEditor에서 실제 픽셀 기준으로 이미 확정됨
        tfs   = max(8, memo.get("title_font_size", 11))
        bfs   = max(8, memo.get("body_font_size",  10))
        hdr_h = _calc_header_h(tfs)

        # 이미지 메모(폴라로이드): 사진 상단 + 캡션 하단 — 비PIL(기본 투명도) 경로 대응
        if not collapsed and memo.get("kind") == "image" and _HAS_PIL:
            self._place_image_card(memo, x, y, max(80, w), max(60, h),
                                   hdr, title_fg, tfs, family, hdr_h)
            return

        card_h_init = hdr_h if collapsed else max(hdr_h + 20, h)

        # 카드 너비: rel_w * sw 결과값(w) 그대로 사용 (800*sx 상한 제거)
        title_text = memo.get("title","")[:100]
        tmp_font   = _safe_font(family, tfs, "bold")
        import tkinter.font as _tkfont
        try:
            text_pixel_w = _tkfont.Font(font=tmp_font).measure(title_text)
        except Exception:
            text_pixel_w = 0
        # 제목 픽셀 폭 초과 시 카드 너비 확장 (상한: 메모 영역 너비의 80%)
        target_w = max(w, min(int(self.sw * 0.8), text_pixel_w + 40))

        outer = tk.Frame(self.canvas, width=target_w, height=card_h_init,
                         bg=bg, relief="flat", bd=0)
        outer.pack_propagate(False)

        header = tk.Frame(outer, bg=hdr)
        header.pack(fill="x", side="top")

        pad_y = max(3, int(tfs * 0.5))
        tk.Label(header, text=title_text,
                 bg=hdr, fg=title_fg,
                 font=tmp_font,
                 anchor="nw",
                 justify="left",
                 wraplength=max(40, target_w - 30)   # 고정 여백 30px
                 ).pack(side="left", padx=5, pady=pad_y, fill="x", expand=True)

        if collapsed:   # 펼침 시 역삼각형 제거(뷰어)
            tk.Label(header, text="▶",
                     bg=hdr, fg=title_fg, font=("Arial", 8)
                     ).pack(side="right", padx=4)

        if memo.get("pinned"):
            tk.Label(header, text="📌", bg=hdr, font=("Arial",9)).pack(side="right", padx=2)

        header.update_idletasks()
        actual_hdr_h = header.winfo_reqheight()
        card_h = actual_hdr_h if collapsed else max(actual_hdr_h + 30, h)
        outer.config(height=card_h)

        if not collapsed:
            if memo.get("kind") == "table":
                grid = self._build_table_view(outer, memo, bg, body_fg, bfs)
                grid.pack(fill="both", expand=True, padx=2, pady=2)
            else:
                body_font = _safe_font(family, bfs)
                body = tk.Text(outer, bg=bg, fg=body_fg, relief="flat", bd=4,
                               font=body_font,
                               wrap="word", cursor="arrow", state="normal")
                body.insert("1.0", memo.get("body",""))
                body.config(state="disabled")
                body.pack(fill="both", expand=True, padx=2, pady=2)

        self.canvas.create_window(x, y, window=outer, anchor="nw")
        self._frames.append(outer)

    def _place_image_card(self, memo, x, y, w, h, hdr, title_fg, tfs, family, hdr_h):
        """이미지 메모(폴라로이드) 뷰어 렌더 — 흰 카드 + 사진 상단 + 캡션 하단."""
        outer = tk.Frame(self.canvas, width=w, height=h,
                         bg="#ffffff", relief="flat", bd=0)
        outer.pack_propagate(False)
        # 캡션(하단 헤더)
        header = tk.Frame(outer, bg=hdr)
        header.pack(fill="x", side="bottom")
        pin = "📌 " if memo.get("pinned") else ""
        _anchor = {"l": "w", "c": "center", "r": "e"}.get(memo.get("title_align", "l"), "w")
        tk.Label(header, text=f"{pin}{memo.get('title','')[:100]}",
                 bg=hdr, fg=title_fg, font=_safe_font(family, tfs, "bold"),
                 anchor=_anchor, wraplength=max(40, w - 16)
                 ).pack(fill="x", padx=5, pady=max(3, int(tfs * 0.4)))
        # 사진(상단, 남은 영역)
        photo_host = tk.Frame(outer, bg="#ffffff")
        photo_host.pack(fill="both", expand=True)
        try:
            im = Image.open(memo.get("image_path")).convert("RGBA")
            aw = max(1, w - 16); ah = max(1, h - hdr_h - 16)
            im.thumbnail((aw, ah), Image.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            lbl = tk.Label(photo_host, image=ph, bg="#ffffff")
            lbl.image = ph   # GC 방지 참조 유지
            lbl.pack(expand=True)
        except Exception as _ie:
            LOG.error(f"[Viewer] 이미지 메모 로드 실패: {_ie}")
            tk.Label(photo_host, text="(이미지 없음)",
                     bg="#ffffff", fg="#999999").pack(expand=True)
        self.canvas.create_window(x, y, window=outer, anchor="nw")
        self._frames.append(outer)

    def _build_table_view(self, parent, memo, bg, fg, bfs):
        """뷰어 표 격자(읽기전용): Frame+Label 셀. 메모 글꼴·셀 배경색 반영."""
        tbl   = memo.get("table") or {}
        rows  = max(1, int(tbl.get("rows", 1)))
        cols  = max(1, int(tbl.get("cols", 1)))
        cells = tbl.get("cells") or [["" for _ in range(cols)] for _ in range(rows)]
        family = memo.get("font_family", "Malgun Gothic")
        cfont  = _safe_font(family, max(8, bfs))
        cell_bg = tbl.get("cell_bg") or {}
        cell_fg = tbl.get("cell_fg") or {}
        frame = tk.Frame(parent, bg="#888888")
        for c in range(cols):
            frame.grid_columnconfigure(c, weight=1, uniform="vtcol")
        for r in range(rows):
            frame.grid_rowconfigure(r, weight=1, uniform="vtrow")
            for c in range(cols):
                val = cells[r][c] if (r < len(cells) and c < len(cells[r])) else ""
                cbg = cell_bg.get(f"{r},{c}", "#ffffff")
                cfg = cell_fg.get(f"{r},{c}", fg)
                tk.Label(frame, text=val, font=cfont, bg=cbg, fg=cfg,
                         anchor="w", justify="left", padx=3, pady=1
                         ).grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
        return frame

    def destroy(self):
        for f in self._frames:
            try:
                f.destroy()
            except Exception:
                pass
        self._frames.clear()
        try:
            self.canvas.destroy()
        except Exception:
            pass
