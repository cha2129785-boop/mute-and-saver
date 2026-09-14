# -*- coding: utf-8 -*-
"""
constants — 앱 전역 상수
Mute&Saver v1.0.0
"""
import os
import sys
from pathlib import Path

APP_NAME     = "MuteAndSaver"            # 폴더·로그·시스템 식별자
APP_DISPLAY  = "Mute&Saver"             # UI 표시명
APP_VERSION  = "1.4.38"   # 리본 TXT 불러오기(.txt→새 메모) 추가
# 제작자 서명(저작권 검증용) — 제작자 식별 문자열의 SHA256 단방향 해시.
# 원본 복원 불가. 분쟁 시 제작자가 보관한 원본 문자열을 제시 → 이 값과 일치로 저작권 증명.
APP_AUTHOR_SIG = "9a1dacb56bda0f297166c380449d3902140701b4a28074356bd938a4312de2e2"
APP_AUTHOR_DISPLAY = "슈글 (Shugle)"    # UI 표시용 제작자명 (이메일 비노출)
EULA_VERSION = "1.2"      # 사용권 계약 버전 — 갱신 시 재동의 요구
# UI 여백 규격 (설정 탭 섹션 리듬 통일 — v1.3.29)
UI_LF_PADDING = (8, 4)   # LabelFrame 내부 패딩
UI_PAD_SEC    = (0, 6)   # 섹션(LabelFrame) 하단 간격
UI_PAD_SEP    = (6, 4)   # 구분선(Separator) 상하 간격
# 후원(도네이션) 링크
DONATE_URL       = "https://buymeacoffee.com/reading83"   # 해외/글로벌
DONATE_URL_KAKAO = "https://qr.kakaopay.com/Ej76S26kQ"    # 국내 (카카오페이 받기)
# 업데이트 확인(옵트인 수동) — 클릭 시에만 GitHub 릴리스 버전 조회. 사용자 데이터 미전송.
GITHUB_OWNER        = "cha2129785-boop"
GITHUB_REPO         = "mute-and-saver"
GITHUB_API_LATEST   = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
# 관리자 키 히든 언락 — 평문 미저장. 검증은 pin_service._verify_master(PBKDF2-SHA256) 재사용.
# 아래는 슬라이딩 입력버퍼 윈도우 길이만(문자열 아님 → 노출 무해).
ADMIN_UNLOCK_LEN = 10
MUTEX_NAME   = "Local\\MuteAndSaver_Mutex_v1"   # Local\ = 현재 사용자 세션, UAC 권한 불필요
CONFIG_SCHEMA = 10  # v10: tab_order 추가 (Stage D — 탭 드래그앤드롭 순서 영속화)

TIER_CONFIG = {
    "free": {
        "max_videos":  5,       # 영상만
        "max_images":  10,      # 이미지만
        "random_play": False,
        "max_memos":   15,      # 화면 표시 제한 (데이터는 보존)
        "max_presets": 7,
    },
    "premium": {
        "max_videos":  20,      # 영상만
        "max_images":  40,      # 이미지만 (free 역전 방지 상향)
        "random_play": True,
        "max_memos":   30,      # free 15 역전 방지 상향
        "max_presets": 20,
    },
}

# ══════════════════════════════════════════════════════
# [1] 경로 설정
# ══════════════════════════════════════════════════════
_frozen = getattr(sys, 'frozen', False)

# ── 읽기 전용: 설치 폴더 (영상·아이콘·폰트) ─────────────
# One-file 빌드: _MEIPASS (임시 압축 해제 폴더) 우선
# One-dir  빌드: exe 옆 폴더
# 개발(.py)   : 현재 스크립트 위치
if _frozen:
    BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
else:
    BASE_DIR = Path(__file__).parent

# ── 쓰기 가능: 사용자 데이터 폴더 (config·즐겨찾기·로그) ──
# %LOCALAPPDATA%\MuteAndSaver  (UAC 없이 자유롭게 읽기/쓰기)
_local_appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
APPDATA_DIR    = Path(_local_appdata) / APP_NAME
THUMBS_DIR     = APPDATA_DIR / "thumbs"
LOGS_DIR       = APPDATA_DIR / "logs"
CUSTOM_BGS_DIR = APPDATA_DIR / "custom_bgs"   # P2: 사용자 이미지 배경 내부 복사본
CONFIG_PATH    = APPDATA_DIR / "config.json"
FAVORITES_PATH = APPDATA_DIR / "favorites.json"
MEMO_PATH      = APPDATA_DIR / "memo.json"
USER_THEMES_PATH = APPDATA_DIR / "user_themes.json"   # P2: 사용자 정의 테마
USER_PRESETS_PATH = APPDATA_DIR / "user_presets.json"  # 사용자 프리셋 오버라이드 레이어
LOG_PATH       = LOGS_DIR   / "screensaver.log"

