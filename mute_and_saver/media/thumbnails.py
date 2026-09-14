# -*- coding: utf-8 -*-
"""
thumbnails — 미디어 썸네일 생성 (이미지 + 동영상)
"""
import logging
from pathlib import Path

LOG = logging.getLogger("MuteAndSaver")

try:
    from PIL import Image
    _HAS_PIL = True
    # ⚠️ 앱 시작 시 PIL 플러그인 전부 사전 로드 + 저장 경로 워밍업.
    #  안 하면 generate_thumb의 Image.open/save가 플러그인(특히 JPEG 인코더)을 그때 지연 import →
    #  그 시점(콜백 내부) 파이썬 GC가 잔존 comtypes(pycaw) 프록시를 Release하다 access violation(네이티브 종료).
    #  시작 시(깨끗한 스택, COM 프록시 없음) 강제 로드해 런타임 지연 import 자체를 제거.
    try:
        from io import BytesIO
        Image.init()                                   # 디코더/플러그인 등록
        Image.new("RGB", (1, 1)).save(BytesIO(), "JPEG")  # 저장 경로(preinit+JPEG 인코더) 강제 로드
    except Exception as _e:
        LOG.warning(f"[Thumb] PIL 사전 로드 실패(런타임 지연 import 위험): {_e}")
except ImportError:
    _HAS_PIL = False

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

from ..constants import THUMBS_DIR, THUMB_SIZE, IMG_EXTS, VIDEO_EXTS

def generate_thumb(src_path: str):
    """썸네일 생성 래퍼 — 생성 구간 동안 순환 GC 일시중지(근본 크래시 차단).
    ⚠️ 확진(fault.log): PIL 플러그인 import/연산 중 파이썬 GC가 잔존 comtypes(pycaw)
      프록시를 Release → access violation(네이티브 종료). 생성 구간만 gc.disable 하면
      그 구간에 comtypes __del__→Release가 발생하지 않음. 종료 후 원상복원.
    """
    import gc as _gc
    _was = _gc.isenabled()
    _gc.disable()
    try:
        return _generate_thumb_impl(src_path)
    finally:
        if _was:
            _gc.enable()


def _generate_thumb_impl(src_path: str):
    """
    동영상/이미지 → 썸네일 JPG 캐시. 경로 반환 또는 None.
    THUMB_SIZE 변경 시 기존 캐시와 크기 불일치 → 자동 재생성.
    PermissionError 방어: 파일 사용 중이면 기존 썸네일 재사용.
    """
    src = Path(src_path)
    if not src.exists():
        return None
    thumb_path = THUMBS_DIR / f"{src.stem}.jpg"
    if thumb_path.exists():
        # 크기 불일치 감지 → 재생성 시도
        if _HAS_PIL:
            try:
                with Image.open(str(thumb_path)) as existing:
                    size_ok = (existing.size == THUMB_SIZE)
                if not size_ok:
                    try:
                        thumb_path.unlink(missing_ok=True)
                        LOG.info(f"[Thumb] 크기 불일치 재생성: {src.name}")
                    except PermissionError:
                        # 다른 프로세스가 파일 점유 중 → 기존 썸네일 재사용
                        LOG.warning(
                            f"[Thumb] 파일 사용 중 → 기존 썸네일 재사용: "
                            f"{thumb_path.name}"
                        )
                        return str(thumb_path)
                else:
                    return str(thumb_path)
            except PermissionError:
                # 열기 자체가 막힌 경우도 재사용
                LOG.warning(f"[Thumb] 파일 접근 불가 → 재사용: {thumb_path.name}")
                return str(thumb_path)
            except Exception:
                try:
                    thumb_path.unlink(missing_ok=True)
                except PermissionError:
                    return str(thumb_path)   # 손상됐지만 삭제 불가 → 재사용
        else:
            return str(thumb_path)
    ext = src.suffix.lower()
    img = None
    try:
        if ext in VIDEO_EXTS and _HAS_CV2:
            cap = cv2.VideoCapture(str(src))
            try:
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
                ret, frame = cap.read()
            finally:
                cap.release()
            if ret and _HAS_PIL:
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        elif ext in IMG_EXTS and _HAS_PIL:
            with Image.open(str(src)) as raw:
                img = raw.copy()
        if img and _HAS_PIL:
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            bg = Image.new('RGB', THUMB_SIZE, (40, 40, 40))
            ofs = ((THUMB_SIZE[0]-img.width)//2, (THUMB_SIZE[1]-img.height)//2)
            bg.paste(img, ofs)
            bg.save(str(thumb_path), 'JPEG', quality=75)
            img.close()
            LOG.debug(f"썸네일 생성: {src.name}")
            return str(thumb_path)
    except PermissionError as e:
        LOG.warning(f"[Thumb] 썸네일 저장 권한 없음: {src.name} — {e}")
    except Exception as e:
        LOG.error(f"썸네일 실패 {src.name}: {e}")
    return None
