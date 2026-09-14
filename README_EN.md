**English** | [한국어](README.md)

# Mute&Saver (뮤트세이버)

A Windows desktop utility that turns idle time into a **multi-monitor screensaver with a memo board** and **automatically mutes system audio** while active.
Open-source · portable (no installer) · no network access.

---

## Features
- 🖥️ Multi-monitor screensaver — per-monitor media / memo / split modes
- 📝 Full-resolution memo editor — drag, resize, fonts, sizes, colors, opacity
- ▦ Table + 🗓 calendar templates — cell background/text colors, content preserved across months
- 🎨 Formatting ribbon · save custom templates & favorites
- 🔇 Auto-mutes system volume on screensaver entry (restores on exit)
- 🌐 Multilingual (KO / EN / ZH / JA / RU)

## Requirements
- Windows 10 / 11 (64-bit)
- No extra install needed (Python bundled)

## Install
1. Download `MuteAndSaver_vX.Y.Z_win64.zip` from [Releases](../../releases)
2. Extract and run `MuteAndSaver.exe`
3. If SmartScreen shows an "unknown publisher" warning → **More info → Run anyway**
   (Standard warning due to no code-signing certificate. The source is public.)

## Data
- Settings, memos, logs: `%LOCALAPPDATA%\MuteAndSaver\`
- **No data is sent anywhere** — everything stays local.

## Privacy
- No network communication. Only file and system-mute operations, all local.

## Build from source
```bat
python -m pip install pyinstaller pycaw comtypes pillow
pyinstaller build.spec --noconfirm
REM or all at once:
build.bat
```
Run in dev: `pythonw run.pyw`

## License
MIT — see [LICENSE](LICENSE). Third-party notices in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Screenshots
<!-- TODO: add screenshots/GIFs under docs/ and link here
![multi-monitor](docs/multimonitor.png)
![memo/table/calendar](docs/memo.png)
-->