def resource_path(rel: str) -> str:
    """설치 폴더 기준 리소스 경로 반환 (영상·아이콘·폰트 등 읽기 전용)."""
    return str(BASE_DIR / rel)

# ── 설치 폴더 내 서브 경로 ────────────────────────────
ASSETS_DIR   = BASE_DIR / "assets"
PREMIUM_DIR  = ASSETS_DIR / "premium"
FONTS_DIR    = ASSETS_DIR / "fonts"
ICON_PATH    = ASSETS_DIR / "app.ico"   # 창 타이틀·트레이 아이콘 (exe 아이콘과 동일)
# 기본 번들 미디어 (사용설명서) — 첫 실행 라이브러리 시드 + 기본 선택
_MANUAL_DIR = ASSETS_DIR / "default_media"
DEFAULT_MANUAL_MEDIA    = str(_MANUAL_DIR / "manual.png")      # 한글(기본)
DEFAULT_MANUAL_MEDIA_EN = str(_MANUAL_DIR / "manual_en.png")   # 영문(그 외 언어 기본)
MANUAL_BY_LANG = {
    "ko": DEFAULT_MANUAL_MEDIA,
    "en": DEFAULT_MANUAL_MEDIA_EN,
    "zh": str(_MANUAL_DIR / "manual_zh.png"),
    "ja": str(_MANUAL_DIR / "manual_ja.png"),
    "ru": str(_MANUAL_DIR / "manual_ru.png"),
}

def manual_media_for(lang: str) -> str:
    """언어별 사용설명서 경로. 미지원 언어는 영문."""
    return MANUAL_BY_LANG.get(lang, DEFAULT_MANUAL_MEDIA_EN)
KAKAO_QR_PATH = ASSETS_DIR / "kakao_qr.png"   # 카카오페이 후원 QR (About 탭 표시)

IMG_EXTS   = {'.jpg', '.jpeg', '.png', '.bmp', '.gif'}
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov'}
THUMB_SIZE = (120, 68)   # 16:9 근사 비율 — 카드 하단 클리핑 방지

# ── 메모 보드 상수 ──────────────────────────────────────
MEMO_COLORS: dict = {
    # key: (배경색, 헤더강조색)  — MemoBoardViewer 렌더링 기준
    "yellow": ("#fff9c4", "#f9a825"),
    "blue":   ("#bbdefb", "#1565c0"),
    "pink":   ("#f8bbd0", "#ad1457"),
    "green":  ("#c8e6c9", "#2e7d32"),
    "white":  ("#f5f5f5", "#9e9e9e"),
    "dark":   ("#37474f", "#263238"),
    # 신규 7색
    "orange": ("#ffe0b2", "#e65100"),
    "purple": ("#e1bee7", "#6a1b9a"),
    "red":    ("#ffcdd2", "#b71c1c"),
    "teal":   ("#b2dfdb", "#004d40"),
    "indigo": ("#c5cae9", "#1a237e"),
    "amber":  ("#fff8e1", "#ff8f00"),
    "rose":   ("#fce4ec", "#880e4f"),
}
# 메모 글자 색상 (제목/본문 개별 지정용) — 미지정 시 각 렌더의 기본색 사용
TEXT_COLORS: dict = {
    "white":  "#ffffff",
    "black":  "#1a1a1a",
    "red":    "#e53935",
    "blue":   "#1e88e5",
    "yellow": "#f9a825",
}
MAX_MEMO_FREE       = 3
MAX_MEMO_PREMIUM    = 50
MEMO_SAVE_DEBOUNCE_MS = 2000

# ── 설정 프리셋 ──────────────────────────────────────────
# 내장 프리셋 — '기본'(none)만. 적용 시: 화면보호기+음소거 ON, 미디어 모드,
#   사용설명서 선택, 잠금 메시지 'Mute&Saver'. (보조 모니터 블랙은 배정 기본값에서 처리)
PRESETS: dict = {
    "none": {
        "screensaver_enabled": True,
        "mute_on_screensaver": True,
        "screensaver_mode":    "media",
        "pin_message":         "Mute&Saver",
        "selected_media":      [DEFAULT_MANUAL_MEDIA],
    },
}

