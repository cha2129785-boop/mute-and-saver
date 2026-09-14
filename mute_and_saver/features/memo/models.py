# -*- coding: utf-8 -*-
"""
models — 메모 데이터 헬퍼 (텍스트색/가시성/스케줄/템플릿)
"""
import time
import uuid
import datetime

from ...constants import MEMO_COLORS, MEMO_TEMPLATES, TIER_CONFIG, TEXT_COLORS

def new_memo_template() -> dict:
    """
    FullscreenMemoEditor + DashboardEditor 양쪽에서 동일한 규격의 메모 생성.
    title_font_size / body_font_size 분리 포함 (최신 스키마 기준).
    """
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    mid = uuid.uuid4().hex[:12]
    return {
        "id":              mid,
        "kind":            "text",   # "text" | "table" (없으면 text — 하위호환)
        "title":           "새 메모",
        "body":            "",
        "color_key":       "amber",   # 시트린
        "font_family":     "Malgun Gothic",
        "title_font_size": 32,
        "body_font_size":  24,
        "title_text_color": "black",   # TEXT_COLORS 키
        "body_text_color":  "black",
        "title_align":      "l",       # 왼쪽
        "body_align":       "l",
        "x": 60, "y": 60,
        "width": 220, "height": 160,
        "z_order":     0,
        "pinned":      False,
        "collapsed":   False,
        "created_at":  now,
        "updated_at":  now,
    }

TABLE_MAX_ROWS = 20
TABLE_MAX_COLS = 10

def new_table(rows: int, cols: int) -> dict:
    """표 데이터 생성 — rows×cols 빈 셀. 상한 20×10 클램프."""
    rows = max(1, min(TABLE_MAX_ROWS, int(rows)))
    cols = max(1, min(TABLE_MAX_COLS, int(cols)))
    return {
        "rows": rows, "cols": cols,
        "cells": [["" for _ in range(cols)] for _ in range(rows)],
        "header_row": False,
    }

def build_calendar_table(year: int, month: int, weekday_labels) -> dict:
    """연·월 → 표 데이터(7열: 요일 헤더 1행 + 주별 날짜). 일요일 시작.
    weekday_labels: 길이 7 리스트(일~토)."""
    import calendar as _cal
    cal = _cal.Calendar(firstweekday=6)   # 6=일요일 시작
    weeks = cal.monthdayscalendar(int(year), int(month))  # 0=해당월 외
    labels = list(weekday_labels)[:7]
    while len(labels) < 7:
        labels.append("")
    cells = [labels[:]]
    for wk in weeks:
        cells.append([str(d) if d else "" for d in wk])
    return {"rows": len(cells), "cols": 7, "cells": cells, "header_row": True}

def _memo_text_color(color_key: str) -> str:
    """배경 밝기(0.299R+0.587G+0.114B) → 전경색 자동 반환. 커스텀 hex 지원."""
    if isinstance(color_key, str) and color_key.startswith("#"):
        bg = color_key
    else:
        bg = MEMO_COLORS.get(color_key, MEMO_COLORS["yellow"])[0]
    try:
        r, g, b = int(bg[1:3],16), int(bg[3:5],16), int(bg[5:7],16)
    except Exception:
        r, g, b = 255, 249, 196
    return "#222222" if (0.299*r + 0.587*g + 0.114*b) > 128 else "#eeeeee"

def resolve_text_color(val, default: str) -> str:
    """글자색 해석: 프리셋 키(TEXT_COLORS) → hex, '#'로 시작하면 커스텀 hex 그대로,
    아니면 default. (제목/본문 글자색 커스텀 지원 공용)."""
    if isinstance(val, str):
        if val in TEXT_COLORS:
            return TEXT_COLORS[val]
        if val.startswith("#"):
            return val
    return default

def _get_visible_memos(memos: list, is_premium: bool) -> list:
    """
    render 단 Freemium 필터: z_order 상위 N개만 반환.
    save_memos()는 항상 전체 저장 — 데이터 유실 없음.
    스케줄 필터는 MemoBoardViewer.render()에서 별도 적용.
    FSEditor는 이 함수를 사용하지 않음 — 전체 메모 항상 표시.
    """
    limit = TIER_CONFIG["premium" if is_premium else "free"]["max_memos"]
    return sorted(memos, key=lambda m: m.get("z_order", 0), reverse=True)[:limit]

def _is_scheduled_now(memo: dict) -> bool:
    """
    메모의 스케줄 설정 기준으로 현재 시각 표시 여부 반환.
    schedule_enabled=False(기본) → 항상 True (스케줄 무관).
    FSEditor: 이 함수 사용하지 않음 → 스케줄 비활성 메모도 편집 가능.
    MemoBoardViewer: 이 함수로 필터링 → 스케줄 외 시간엔 미표시.
    """
    if not memo.get("schedule_enabled", False):
        return True   # 스케줄 미사용 → 항상 표시
    import datetime as _dt
    now = _dt.datetime.now()
    # 요일 체크 (0=월 ~ 6=일)
    show_days = memo.get("show_days", list(range(7)))
    if now.weekday() not in show_days:
        return False
    # 시간대 체크
    try:
        t_from  = _dt.datetime.strptime(memo.get("show_from",  "00:00"), "%H:%M").time()
        t_until = _dt.datetime.strptime(memo.get("show_until", "23:59"), "%H:%M").time()
        return t_from <= now.time() <= t_until
    except ValueError:
        return True   # 파싱 실패 → 안전하게 표시

