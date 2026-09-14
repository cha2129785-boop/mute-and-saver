# -*- coding: utf-8 -*-
"""
config_migrations — 설정 스키마 마이그레이션 (v1~v10)
"""
import logging

from ..atomic_file import _atomic_save
from ...constants import CONFIG_PATH, DEFAULT_CONFIG
from ...features.memo.coordinates import _abs_to_rel
from ..memo_repository import load_memos, save_memos

LOG = logging.getLogger("MuteAndSaver")

def _migrate(cfg: dict) -> dict:
    ver = cfg.get("schema_version", 0)
    if ver < 1:
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        cfg["schema_version"] = 1
        LOG.info(f"설정 마이그레이션: v{ver} → v1")
    if ver < 2:
        v2_keys = {
            "screensaver_mode":    "media",
            "split_ratio":         0.65,
            "split_direction":     "h",
            "monitor_assignments": [],
            "memo_editor_canvas_w": 600,
            "memo_editor_canvas_h": 360,
        }
        for k, v in v2_keys.items():
            cfg.setdefault(k, v)
        cfg["schema_version"] = 2
        LOG.info("설정 마이그레이션: v1 → v2 (메모 보드 키 추가)")
    if ver < 3:
        cfg.setdefault("pin_message", "")
        cfg["schema_version"] = 3
        LOG.info("설정 마이그레이션: v2 → v3 (pin_message 추가)")
    if ver < 4:
        # ── 전역 설정 신규 키 ────────────────────────────────────
        cfg.setdefault("memo_bg_theme", "paper")
        # ── 기존 메모 데이터 신규 필드 안전망 ────────────────────
        try:
            memos   = load_memos()
            changed = False
            for m in memos:
                if "collapsed"   not in m:
                    m["collapsed"]   = False;          changed = True
                if "font_family" not in m:
                    m["font_family"] = "Malgun Gothic"; changed = True
            if changed:
                save_memos(memos)
        except Exception as e:
            LOG.error(f"v4 메모 마이그레이션 오류: {e}")
        cfg["schema_version"] = 4
        _atomic_save(CONFIG_PATH, cfg)
        LOG.info("설정 마이그레이션: v3 → v4 (메모 글꼴·접기·배경 테마 추가)")
    if ver < 5:
        # ── 제목/본문 글자 크기 분리 ─────────────────────────────
        try:
            memos   = load_memos()
            changed = False
            for m in memos:
                old_fs = m.pop("font_size", 13)     # 기존 단일 키 제거, 본문으로 승계
                if "title_font_size" not in m:
                    m["title_font_size"] = 11;       changed = True
                if "body_font_size"  not in m:
                    m["body_font_size"]  = old_fs;   changed = True
            if changed:
                save_memos(memos)
        except Exception as e:
            LOG.error(f"v5 메모 마이그레이션 오류: {e}")
        # 무한 반복 방지: 버전 업 후 반드시 파일 저장
        cfg["schema_version"] = 5
        _atomic_save(CONFIG_PATH, cfg)
        LOG.info("설정 마이그레이션: v4 → v5 (제목/본문 글자 크기 분리 완료)")
    if ver < 6:
        cfg.setdefault("pin_message_font_size", 12)   # 기본 12pt
        cfg["schema_version"] = 6
        _atomic_save(CONFIG_PATH, cfg)   # 무한 반복 방지
        LOG.info("설정 마이그레이션: v5 → v6 (PIN 메시지 글자 크기 추가)")
    if ver < 7:
        # ── 기존 메모의 rel_* 상대 좌표 자동 계산 (하위 호환성) ──
        # 절대 좌표(x/y/width/height)는 유지, rel_* 만 추가
        # 롤백 시 이전 버전이 절대값으로 그대로 작동 가능
        try:
            memos   = load_memos()
            changed = False
            cw      = cfg.get("memo_editor_canvas_w", 600)
            ch      = cfg.get("memo_editor_canvas_h", 360)
            for m in memos:
                if "rel_x" not in m:
                    m.update(_abs_to_rel(
                        m.get("x", 60), m.get("y", 60),
                        m.get("width", 220), m.get("height", 160),
                        cw, ch
                    ))
                    changed = True
            if changed:
                save_memos(memos)
        except Exception as e:
            LOG.error(f"v7 메모 마이그레이션 오류: {e}")
        cfg["schema_version"] = 7
        _atomic_save(CONFIG_PATH, cfg)   # 무한 반복 방지
        LOG.info("설정 마이그레이션: v6 → v7 (메모 상대 좌표 rel_* 추가)")
    if ver < 8:
        # ── rel_* 기준을 메모 영역으로 재정규화 + 메타데이터 추가 ──
        # 위험 시나리오: 저장 당시 split_ratio와 현재 ratio 불일치
        # → _saved_split_ratio 메타로 역산 복구
        try:
            memos   = load_memos()
            changed = False
            cur_cw  = cfg.get("memo_editor_canvas_w", 600)
            cur_ch  = cfg.get("memo_editor_canvas_h", 360)
            ratio   = cfg.get("split_ratio", 0.65)

            for m in memos:
                if "rel_x" not in m:
                    continue
                # 저장 당시 기준값 추출 (_saved_* 메타 우선, 없으면 현재값)
                saved_cw    = m.pop("_saved_canvas_w",    cur_cw)
                saved_ch    = m.pop("_saved_canvas_h",    cur_ch)
                saved_ratio = m.pop("_saved_split_ratio", ratio)   # noqa — 이후 메타 재기록
                # 절대 픽셀 역산 (저장 당시 캔버스 기준)
                abs_x = m["rel_x"] * saved_cw
                abs_y = m["rel_y"] * saved_ch
                abs_w = m["rel_w"] * saved_cw
                abs_h = m["rel_h"] * saved_ch
                # 현재 캔버스(메모 영역) 기준으로 재정규화
                m.update(_abs_to_rel(abs_x, abs_y, abs_w, abs_h, cur_cw, cur_ch))
                # 메타데이터 기록 (이후 ratio 변경 시 역산 가능)
                m["_saved_canvas_w"]    = cur_cw
                m["_saved_canvas_h"]    = cur_ch
                m["_saved_split_ratio"] = ratio
                changed = True
            if changed:
                save_memos(memos)
        except Exception as e:
            LOG.error(f"v8 메모 마이그레이션 오류: {e}")
        cfg["schema_version"] = 8
        _atomic_save(CONFIG_PATH, cfg)   # 무한 반복 방지
        LOG.info("설정 마이그레이션: v7 → v8 (메모 좌표 기준 메모 영역 통일)")
    if ver < 9:
        # memo_opacity 의미 반전: 불투명도(1.0=불투명) → 투명도(0.0=불투명)
        old_val = cfg.get("memo_opacity", 1.0)
        cfg["memo_opacity"] = round(1.0 - old_val, 2)
        cfg["schema_version"] = 9
        _atomic_save(CONFIG_PATH, cfg)
        LOG.info(f"설정 마이그레이션: v8 → v9 (memo_opacity 반전: {old_val} → {cfg['memo_opacity']})")
    if ver < 10:
        cfg.setdefault("tab_order", ["setting", "media", "hotkey", "memo", "license", "lang"])
        cfg["schema_version"] = 10
        _atomic_save(CONFIG_PATH, cfg)
        LOG.info("설정 마이그레이션: v9 → v10 (tab_order 추가)")
    return cfg
