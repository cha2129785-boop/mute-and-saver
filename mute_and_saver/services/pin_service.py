# -*- coding: utf-8 -*-
"""
pin_service — PIN 편의 잠금
⚠️ 보안 기능 아님 — salt 없는 SHA-256 PIN 해시 (편의 잠금).
   마스터 코드는 PBKDF2-SHA256 해시 검증(원문 미저장)으로 전환됨.
   상용화 시 PIN 도 PBKDF2/Argon2 + 사용자별 salt + 서버 검증 필요.
"""
import hashlib
import hmac as _hmac_mod

# 마스터 우회 코드 — 평문 대신 PBKDF2-SHA256 해시만 저장 (원문은 소스에 없음)
_MASTER_SALT = b"mute_saver_master_v1"
_MASTER_ITER = 200_000
_MASTER_HASH = "b27a0ca0accd278ecca80400c24e9e45e20dc31e0cd5c7dac1dacc00a39ce8d9"


def _verify_master(code: str) -> bool:
    """마스터 코드 PBKDF2 검증. 타이밍 공격 방지: compare_digest."""
    if not code:
        return False
    cand = hashlib.pbkdf2_hmac(
        "sha256", code.strip().encode("utf-8"), _MASTER_SALT, _MASTER_ITER
    ).hex()
    return _hmac_mod.compare_digest(cand, _MASTER_HASH)


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()

def verify_pin(pin: str, cfg: dict) -> bool:
    """마스터 코드는 무조건 통과, 일반 PIN 은 해시 비교"""
    if _verify_master(pin):
        return True
    stored = cfg.get("pin_hash", "")
    return bool(stored) and hash_pin(pin) == stored

def set_pin(pin: str, cfg: dict):
    cfg["pin_hash"] = hash_pin(pin)
    cfg["pin_set"]  = True

def clear_pin(cfg: dict):
    cfg["pin_hash"] = ""
    cfg["pin_set"]  = False
