# -*- coding: utf-8 -*-
"""
config_repository — 설정 로드/저장 (예외 경계 분리 + 백업)
"""
import json
import shutil
import logging

from .atomic_file import _atomic_save
from .migrations.config_migrations import _migrate
from ..constants import CONFIG_PATH, DEFAULT_CONFIG

LOG = logging.getLogger("MuteAndSaver")

def load_config() -> dict:
    if CONFIG_PATH.exists():
        # 1단계: 읽기 + 파싱 (실패 → 기본값 정당)
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            LOG.error(f"설정 파일 읽기 실패, 기본값 사용: {e}")
            cfg = dict(DEFAULT_CONFIG)
            try:
                _atomic_save(CONFIG_PATH, cfg)
            except Exception:
                pass
            return cfg

        # 2단계: 마이그레이션 (변환만 — 실패해도 읽은 설정 유지)
        try:
            cfg = _migrate(cfg)
        except Exception as e:
            LOG.error(f"설정 마이그레이션 실패 (기존 설정으로 계속): {e}")
            return cfg

        # 3단계: 마이그레이션 결과 저장 (실패해도 메모리 설정 유효)
        try:
            _atomic_save(CONFIG_PATH, cfg)
        except Exception as e:
            LOG.warning(f"마이그레이션 저장 실패 (메모리 설정으로 계속): {e}")

        LOG.info("설정 로드 완료")
        return cfg

    # 파일 없음 → 백업에서 복원 시도
    bak_path = CONFIG_PATH.with_suffix(".json.bak")
    if bak_path.exists():
        try:
            import shutil
            shutil.copy2(bak_path, CONFIG_PATH)
            LOG.warning("config.json 소실 — 백업에서 복원")
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return _migrate(cfg)
        except Exception as e:
            LOG.error(f"백업 복원 실패: {e}")

    # 백업도 없음 → 기본값 생성
    cfg = dict(DEFAULT_CONFIG)
    try:
        _atomic_save(CONFIG_PATH, cfg)
        LOG.info("기본 설정 생성")
    except Exception as e:
        LOG.warning(f"기본 설정 저장 실패 (메모리 설정으로 계속): {e}")
    return cfg

def save_config(cfg: dict):
    try:
        _atomic_save(CONFIG_PATH, cfg)
        # 백업 파일 갱신 (config 소실 방어)
        try:
            import shutil
            shutil.copy2(CONFIG_PATH, CONFIG_PATH.with_suffix(".json.bak"))
        except Exception:
            pass
    except Exception as e:
        LOG.error(f"설정 저장 실패 (메모리 설정 유지): {e}")
