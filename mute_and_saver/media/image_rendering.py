# -*- coding: utf-8 -*-
"""
image_rendering — PIL 기반 배경/이미지 렌더링
"""
import io
import logging
from pathlib import Path
import random

LOG = logging.getLogger("MuteAndSaver")

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFilter
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from ..constants import MEMO_BG_THEMES, _CANVAS_BG
from ..i18n import t
from ..persistence import get_all_themes

def _safe_font(family: str, size: int, style: str = "normal") -> tuple:
    """
    폰트 튜플 반환.
    Tkinter는 존재하지 않는 폰트를 지정해도 자체 폴백 처리.
    ⚠️ tkfont.families()는 FreeConsole/DPI 변경 후 불완전한 결과를
    반환할 수 있으므로 사전 검사하지 않음.
    """
    return (family, size, style)

def _draw_gradient(canvas: "tk.Canvas", w: int, h: int, theme: dict):
    """그라데이션 — PIL 방식 (Canvas 객체 0개, 이미지 1장)."""
    if not _HAS_PIL:
        # PIL 없으면 기존 Canvas 방식 폴백
        c_start = theme.get("color",     "#0a0a0f")
        c_end   = theme.get("color_end", "#1a1a2e")
        STEPS   = 80
        try:
            r0=int(c_start[1:3],16); g0=int(c_start[3:5],16); b0=int(c_start[5:7],16)
            r1=int(c_end[1:3],16);   g1=int(c_end[3:5],16);   b1=int(c_end[5:7],16)
        except Exception:
            return
        for i in range(STEPS):
            t = i / max(STEPS-1, 1)
            r = int(r0+(r1-r0)*t); g = int(g0+(g1-g0)*t); b = int(b0+(b1-b0)*t)
            y0_ = int(h*i/STEPS); y1_ = int(h*(i+1)/STEPS)
            canvas.create_rectangle(0, y0_, w, y1_,
                                     fill=f"#{r:02x}{g:02x}{b:02x}",
                                     outline="", tags="bg_layer")
        return
    return None   # PIL 방식은 _render_theme_to_pil 에서 처리

def _fit_image(src: "Image.Image", w: int, h: int, mode: str,
               bg_color=(0, 0, 0)) -> "Image.Image":
    """
    이미지를 (w, h) 크기에 맞게 fit_mode에 따라 조정.
    cover:   비율 유지, 캔버스 꽉 채움 (기본값)
    contain: 비율 유지, 캔버스 안에 맞춤 (여백은 bg_color)
    stretch: 비율 무시, 정확히 맞춤
    tile:    이미지 반복 타일
    """
    sw, sh = src.size
    canvas = Image.new("RGB", (w, h), bg_color)

    if mode == "stretch":
        canvas.paste(src.resize((w, h), Image.LANCZOS))

    elif mode == "tile":
        for y in range(0, h, sh):
            for x in range(0, w, sw):
                canvas.paste(src, (x, y))

    elif mode == "contain":
        ratio  = min(w / sw, h / sh)
        nw, nh = int(sw * ratio), int(sh * ratio)
        resized = src.resize((nw, nh), Image.LANCZOS)
        ox, oy  = (w - nw) // 2, (h - nh) // 2
        canvas.paste(resized, (ox, oy))

    else:   # cover (기본값)
        ratio  = max(w / sw, h / sh)
        nw, nh = max(w, int(sw * ratio)), max(h, int(sh * ratio))
        resized = src.resize((nw, nh), Image.LANCZOS)
        ox, oy  = (nw - w) // 2, (nh - h) // 2
        cropped = resized.crop((ox, oy, ox + w, oy + h))
        canvas.paste(cropped, (0, 0))

    return canvas

