# -*- coding: utf-8 -*-
"""
make_manual — 사용설명서 이미지 생성기 (개발용, 배포 미포함)

HTML → Chromium(headless) 렌더 → assets/default_media/manual_<lang>.png (3200x1800).
언어별 텍스트를 이 파일에서만 고치면 전 언어 재생성. 버전은 constants.APP_VERSION 자동 반영.

사전: pip install playwright  (그리고 브라우저: playwright install chromium)
실행: python tools/make_manual.py
"""
import base64
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "mute_and_saver"
ASSETS = PKG / "assets"
OUT_DIR = ASSETS / "default_media"

def app_version() -> str:
    txt = (PKG / "constants.py").read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', txt)
    return m.group(1) if m else "0.0.0"

def slidey_data_uri() -> str:
    from PIL import Image
    im = Image.open(ASSETS / "app.ico").convert("RGBA")
    bb = im.getbbox()
    if bb:
        im = im.crop(bb)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

# ── 언어별 텍스트 (여기만 고치면 됨) ─────────────────────────
LANGS = ["ko", "en", "zh", "ja", "ru"]   # 언어 추가 시 여기 + 아래 T 채우기

T = {
    "ko": {
        "subtitle": "화면보호기 · 시스템 음소거 · 멀티 메모보드  —  사용 설명서",
        "platform": "Windows · 한 / En / 中 / 日 / Py",
        "c1_title": "단축키", "c1_emoji": "⌨️",
        "c1_rows": [
            ("keys", ["Ctrl", "Space"], "<b>화면보호기 켜기 / 끄기</b>"),
            ("keys", ["Ctrl", "Alt", ";"], "<b>퀵 메모</b> 바로 작성"),
            ("keys", ["ESC"], "화면보호기 <b>종료</b> <span class='dim'>(PIN 설정 시 PIN 입력)</span>"),
        ],
        "c1_note": "※ 단축키는 「단축키」 탭에서 변경 가능",
        "c2_title": "탭 안내", "c2_emoji": "📁",
        "c2_rows": [
            ("설정", "프리셋 · 기본설정 · 화면보호기 모드 · 모니터 배정 · PIN"),
            ("미디어", "이미지 / 영상 추가 · 선택 · 즐겨찾기"),
            ("단축키", "단축키 변경"),
            ("메모보드", "메모 작성 · 편집 · 테마"),
            ("언어·정보", "한글 · English · 中文 · 日本語 · Русский"),
        ],
        "c3_title": "화면보호기 모드", "c3_emoji": "🎬",
        "c3_rows": [
            ("tag-media", "미디어", "선택한 영상 · 이미지 재생"),
            ("tag-memo", "메모", "메모보드 전체 표시"),
            ("tag-split", "분할", "미디어 + 메모 동시 (비율 조절)"),
        ],
        "c3_note": "🕐 <b>시계</b> — 미디어가 없을 때 자동 대체 표시 <span class='dim'>(선택 모드 아님)</span>",
        "c4_title": "프리셋", "c4_emoji": "⭐",
        "c4_rows": [
            "자주 쓰는 <b>설정 조합</b>을 저장 → 카드 <b>클릭 한 번</b>으로 적용",
            "모드 · 테마 · 단축키 · <b>선택한 미디어</b>까지 함께 저장",
        ],
        "c4_notes": [
            "✔ 적용 중 프리셋은 초록 테두리 + 체크로 표시",
            "🗑 프리셋에 저장된 미디어 삭제 시 확인 알림",
        ],
        "c5_title": "멀티 모니터", "c5_emoji": "🖥️",
        "c5_main": "<span class='dot'>●</span> <b>주 모니터</b> — 전역 화면보호기 모드 적용",
        "c5_sub": "<b>보조 모니터</b> — 아래 중 선택",
        "c5_chips": [("chip-video", "영상"), ("chip-image", "이미지"),
                     ("chip-memo", "메모"), ("chip-black", "검은화면")],
        "c5_notes": [
            "🗺️ <b>배치도(미니맵)</b> 사각형을 클릭하면 모드가 순환 전환",
            "🎬 보조 영상은 주 모니터가 영상 모드가 아닐 때 1개 재생",
        ],
        "c6_title": "알아두면 편해요", "c6_emoji": "🔧",
        "c6_rows": [
            "🔇 화면보호기 실행 시 <b>시스템 자동 음소거</b> (옵션)",
            "🔒 <b>PIN 잠금</b>으로 화면보호기 종료 보호",
            "🖼️ 미디어 탭에서 <b>즐겨찾기</b> ⭐ · 표시할 항목 선택",
        ],
        "c6_tip_label": "TIP",
        "c6_tip": "설정은 자동 저장 — 바꾸는 즉시 반영됩니다",
    },
    "en": {
        "subtitle": "Screensaver · System Mute · Multi Memo Board  —  User Guide",
        "platform": "Windows · 한 / En / 中 / 日 / Py",
        "c1_title": "Shortcuts", "c1_emoji": "⌨️",
        "c1_rows": [
            ("keys", ["Ctrl", "Space"], "<b>Turn screensaver on / off</b>"),
            ("keys", ["Ctrl", "Alt", ";"], "Open <b>Quick Memo</b>"),
            ("keys", ["ESC"], "<b>Exit</b> screensaver <span class='dim'>(enter PIN if set)</span>"),
        ],
        "c1_note": "※ Shortcuts can be changed in the “Shortcuts” tab",
        "c2_title": "Tabs", "c2_emoji": "📁",
        "c2_rows": [
            ("Settings", "Presets · Basics · Screensaver mode · Monitor assign · PIN"),
            ("Media", "Add images / videos · select · favorites"),
            ("Shortcuts", "Change hotkeys"),
            ("Memo board", "Write · edit · themes"),
            ("Language·Info", "한글 · English · 中文 · 日本語 · Русский"),
        ],
        "c3_title": "Screensaver Modes", "c3_emoji": "🎬",
        "c3_rows": [
            ("tag-media", "Media", "Play selected videos · images"),
            ("tag-memo", "Memo", "Show the full memo board"),
            ("tag-split", "Split", "Media + memo together (adjustable ratio)"),
        ],
        "c3_note": "🕐 <b>Clock</b> — auto fallback when no media <span class='dim'>(not a selectable mode)</span>",
        "c4_title": "Presets", "c4_emoji": "⭐",
        "c4_rows": [
            "Save a <b>combination of settings</b> → apply with <b>one click</b>",
            "Saves mode · theme · shortcuts · even the <b>selected media</b>",
        ],
        "c4_notes": [
            "✔ The active preset is shown with a green border + check",
            "🗑 Confirmation prompt before deleting media saved in a preset",
        ],
        "c5_title": "Multi-Monitor", "c5_emoji": "🖥️",
        "c5_main": "<span class='dot'>●</span> <b>Primary monitor</b> — uses the global screensaver mode",
        "c5_sub": "<b>Secondary monitors</b> — choose from below",
        "c5_chips": [("chip-video", "Video"), ("chip-image", "Image"),
                     ("chip-memo", "Memo"), ("chip-black", "Black")],
        "c5_notes": [
            "🗺️ <b>Mini-map</b> — click a rectangle to cycle its mode",
            "🎬 A secondary video plays when the primary isn’t in video mode",
        ],
        "c6_title": "Good to Know", "c6_emoji": "🔧",
        "c6_rows": [
            "🔇 <b>Auto-mute system audio</b> when the screensaver starts (optional)",
            "🔒 Protect exit with a <b>PIN lock</b>",
            "🖼️ Pick <b>favorites</b> ⭐ to show in the Media tab",
        ],
        "c6_tip_label": "TIP",
        "c6_tip": "Settings auto-save — changes apply instantly",
    },
    "zh": {
        "subtitle": "屏幕保护 · 系统静音 · 多显示器便签板  —  使用说明",
        "platform": "Windows · 한 / En / 中 / 日 / Py",
        "c1_title": "快捷键", "c1_emoji": "⌨️",
        "c1_rows": [
            ("keys", ["Ctrl", "Space"], "<b>开启 / 关闭屏幕保护</b>"),
            ("keys", ["Ctrl", "Alt", ";"], "打开<b>快速便签</b>"),
            ("keys", ["ESC"], "<b>退出</b>屏幕保护 <span class='dim'>(若设置了PIN则输入)</span>"),
        ],
        "c1_note": "※ 快捷键可在「快捷键」标签页中更改",
        "c2_title": "标签页", "c2_emoji": "📁",
        "c2_rows": [
            ("设置", "预设 · 基本设置 · 屏保模式 · 显示器分配 · PIN"),
            ("媒体", "添加图片 / 视频 · 选择 · 收藏"),
            ("快捷键", "更改快捷键"),
            ("便签板", "编写 · 编辑 · 主题"),
            ("语言·信息", "한글 · English · 中文 · 日本語 · Русский"),
        ],
        "c3_title": "屏保模式", "c3_emoji": "🎬",
        "c3_rows": [
            ("tag-media", "媒体", "播放所选视频 · 图片"),
            ("tag-memo", "便签", "显示整个便签板"),
            ("tag-split", "分屏", "媒体 + 便签同时 (可调比例)"),
        ],
        "c3_note": "🕐 <b>时钟</b> — 无媒体时自动替代显示 <span class='dim'>(非可选模式)</span>",
        "c4_title": "预设", "c4_emoji": "⭐",
        "c4_rows": [
            "保存常用的<b>设置组合</b> → <b>单击</b>卡片即可应用",
            "一并保存模式 · 主题 · 快捷键 · <b>所选媒体</b>",
        ],
        "c4_notes": [
            "✔ 当前预设以绿色边框 + 勾选显示",
            "🗑 删除预设中保存的媒体时会提示确认",
        ],
        "c5_title": "多显示器", "c5_emoji": "🖥️",
        "c5_main": "<span class='dot'>●</span> <b>主显示器</b> — 使用全局屏保模式",
        "c5_sub": "<b>副显示器</b> — 从下方选择",
        "c5_chips": [("chip-video", "视频"), ("chip-image", "图片"),
                     ("chip-memo", "便签"), ("chip-black", "黑屏")],
        "c5_notes": [
            "🗺️ <b>小地图</b> — 点击方块循环切换其模式",
            "🎬 主显示器非视频模式时，副屏播放一个视频",
        ],
        "c6_title": "实用提示", "c6_emoji": "🔧",
        "c6_rows": [
            "🔇 屏保启动时<b>自动静音系统</b> (可选)",
            "🔒 用<b>PIN锁</b>保护退出",
            "🖼️ 在媒体标签选择<b>收藏</b> ⭐ · 要显示的项目",
        ],
        "c6_tip_label": "TIP",
        "c6_tip": "设置自动保存 — 更改即时生效",
    },
    "ja": {
        "subtitle": "スクリーンセーバー · システム消音 · マルチメモボード  —  使用説明",
        "platform": "Windows · 한 / En / 中 / 日 / Py",
        "c1_title": "ショートカット", "c1_emoji": "⌨️",
        "c1_rows": [
            ("keys", ["Ctrl", "Space"], "<b>スクリーンセーバー オン / オフ</b>"),
            ("keys", ["Ctrl", "Alt", ";"], "<b>クイックメモ</b>を開く"),
            ("keys", ["ESC"], "スクリーンセーバー<b>終了</b> <span class='dim'>(PIN設定時は入力)</span>"),
        ],
        "c1_note": "※ ショートカットは「ショートカット」タブで変更可能",
        "c2_title": "タブ案内", "c2_emoji": "📁",
        "c2_rows": [
            ("設定", "プリセット · 基本設定 · SSモード · モニター割当 · PIN"),
            ("メディア", "画像 / 動画 追加 · 選択 · お気に入り"),
            ("ショートカット", "ショートカット変更"),
            ("メモボード", "作成 · 編集 · テーマ"),
            ("言語·情報", "한글 · English · 中文 · 日本語 · Русский"),
        ],
        "c3_title": "SSモード", "c3_emoji": "🎬",
        "c3_rows": [
            ("tag-media", "メディア", "選択した動画 · 画像を再生"),
            ("tag-memo", "メモ", "メモボード全体を表示"),
            ("tag-split", "分割", "メディア + メモ同時 (比率調整)"),
        ],
        "c3_note": "🕐 <b>時計</b> — メディアが無い時に自動代替表示 <span class='dim'>(選択モードではない)</span>",
        "c4_title": "プリセット", "c4_emoji": "⭐",
        "c4_rows": [
            "よく使う<b>設定の組み合わせ</b>を保存 → カード<b>ワンクリック</b>で適用",
            "モード · テーマ · ショートカット · <b>選択したメディア</b>まで保存",
        ],
        "c4_notes": [
            "✔ 適用中のプリセットは緑枠 + チェックで表示",
            "🗑 プリセット内メディア削除時に確認",
        ],
        "c5_title": "マルチモニター", "c5_emoji": "🖥️",
        "c5_main": "<span class='dot'>●</span> <b>主モニター</b> — 全体SSモードを適用",
        "c5_sub": "<b>副モニター</b> — 下から選択",
        "c5_chips": [("chip-video", "動画"), ("chip-image", "画像"),
                     ("chip-memo", "メモ"), ("chip-black", "黒画面")],
        "c5_notes": [
            "🗺️ <b>ミニマップ</b> — 四角をクリックでモード循環",
            "🎬 主モニターが動画モードでない時、副で1つ再生",
        ],
        "c6_title": "知っておくと便利", "c6_emoji": "🔧",
        "c6_rows": [
            "🔇 スクリーンセーバー時に<b>システム自動消音</b> (オプション)",
            "🔒 <b>PINロック</b>で終了を保護",
            "🖼️ メディアタブで<b>お気に入り</b> ⭐ · 表示項目を選択",
        ],
        "c6_tip_label": "TIP",
        "c6_tip": "設定は自動保存 — 変更は即時反映",
    },
    "ru": {
        "subtitle": "Заставка · Отключение звука · Доска заметок  —  Руководство",
        "platform": "Windows · 한 / En / 中 / 日 / Py",
        "c1_title": "Горячие клавиши", "c1_emoji": "⌨️",
        "c1_rows": [
            ("keys", ["Ctrl", "Space"], "<b>Вкл / выкл заставку</b>"),
            ("keys", ["Ctrl", "Alt", ";"], "Открыть <b>быструю заметку</b>"),
            ("keys", ["ESC"], "<b>Выход</b> из заставки <span class='dim'>(ввод PIN, если задан)</span>"),
        ],
        "c1_note": "※ Клавиши меняются во вкладке «Горячие клавиши»",
        "c2_title": "Вкладки", "c2_emoji": "📁",
        "c2_rows": [
            ("Настройки", "Пресеты · Основные · Режим заставки · Мониторы · PIN"),
            ("Медиа", "Добавить изображения / видео · выбор · избранное"),
            ("Клавиши", "Изменить горячие клавиши"),
            ("Заметки", "Создать · править · темы"),
            ("Язык·Инфо", "한글 · English · 中文 · 日本語 · Русский"),
        ],
        "c3_title": "Режимы заставки", "c3_emoji": "🎬",
        "c3_rows": [
            ("tag-media", "Медиа", "Воспроизведение видео · изображений"),
            ("tag-memo", "Заметки", "Показать всю доску заметок"),
            ("tag-split", "Раздел.", "Медиа + заметки вместе (регулируемо)"),
        ],
        "c3_note": "🕐 <b>Часы</b> — авто-замена при отсутствии медиа <span class='dim'>(не выбираемый режим)</span>",
        "c4_title": "Пресеты", "c4_emoji": "⭐",
        "c4_rows": [
            "Сохраните <b>набор настроек</b> → примените <b>одним кликом</b>",
            "Сохраняет режим · тему · клавиши · <b>выбранное медиа</b>",
        ],
        "c4_notes": [
            "✔ Активный пресет — зелёная рамка + галочка",
            "🗑 Подтверждение перед удалением медиа из пресета",
        ],
        "c5_title": "Мультимонитор", "c5_emoji": "🖥️",
        "c5_main": "<span class='dot'>●</span> <b>Основной монитор</b> — глобальный режим заставки",
        "c5_sub": "<b>Доп. мониторы</b> — выберите ниже",
        "c5_chips": [("chip-video", "Видео"), ("chip-image", "Изображ."),
                     ("chip-memo", "Заметка"), ("chip-black", "Чёрный")],
        "c5_notes": [
            "🗺️ <b>Мини-карта</b> — клик по прямоугольнику меняет режим",
            "🎬 Доп. видео играет, когда основной не в режиме видео",
        ],
        "c6_title": "Полезно знать", "c6_emoji": "🔧",
        "c6_rows": [
            "🔇 <b>Авто-отключение звука</b> при запуске заставки (опция)",
            "🔒 Защита выхода <b>PIN-кодом</b>",
            "🖼️ Выберите <b>избранное</b> ⭐ для показа во вкладке Медиа",
        ],
        "c6_tip_label": "TIP",
        "c6_tip": "Настройки сохраняются автоматически — изменения сразу",
    },
}