# ── 메모 템플릿 ──────────────────────────────────────────
MEMO_TEMPLATES: dict = {
    "빈 메모":    {"title": "새 메모",    "body": ""},
    "체크리스트": {"title": "✅ 할 일",   "body": "☐ 항목 1\n☐ 항목 2\n☐ 항목 3"},
    "오늘 일정":  {"title": "📅 일정",    "body": "오전:\n오후:\n저녁:"},
    "중요 알림":  {"title": "⚠️ 중요",   "body": "기억할 것:\n\n마감:"},
    "회의 메모":  {"title": "📋 회의",    "body": "참석자:\n안건:\n결론:"},
    "아이디어":   {"title": "💡 아이디어","body": ""},
}


def _blend_color(fg: str, bg: str, alpha: float) -> str:
    """두 hex 색상을 alpha 비율로 혼합. alpha=1.0 → fg 그대로."""
    try:
        fr = int(fg[1:3], 16); fg_ = int(fg[3:5], 16); fb = int(fg[5:7], 16)
        br = int(bg[1:3], 16); bg_ = int(bg[3:5], 16); bb = int(bg[5:7], 16)
        r = max(0, min(255, int(fr * alpha + br * (1 - alpha))))
        g = max(0, min(255, int(fg_ * alpha + bg_ * (1 - alpha))))
        b = max(0, min(255, int(fb * alpha + bb * (1 - alpha))))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return fg


