# -*- coding: utf-8 -*-
"""
license_service — 제품 활성화 + 관리자 인증
⚠️ 로컬 검증은 Patch 우회 가능 — 편의 구분 수단. 강한 통제는 서버 필요.
"""
import hashlib
import hmac as _hmac_mod

CURRENT_VERSION   = "8.84"
SECRET_KEY        = "SecMon_Activation_Key_V1_CH.A.831221"
_ADMIN_SALT       = b"secmon_admin_salt_v1"
_ADMIN_ITER       = 200_000

# 관리자 코드 PBKDF2-SHA256 해시 (원문은 소스에 없음 — 검증 시 입력값을 동일 파라미터로 해싱 후 비교)
ADMIN_HASH = "925ac5fbdecc7a912471c9c7e49efd9edad48bb283b980041040fb62164c8d76"


def _verify_admin(code: str) -> bool:
    """
    입력값을 동일 파라미터로 해싱 후 ADMIN_HASH와 비교.
    타이밍 공격 방지: hmac.compare_digest 사용.
    """
    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        code.strip().encode(),
        _ADMIN_SALT,
        _ADMIN_ITER
    ).hex()
    return _hmac_mod.compare_digest(candidate, ADMIN_HASH)


def _get_hardware_id() -> str:
    """
    MAC 주소 + platform → 하드웨어 ID 생성.
    가상화/VPN 환경에서 MAC 변경 가능 — 라이선스 로컬 검증 한계 인정.
    """
    import platform
    try:
        import uuid as _uuid
        mac = hex(_uuid.getnode())[2:].upper().zfill(12)
        plat = platform.system()
        raw = f"{mac}:{plat}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32].upper()
    except Exception:
        return "UNKNOWN-HW-ID"


def _generate_activation_code(hw_id: str) -> str:
    """hw_id → HMAC-SHA256 → 4×4 활성화 코드."""
    sig = _hmac_mod.new(
        SECRET_KEY.encode(),
        hw_id.encode(),
        hashlib.sha256
    ).hexdigest().upper()
    return f"{sig[:4]}-{sig[4:8]}-{sig[8:12]}-{sig[12:16]}"


def _verify_license(cfg: dict) -> bool:
    """
    1차: 온라인 API (추후 서버 개설 시 활성화 — 현재 None 반환으로 로컬 폴백)
    2차: 로컬 HMAC 검증 (오프라인 환경 보호)
    로컬 검증은 Patch 우회에 취약 — 편의성 수단임을 명시.
    """
    code = cfg.get("activation_code", "").strip()
    if not code:
        return False
    hw_id = _get_hardware_id()
    expected = _generate_activation_code(hw_id)
    return _hmac_mod.compare_digest(code.upper(), expected)
