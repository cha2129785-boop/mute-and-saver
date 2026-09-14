# -*- coding: utf-8 -*-
"""
audio_service — 시스템 음소거 제어 (pycaw + COM)
"""
import logging

LOG = logging.getLogger("MuteAndSaver")

_HAS_PYCAW = False
try:
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL, CoInitialize, CoCreateInstance, GUID
    from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator
    _HAS_PYCAW = True
    CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
except ImportError:
    pass

class SystemAudioController:
    """
    Windows 시스템 볼륨 음소거/복구 (Core Audio COM 다이렉트).

    COM 스레드 안전 설계:
    - 각 메서드 내부에서 COM 프록시 획득 → 사용 → 로컬 del
    - CoInitialize 는 매 호출 시도(idempotent — 이미 초기화 시 S_FALSE, 무해)
    - ⚠️ CoUninitialize 는 호출하지 않음: 장시간 실행 앱에서 COM 채널을 매 호출
      닫으면, 이후 잔존 COM 프록시가 지연 GC로 Release 될 때 이미 닫힌 채널을
      참조해 access violation(네이티브 크래시) 발생. 채널을 스레드 수명 동안
      유지해야 지연 GC Release 가 안전함. (fault.log: json.dump 중 GC →
      comtypes __del__ → Release → access violation 로 확진)
    """
    def __init__(self):
        self.was_muted = False
        self._vol = None            # 앱 수명 싱글톤 COM 인터페이스(드롭 안 함)
        LOG.info(f"[Audio] COM 다이렉트 제어기 준비 완료 (pycaw: {_HAS_PYCAW})")

    def _get_vol(self):
        """볼륨 인터페이스 1회 생성 후 캐시(싱글톤).
        ⚠️ 근본 크래시 차단(B): 매 호출 생성/드롭하면 잔존 comtypes 프록시가
           자동 GC로 임의 시점 Release → access violation. 앱 수명 동안 강참조로
           보유해 GC 대상에서 제외. 종료 시 close()에서 메인스레드 명시 해제."""
        if self._vol is not None:
            return self._vol
        if not _HAS_PYCAW:
            return None
        try:
            CoInitialize()   # 현재 스레드 COM 채널 개설(idempotent)
        except Exception:
            pass
        try:
            enumerator = CoCreateInstance(
                CLSID_MMDeviceEnumerator,
                interface=IMMDeviceEnumerator,
                clsctx=CLSCTX_ALL
            )
            endpoint  = enumerator.GetDefaultAudioEndpoint(0, 1)
            interface = endpoint.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None
            )
            self._vol = cast(interface, POINTER(IAudioEndpointVolume))
        except Exception as e:
            LOG.error(f"[Audio] COM 인터페이스 생성 실패: {e}")
            self._vol = None
        return self._vol

    def close(self):
        """종료 시 메인스레드에서 명시 해제 (채널 살아있는 동안 안전 Release)."""
        self._vol = None

    def _with_volume(self, callback):
        """캐시된 볼륨 인터페이스로 callback 실행. 생성/드롭/gc.collect 없음
        (싱글톤 보유 + 전역 자동 GC off(A) → 중간 수거 자체가 발생하지 않음)."""
        vol = self._get_vol()
        if vol is None:
            return
        try:
            callback(vol)
        except Exception as e:
            LOG.error(f"[Audio] COM 볼륨 제어 실패: {e}")

    def mute_if_needed(self, should_mute: bool):
        if not should_mute:
            return
        LOG.info("[Audio] 🛑 mute_if_needed 진입: 목표 = ON(잠금)")

        def _do_mute(vol):
            try:
                current_mute = bool(vol.GetMute())
                LOG.info(f"[Audio] 1. 현재 시스템 음소거 상태: {current_mute}")
            except Exception as e:
                LOG.error(f"[Audio] 🚨 볼륨 상태 읽기 실패: {e}")
                return

            if not current_mute:
                vol.SetMute(1, None)
                self.was_muted = False
                LOG.info("[Audio] 2. ✅ 시스템 음소거 ON 적용 완료")
            else:
                self.was_muted = True   # 원래부터 음소거 상태
                LOG.info("[Audio] 2. ⚠️ 이미 음소거 상태 → 명령 스킵 (중복 방어)")

        LOG.info("[Audio] → COM 채널 오픈 요청 (_with_volume)")
        self._with_volume(_do_mute)
        LOG.info("[Audio] 🏁 mute_if_needed 프로세스 완전 종료")

    def restore_audio(self, should_mute: bool):
        if not should_mute:
            return
        LOG.info("[Audio] 🛑 restore_audio 진입: 목표 = OFF(복구)")

        def _do_restore(vol):
            try:
                current_mute = bool(vol.GetMute())
                LOG.info(f"[Audio] 1. 현재 시스템 음소거 상태: {current_mute}")
            except Exception as e:
                LOG.error(f"[Audio] 🚨 볼륨 상태 읽기 실패: {e}")
                return

            if current_mute and not self.was_muted:
                vol.SetMute(0, None)
                LOG.info("[Audio] 2. ✅ 시스템 음소거 OFF 복구 완료")
            else:
                LOG.info(f"[Audio] 2. ⚠️ 복구 조건 미충족 (current={current_mute}, was_muted={self.was_muted}) → 스킵")

        LOG.info("[Audio] → COM 채널 오픈 요청 (_with_volume)")
        self._with_volume(_do_restore)
        LOG.info("[Audio] 🏁 restore_audio 프로세스 완전 종료")