def _keys(keys):
    return "".join(f"<span class='key'>{k}</span>" for k in keys)

def build_html(lang, ver, icon_uri):
    d = T[lang]
    # 카드 1 (단축키)
    c1 = "".join(
        f"<div class='row'><div class='keys'>{_keys(k)}</div><div class='txt'>{txt}</div></div>"
        for _, k, txt in d["c1_rows"])
    c1 += f"<div class='note'>{d['c1_note']}</div>"
    # 카드 2 (탭)
    c2 = "".join(
        f"<div class='kv'><div class='k'>{k}</div><div class='v'>{v}</div></div>"
        for k, v in d["c2_rows"])
    # 카드 3 (모드)
    c3 = "".join(
        f"<div class='row'><span class='tag {cls}'>{name}</span><div class='txt'>{txt}</div></div>"
        for cls, name, txt in d["c3_rows"])
    c3 += f"<div class='note'>{d['c3_note']}</div>"
    # 카드 4 (프리셋)
    c4 = "".join(f"<div class='line'>{r}</div>" for r in d["c4_rows"])
    c4 += "".join(f"<div class='note'>{n}</div>" for n in d["c4_notes"])
    # 카드 5 (멀티모니터)
    chips = "".join(f"<span class='chip {cls}'>{name}</span>" for cls, name in d["c5_chips"])
    c5 = (f"<div class='line'>{d['c5_main']}</div>"
          f"<div class='line'>{d['c5_sub']}</div>"
          f"<div class='chips'>{chips}</div>"
          + "".join(f"<div class='note'>{n}</div>" for n in d["c5_notes"]))
    # 카드 6 (팁)
    c6 = "".join(f"<div class='line'>{r}</div>" for r in d["c6_rows"])
    c6 += f"<div class='tip'><span class='tip-badge'>{d['c6_tip_label']}</span>{d['c6_tip']}</div>"

    def card(num, emoji, title, body):
        return (f"<div class='card'><div class='chead'>"
                f"<span class='cemoji'>{emoji}</span><span class='ctitle'>{title}</span>"
                f"<span class='cnum'>{num}</span></div>{body}</div>")

    grid = (card("01", d["c1_emoji"], d["c1_title"], c1)
            + card("02", d["c2_emoji"], d["c2_title"], c2)
            + card("05", d["c5_emoji"], d["c5_title"], c5)
            + card("03", d["c3_emoji"], d["c3_title"], c3)
            + card("04", d["c4_emoji"], d["c4_title"], c4)
            + card("06", d["c6_emoji"], d["c6_title"], c6))

    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:1600px; height:900px; }}
