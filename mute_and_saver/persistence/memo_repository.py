# -*- coding: utf-8 -*-
"""
memo_repository — 메모 로드/저장/생성
"""
import json
import time
import uuid
import logging

from .atomic_file import _atomic_save
from ..constants import MEMO_PATH
from ..features.memo.coordinates import _abs_to_rel
from ..platform.windows.monitor import _get_monitors_info  # noqa
# ⚠️ 위 두 import는 패키지 __init__가 아닌 모듈 직접 경로 → 순환 import 회피

LOG = logging.getLogger("MuteAndSaver")

def load_memos() -> list:
    """
    memo.json → 메모 목록 반환 (없으면 빈 리스트).
    로드 직후 _migrate_legacy_memos()로 구버전 메모 rel_* 변환.
    """
    if MEMO_PATH.exists():
        try:
            with open(MEMO_PATH, "r", encoding="utf-8") as f:
                memos = json.load(f).get("memos", [])
            # ── 레거시 메모 일괄 변환 (rel_* 없는 구버전) ─────────
            # render()는 rel_* 단일 좌표계만 읽도록 확정
            # 이 변환은 rel_* 없는 메모가 존재할 때만 실행 (no-op 최적화)
            memos = _migrate_legacy_memos(memos)
            return memos
        except Exception as e:
            LOG.error(f"메모 로드 실패: {e}")
    return []


def _migrate_legacy_memos(memos: list) -> list:
    """
    rel_* 없는 구버전 메모를 실제 모니터 해상도 기준 rel_*로 일괄 변환.
    변환 후 즉시 save_memos() → 이후 호출에서는 no-op.
    render()의 폴백 분기를 원천 제거하기 위한 선행 처리.
    """
    needs = any("rel_x" not in m for m in memos)
    if not needs:
        return memos   # 전부 rel_* 존재 → 즉시 반환

    try:
        monitors = _get_monitors_info()
        primary  = next((m for m in monitors if m[4]), monitors[0])
        _, _, mw, mh, _ = primary
    except Exception:
        mw, mh = 1920, 1080   # 폴백 기준

    changed = False
    for m in memos:
        if "rel_x" in m:
            # rel_* 이미 존재 → 범위 검증 (화면 밖 클램핑)
            # FSEditor 저장 버그나 수동 편집으로 rel_* > 1.0 발생 시 복구
            clamped = False
            for key in ("rel_x", "rel_y", "rel_w", "rel_h"):
                val = m.get(key, 0.0)
                fixed = max(0.0, min(1.0, float(val)))
                if abs(fixed - val) > 0.0001:
                    m[key] = fixed
                    clamped = True
            if clamped:
                changed = True
                LOG.warning(f"[LegacyMigrate] {m.get('id','?')} rel_* 범위 초과 → 클램핑")
            continue
        ax = max(0, min(m.get("x", 60),      mw - m.get("width",  220)))
        ay = max(0, min(m.get("y", 60),      mh - m.get("height", 160)))
        aw = min(m.get("width",  220), mw)
        ah = min(m.get("height", 160), mh)
        m.update(_abs_to_rel(ax, ay, aw, ah, mw, mh))
        m["_saved_canvas_w"]    = mw
        m["_saved_canvas_h"]    = mh
        m["_saved_split_ratio"] = 0.65
        changed = True
        LOG.info(f"[LegacyMigrate] {m.get('id','?')} → rel_* 변환")

    if changed:
        save_memos(memos)
        LOG.info(f"[LegacyMigrate] 레거시 메모 마이그레이션 완료")
    return memos

def save_memos(memos: list):
    """
    memo.json 원자적 저장.
    ⚠️ tier 체크 없음 — 데이터 100% 보존.
    Freemium 제한은 render 단에서만 처리.
    """
    _atomic_save(MEMO_PATH, {"schema_version": 2, "memos": memos})

def new_memo(x: int = 60, y: int = 60) -> dict:
    """기본값 메모 딕셔너리 생성 (uuid 기반 ID)."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "id":          uuid.uuid4().hex[:12],
        "title":       "새 메모",
        "body":        "",
        "color_key":   "yellow",
        "font_size":   13,
        "font_family": "Malgun Gothic",   # v4 추가
        "x": x, "y": y,
        "width": 220, "height": 160,
        "z_order":     0,
        "pinned":      False,
        "collapsed":   False,             # v4 추가 — 제목만 보기
        "created_at":  now,
        "updated_at":  now,
    }