def _render_theme_to_pil(w: int, h: int, theme: dict) -> "Image.Image":
    """
    테마를 PIL Image로 렌더링.
    Canvas 직접 그리기 방식 완전 대체.
    반환된 이미지를 canvas._origin_theme_img에 저장 → 블러 소스로 사용.

    PIL 마이그레이션 팁:
      - 색상: 모두 #HEX → PIL 완전 호환
      - create_line → draw.line([(x1,y1),(x2,y2)], fill, width)
      - create_oval → draw.ellipse([x0,y0,x1,y1], fill)
      - create_rectangle → draw.rectangle([x0,y0,x1,y1], fill)
      - 코르크 3000개: Immediate Mode → 이미지 1장 = 버벅임 0
    """
    bg_color = theme.get("color", "#0d0d0d")
    img  = Image.new("RGB", (w, h), bg_color)
    draw = ImageDraw.Draw(img)
    bg_type = theme.get("bg_type", "solid")

    if bg_type == "image":
        img_path = theme.get("image_path", "")
        fit_mode = theme.get("fit_mode", "cover")
        LOG.info(f"[Theme_Apply] 🛑 이미지 테마 렌더링 시작 — 경로: {img_path}")

        # 1. 파일 존재 검증
        if not img_path:
            LOG.error("[Theme_Apply] 🚨 image_path가 비어있음 → paper 폴백")
            return Image.new("RGB", (w, h), MEMO_BG_THEMES["paper"].get("color", "#fafaf7"))
        if not Path(img_path).exists():
            LOG.error(f"[Theme_Apply] 🚨 파일 없음: {img_path} → paper 폴백")
            return Image.new("RGB", (w, h), MEMO_BG_THEMES["paper"].get("color", "#fafaf7"))

        try:
            LOG.info(f"[Theme_Apply] 2. Image.open 시도 중...")
            # ⚠️ 한글/공백 경로 네이티브 크래시 방어: 파일을 바이트로 읽어
            #    BytesIO 경유로 디코딩 → PIL이 경로를 직접 열지 않음.
            with open(img_path, "rb") as _img_f:
                _img_bytes = _img_f.read()
            with Image.open(io.BytesIO(_img_bytes)) as raw_img:
                raw_img.load()
                LOG.info(f"[Theme_Apply] 2a. load 완료 — mode={raw_img.mode}, size={raw_img.size}")
                if raw_img.mode == "P":
                    src_img = raw_img.convert("RGBA")
                else:
                    src_img = raw_img.copy()
            # with 블록 종료 → 파일 핸들 즉시 해제
            if src_img.mode in ("RGBA", "LA"):
                bg_white = Image.new("RGB", src_img.size, (255, 255, 255))
                bg_white.paste(src_img, mask=src_img.split()[-1])
                src_img = bg_white
            elif src_img.mode != "RGB":
                src_img = src_img.convert("RGB")
            LOG.info(f"[Theme_Apply] 2b. ✅ RGB 변환 완료 — size={src_img.size}")

            # 회전 (90도 단위 무손실) — fit 이전에 적용. 90/270은 W↔H 스왑됨.
            _rot = int(theme.get("rotate", 0)) % 360
            if _rot in (90, 180, 270):
                src_img = src_img.rotate(-_rot, expand=True)  # 음수=시계방향, expand로 캔버스 확장
                LOG.info(f"[Theme_Apply] 2c. 회전 {_rot}° 적용 — size={src_img.size}")

            # 여백 색상: 테마 color 키 → 폴백 "#1a1a2e"
            _bg_hex = theme.get("color", "#1a1a2e").lstrip('#')
            _bg_rgb = tuple(int(_bg_hex[i:i+2], 16) for i in (0, 2, 4))
            img = _fit_image(src_img, w, h, fit_mode, bg_color=_bg_rgb)
            LOG.info(f"[Theme_Apply] 3. ✅ _fit_image({fit_mode}) 완료 — 결과 크기: {img.size}")

            LOG.info("[Theme_Apply] 🏁 이미지 테마 렌더링 완전 성공")
        except Exception as e:
            LOG.error(f"[Theme_Apply] 🚨 이미지 렌더링 중 크래시 감지: {e}")
            img = Image.new("RGB", (w, h), MEMO_BG_THEMES["paper"].get("color", "#fafaf7"))
        return img

    elif bg_type == "gradient":
        c_start = theme.get("color",     "#0a0a0f")
        c_end   = theme.get("color_end", "#1a1a2e")
        STEPS   = 80
        try:
            r0=int(c_start[1:3],16); g0=int(c_start[3:5],16); b0=int(c_start[5:7],16)
            r1=int(c_end[1:3],16);   g1=int(c_end[3:5],16);   b1=int(c_end[5:7],16)
        except Exception:
            return img
        for i in range(STEPS):
            t  = i / max(STEPS-1, 1)
            r  = int(r0+(r1-r0)*t); g = int(g0+(g1-g0)*t); b = int(b0+(b1-b0)*t)
            y0 = int(h*i/STEPS);   y1 = int(h*(i+1)/STEPS)
            draw.rectangle([0, y0, w, y1], fill=(r, g, b))

    elif bg_type == "pattern":
        tk_key = next(
            (k for k, v in MEMO_BG_THEMES.items() if v is theme), ""
        )
        lc  = theme.get("line_color", "#888888")
        gap = theme.get("grid_gap",   24)

        if "cork" in tk_key:
            dc  = theme.get("dot_color", "#9e7548")
            rng = random.Random(42)
            dot_count = min((w*h)//150, 3000)
            for _ in range(dot_count):
                x, y = rng.randint(0, w), rng.randint(0, h)
                r    = rng.randint(1, 3)
                draw.ellipse([x-r, y-r, x+r, y+r], fill=dc)

        elif "neon_city" in tk_key:
            acc = theme.get("accent", "#5b3dee")
            for x in range(0, w, gap):
                draw.line([(x, 0), (x, h)], fill=lc, width=1)
            for y in range(0, h, gap):
                draw.line([(0, y), (w, y)], fill=lc, width=1)
            count = 0
            for x in range(0, w, gap):
                for y in range(0, h, gap):
                    if count >= 200: break
                    draw.ellipse([x-2, y-2, x+2, y+2], fill=acc)
                    count += 1

        elif "paper" in tk_key:
            for y in range(gap, h, gap):
                draw.line([(0, y), (w, y)], fill=lc, width=1)
            draw.line([(48, 0), (48, h)], fill="#f0c0c0", width=1)

        elif "grid" in tk_key:
            for x in range(0, w, gap):
                draw.line([(x, 0), (x, h)], fill=lc, width=1)
            for y in range(0, h, gap):
                draw.line([(0, y), (w, y)], fill=lc, width=1)

    return img

def _render_canvas_bg(canvas: "tk.Canvas", w: int, h: int, theme: dict):
    """
    Canvas 배경 렌더링 — 완전무결 Fallback 장갑차.
    이미지 로드/리사이즈 실패 시:
      1. _current_bg_photo = None 으로 이미지 참조 정리
      2. canvas를 Paper 단색(#fafaf7)으로 강제 복구
      3. 후속 Tkinter 렌더러가 None 참조로 터지는 현상 원천 차단
    """
    canvas.delete("bg_layer")
    canvas.configure(bg=theme.get("color", "#fafaf7"))

    if _HAS_PIL:
        LOG.info(f"[Theme_Shield] 🛑 PIL 렌더 시작 — bg_type={theme.get('bg_type','solid')}")
        try:
            img   = _render_theme_to_pil(w, h, theme)
            photo = ImageTk.PhotoImage(img)
            canvas.create_image(0, 0, anchor="nw", image=photo, tags="bg_layer")
            # GC 방어: canvas 속성으로 강하게 참조 유지
            canvas._bg_photo         = photo   # GC 방지
            canvas._origin_theme_img = img     # 블러용 원본 보관
            LOG.info("[Theme_Shield] ✅ PhotoImage GC 방어 완료 — canvas._bg_photo 고정")
        except Exception as e:
            # [초치명적 핵심 방어선] 이미지 연산 폭발 → Paper 단색으로 강제 복구
            LOG.error(f"[Theme_Shield] 🚨 테마 렌더링 폭발 → Paper 폴백으로 복구: {e}")
            try:
                # 1. 이미지 참조 정리 (메모리 크래시 방지)
                canvas._bg_photo         = None
                canvas._origin_theme_img = None
                # 2. Canvas를 Paper 단색으로 강제 복구
                fallback_color = MEMO_BG_THEMES["paper"].get("color", "#fafaf7")
                canvas.configure(bg=fallback_color)
                canvas.delete("bg_layer")
                LOG.info(
                    f"[Theme_Shield] ✅ Paper 폴백 복구 완료 (color={fallback_color}) "
                    "— 후속 렌더러 크래시 차단"
                )
            except Exception as fallback_err:
                LOG.critical(
                    f"[Theme_Shield] 🚨 폴백 복구마저 실패 (UI 위젯 파괴 상태): {fallback_err}"
                )
    else:
        # PIL 없을 때 Canvas 직접 그리기 폴백
        bg_type = theme.get("bg_type", "solid")
        if bg_type == "gradient":
            _draw_gradient(canvas, w, h, theme)
        elif bg_type == "pattern":
            all_t  = get_all_themes()
            tk_key = next(
                (k for k, v in all_t.items() if v is theme), ""
            )
            if "cork"        in tk_key: _draw_cork(canvas, w, h, theme)
            elif "neon_city" in tk_key: _draw_neon_grid(canvas, w, h, theme)
            elif "paper"     in tk_key: _draw_lined_paper(canvas, w, h, theme)
            elif "grid"      in tk_key: _draw_grid(canvas, w, h, theme)

    try:
        canvas.tag_lower("bg_layer")
    except Exception:
        pass



# ── 패턴 그리기 헬퍼 ──
def _draw_neon_grid(canvas: "tk.Canvas", w: int, h: int, theme: dict):
    """네온 그리드 — PIL 없으면 Canvas 폴백."""
    if _HAS_PIL:
        return None
    lc  = theme.get("line_color", "#1a1a3a")
    acc = theme.get("accent",     "#5b3dee")
    gap = theme.get("grid_gap",   32)
    for x in range(0, w, gap):
        canvas.create_line(x, 0, x, h, fill=lc, width=1, tags="bg_layer")
    for y in range(0, h, gap):
        canvas.create_line(0, y, w, y, fill=lc, width=1, tags="bg_layer")
    count = 0
    for x in range(0, w, gap):
        for y in range(0, h, gap):
            if count >= 200: break
            canvas.create_oval(x-1, y-1, x+1, y+1,
                               fill=acc, outline="", tags="bg_layer")
            count += 1

def _draw_lined_paper(canvas: "tk.Canvas", w: int, h: int, theme: dict):
    """줄노트 — PIL 없으면 Canvas 폴백."""
    if _HAS_PIL:
        return None
    lc  = theme.get("line_color", "#e8e4da")
    gap = theme.get("grid_gap",   28)
    for y in range(gap, h, gap):
        canvas.create_line(0, y, w, y, fill=lc, width=1, tags="bg_layer")
    canvas.create_line(48, 0, 48, h, fill="#f0c0c0", width=1, tags="bg_layer")

def _draw_cork(canvas: "tk.Canvas", w: int, h: int, theme: dict):
    """코르크 — PIL 없으면 Canvas 폴백."""
    if _HAS_PIL:
        return None
    dc  = theme["dot_color"]
    rng = random.Random(42)
    dot_count = min((w*h)//150, 3000)
    for _ in range(dot_count):
        x, y = rng.randint(0, w), rng.randint(0, h)
        r    = rng.randint(1, 3)
        canvas.create_oval(x-r, y-r, x+r, y+r,
                           fill=dc, outline="", tags="bg_layer")

def _draw_grid(canvas: "tk.Canvas", w: int, h: int, theme: dict):
    """모눈종이 — PIL 없으면 Canvas 폴백."""
    if _HAS_PIL:
        return None
    lc  = theme["line_color"]
    gap = theme["grid_gap"]
    for x in range(0, w, gap):
        canvas.create_line(x, 0, x, h, fill=lc, width=1, tags="bg_layer")
    for y in range(0, h, gap):
        canvas.create_line(0, y, w, y, fill=lc, width=1, tags="bg_layer")

