# -*- coding: utf-8 -*-
"""
coordinates — 메모 절대↔상대 좌표 변환
"""

def _abs_to_rel(px: int, py: int, pw: int, ph: int,
                region_w: int, region_h: int) -> dict:
    """
    절대 픽셀 → 상대 비율 딕셔너리.
    기준: 에디터 캔버스 = 메모 배치 영역(region_w × region_h).
    분할 모드에서 region = 메모 영역 크기 (전체 화면이 아님).
    rel_x 범위 보장: min(1.0) 상한으로 캔버스 밖 저장 방지.
    """
    return {
        "rel_x": round(min(1.0, px / max(region_w, 1)), 4),
        "rel_y": round(min(1.0, py / max(region_h, 1)), 4),
        "rel_w": round(min(1.0, pw / max(region_w, 1)), 4),
        "rel_h": round(min(1.0, ph / max(region_h, 1)), 4),
    }