body {{ background:#eef1f5; font-family:'Noto Sans CJK KR','Noto Sans KR',sans-serif;
        color:#1f2d3d; padding:34px 40px; }}
.header {{ display:flex; align-items:center; gap:20px; }}
.logo {{ height:96px; }}
.htext {{ flex:1; }}
.title {{ font-family:'Poppins','Noto Sans CJK KR',sans-serif; font-weight:700;
          font-size:60px; letter-spacing:-1px; line-height:1; }}
.title .amp {{ color:#2f80d8; }}
.subtitle {{ margin-top:8px; font-size:20px; color:#6b7787; }}
.hright {{ text-align:right; }}
.verpill {{ display:inline-block; background:#1f2d3d; color:#fff; font-family:'Poppins',sans-serif;
           font-weight:700; font-size:21px; padding:7px 18px; border-radius:20px; }}
.platform {{ margin-top:10px; font-size:17px; color:#9aa4b0; }}
.divider {{ height:5px; background:#1f2d3d; border-radius:3px; margin:18px 0 22px; }}
.grid {{ display:grid; grid-template-columns:repeat(3,1fr); grid-auto-rows:1fr;
         gap:20px; height:648px; }}
.card {{ background:#fff; border-radius:20px; padding:20px 24px; overflow:hidden;
         box-shadow:0 6px 18px rgba(31,45,61,.06); }}
.chead {{ display:flex; align-items:center; gap:10px; margin-bottom:12px; }}
.cemoji {{ font-size:25px; }}
.ctitle {{ font-size:25px; font-weight:800; }}
.cnum {{ margin-left:auto; font-family:'Poppins',sans-serif; font-weight:700;
         font-size:18px; color:#c5ccd6; }}
.row {{ display:flex; align-items:center; gap:12px; margin:7px 0; font-size:18px; }}
.txt {{ flex:1; }}
.dim {{ color:#9aa4b0; font-size:16px; }}
.keys {{ display:flex; gap:6px; }}
.key {{ background:#2b3442; color:#fff; font-weight:700; font-size:15px;
        padding:5px 11px; border-radius:8px; min-width:32px; text-align:center; }}
.note {{ font-size:16px; color:#9aa4b0; margin-top:8px; }}
.kv {{ display:flex; gap:16px; margin:4px 0; font-size:17px; align-items:baseline;
       border-bottom:1px dashed #eceff3; padding-bottom:5px; }}
.kv:last-child {{ border-bottom:none; }}
.kv .k {{ color:#2f80d8; font-weight:800; width:158px; min-width:158px; padding-right:8px; line-height:1.25; }}
.kv .v {{ color:#5b6673; line-height:1.3; }}
.line {{ font-size:18px; margin:7px 0; color:#37404d; }}
.tag {{ color:#fff; font-weight:800; font-size:16px; padding:5px 14px; border-radius:8px; }}
.tag-media {{ background:#2e9e5b; }} .tag-memo {{ background:#e8873a; }}
.tag-split {{ background:#3b7dd8; }}
.chips {{ display:flex; gap:8px; margin:8px 0 2px; flex-wrap:wrap; }}
.chip {{ color:#fff; font-weight:800; font-size:16px; padding:6px 16px; border-radius:16px; }}
.chip-video {{ background:#8e5bd8; }} .chip-image {{ background:#2e9e5b; }}
.chip-memo {{ background:#e8873a; }} .chip-black {{ background:#2b3442; }}
.dot {{ color:#2f80d8; }}
.tip {{ margin-top:12px; font-size:18px; color:#5b6673; }}
.tip-badge {{ background:#fff3d6; color:#b8860b; font-weight:800; font-size:15px;
              padding:4px 12px; border-radius:10px; margin-right:10px; }}
</style></head><body>
<div class='header'>
  <img class='logo' src='{icon_uri}'>
  <div class='htext'>
    <div class='title'>Mute <span class='amp'>&amp;</span> Saver</div>
    <div class='subtitle'>{d['subtitle']}</div>
  </div>
  <div class='hright'>
    <div class='verpill'>v{ver}</div>
    <div class='platform'>{d['platform']}</div>
  </div>
</div>
<div class='divider'></div>
<div class='grid'>{grid}</div>
</body></html>"""

def _launch(p):
    """브라우저 실행: playwright 번들 → 실패 시 시스템 Edge/Chrome 순으로 시도.
    (사내망·방화벽으로 번들 Chromium 다운로드가 막혀도 시스템 브라우저로 동작)"""
    last = None
    # 1) playwright 번들 chromium
    try:
        return p.chromium.launch()
    except Exception as e:
        last = e
    # 2) 시스템 Edge → Chrome (Windows 기본 내장 Edge = Chromium, 다운로드 불필요)
    for ch in ("msedge", "chrome"):
        try:
            b = p.chromium.launch(channel=ch)
            print(f"[make_manual] 시스템 브라우저 사용: {ch}")
            return b
        except Exception as e:
            last = e
    raise last

def main():
    from playwright.sync_api import sync_playwright
    ver = app_version()
    icon = slidey_data_uri()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = _launch(p)
        for lang in LANGS:
            html = build_html(lang, ver, icon)
            page = browser.new_page(viewport={"width": 1600, "height": 900},
                                    device_scale_factor=2)
            page.set_content(html, wait_until="networkidle")
            page.wait_for_timeout(300)
            name = "manual.png" if lang == "ko" else f"manual_{lang}.png"
            page.screenshot(path=str(OUT_DIR / name), clip={"x": 0, "y": 0, "width": 1600, "height": 900})
            page.close()
            print(f"[make_manual] {name}  (v{ver}, {lang})")
        browser.close()

if __name__ == "__main__":
    main()