def _darken(hex_color: str, factor: float = 0.5) -> str:
    """hex 색을 factor 비율로 어둡게 (커스텀 색 헤더강조색 자동 생성)."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
        return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"
    except Exception:
        return hex_color


def is_custom_color(color_key) -> bool:
    """color_key가 커스텀 hex(#rrggbb)인지 판정."""
    return isinstance(color_key, str) and color_key.startswith("#")


# 캔버스 배경색 기준으로 Pre-blended 색상 사전 계산 (앱 시작 시 1회)
# 드래그 중 PIL 재계산 없음 → CPU 영향 0
_CANVAS_BG = "#1a1a2e"   # 기본 캔버스 배경

def _build_opacity_presets() -> dict:
    """MEMO_COLORS 기반 opacity별 blended 색상 계산."""
    presets = {}
    for op in [1.0, 0.7, 0.4]:
        presets[op] = {}
        for key, (card_bg, hdr_color) in MEMO_COLORS.items():
            presets[op][key] = (
                _blend_color(card_bg,    _CANVAS_BG, op),
                _blend_color(hdr_color,  _CANVAS_BG, op),
            )
    return presets

OPACITY_PRESETS: dict = _build_opacity_presets()   # 드래그 후 저장 딜레이(ms)

# ── 메모보드 배경 테마 ───────────────────────────────────
MEMO_BG_THEMES: dict = {
    "white": {
        "label":   "화이트",
        "bg_type": "solid",
        "color":   "#ffffff",
        "desc":    "깨끗한 흰색 배경",
    },
    "grid": {
        "label":      "모눈종이",
        "bg_type":    "pattern",
        "color":      "#f8f9fa",
        "line_color": "#d1d5db",
        "grid_gap":   24,
        "desc":       "모눈종이 패턴",
    },
    "paper": {
        "label":      "페이퍼",
        "bg_type":    "pattern",
        "color":      "#fafaf7",
        "line_color": "#e8e4da",
        "grid_gap":   28,
        "desc":       "줄 노트 감성",
    },
    "forest": {
        "label":      "포레스트",
        "bg_type":    "gradient",
        "color":      "#0a1a0e",
        "color_end":  "#1a2e1a",
        "desc":       "숲 속 딥 그린 그라데이션",
    },
    "ocean": {
        "label":      "오션딥",
        "bg_type":    "gradient",
        "color":      "#020b18",
        "color_end":  "#0a2540",
        "desc":       "깊은 바다 딥 블루 그라데이션",
    },
}

# ══════════════════════════════════════════════════════
# 기본 단축키 (default 모드 표준값 — 여러 곳에서 공유)
DEFAULT_SS_HOTKEY = "ctrl+space"           # 화면보호기 켜기/끄기
DEFAULT_QM_HOTKEY = "ctrl+alt+semicolon"   # 퀵 메모 (ctrl+alt+;)

DEFAULT_CONFIG: dict = {
    "schema_version":         CONFIG_SCHEMA,
    "screensaver_enabled":    True,
    "power_save_enabled":     False,
    "mute_on_screensaver":    True,           # 기본: 화면보호기 시 음소거 ON
    "timeout_seconds":        300,
    "pin_hash":               "",
    "pin_set":                False,
    "hotkey_screensaver":     DEFAULT_SS_HOTKEY,   # 화면보호기 단축키
    "hotkey_quick_memo":      DEFAULT_QM_HOTKEY,   # 퀵 메모 단축키
    "qm_hotkey_mode":         "default",           # 퀵 메모 단축키 모드 (default/custom)
    "language":               "ko",
    "media_interval_seconds": 10,
    "slide_mode":             "random",
    "slide_auto":             True,   # True=자동(초 간격) / False=수동(Tab으로 다음)
    "selected_media":         [DEFAULT_MANUAL_MEDIA],   # 기본 선택: 사용설명서
    "first_run":              True,
    # v2 추가 ─────────────────────────────
    "screensaver_mode":       "media",   # "media" | "memo" | "split"
    "split_ratio":            0.65,
    "split_direction":        "h",       # "h"=좌우 | "v"=상하
    "monitor_assignments":    [],
    "blur_lock_bg":           True,    # 잠금화면 배경 블러 효과
    "memo_bg_blur":           False,   # 메모보드 배경 블러
    "memo_blur_radius":       1,       # 블러 강도 사용자 입력값 (0~10) → PIL radius × 0.5
    "memo_editor_canvas_w":   600,
    "memo_editor_canvas_h":   360,
    # v3 추가 ─────────────────────────────
    "pin_message":            "Mute&Saver",   # 잠금 메시지 (기본: 앱명)
    # v4 추가 ─────────────────────────────
    "memo_bg_theme":          "paper",   # 메모보드 배경 테마 (기본: 페이퍼)
    "memo_opacity":           0.0,       # 메모 카드 전체 투명도 (0.0=불투명, 1.0=완전투명)
    # v6 추가 ─────────────────────────────
    "pin_message_font_size":  12,        # 잠금 메시지 폰트 크기 (8~24)
    # v10 추가 ────────────────────────────
    "tab_order": ["setting", "media", "hotkey", "memo", "license", "lang"],  # 탭 순서 (드래그앤드롭 영속화)
    # Stage F 추가 ───────────────────────
    "active_preset": None,   # 현재 적용 중 프리셋 키 (표시용, None-safe → 마이그레이션 불필요)
    # 커스텀 메모 색상 (팔레트 직접 선택 → hex 저장, 전 메모 공유) ─────
    "custom_memo_colors": [],   # ["#a1b2c3", ...] — None-safe
    # 커스텀 메모 글꼴 (시스템 글꼴 선택 → 이름 저장, 전 메모 공유) ─────
    "custom_memo_fonts": [],    # ["Batang", ...] — None-safe
    # 미디어 탭 즐겨찾기 표시 옵션 ─────
    "media_fav_top":  False,    # 즐겨찾기 위로 정렬
    "media_fav_only": False,    # 즐겨찾기만 보기
    # 메인 창 크기·위치 기억 ("WxH+X+Y", 빈값=미저장) ─────
    "win_geometry":   "",
    # 수락한 사용권 계약 버전 (""=미동의 → 첫 실행 동의창 표시) ─────
    "eula_accepted":  "",
}


LOCK_FILE = BASE_DIR / ".secmon.lock"   # PID Lock 파일

def init_dirs():
    """필수 디렉토리 생성 — import 시 자동 실행."""
    for d in [APPDATA_DIR, THUMBS_DIR, LOGS_DIR, CUSTOM_BGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    for d in [PREMIUM_DIR, FONTS_DIR]:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

init_dirs()

# ── 단축키/언어 상수 ──
LANGUAGES = [
    ("ko", "한국어 (기본)"),
    ("en", "English"),
    ("zh", "中文"),
    ("ja", "日本語"),
    ("ru", "Русский"),
]

RECOMMENDED_HOTKEYS = [
    "ctrl+space","ctrl+shift+l","ctrl+alt+s","ctrl+shift+z",
    "windows+shift+s","ctrl+f12",
]

MODIFIER_ONLY = {"ctrl","alt","shift","windows","cmd","meta"}

RESERVED_HOTKEYS = {
    "ctrl+c","ctrl+v","ctrl+x","ctrl+z","ctrl+y","ctrl+a","ctrl+s",
    "ctrl+f","ctrl+p","ctrl+n","ctrl+o","ctrl+w","ctrl+t","ctrl+r",
    "alt+f4","alt+tab","alt+enter","alt+space",
    "ctrl+alt+delete","ctrl+shift+esc",
    "windows+l","windows+d","windows+e","windows+r","windows+tab",
}

