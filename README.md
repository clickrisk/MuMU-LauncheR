<div align="center">

# 🚀 MuMU LauncheR

**Stop clicking through MuMuPlayer one profile at a time.**
Launch, stop, clone, configure and organize dozens of MuMuPlayer Pro profiles from one fast, clean window.

![Version](https://img.shields.io/badge/version-3.6-0A84FF?style=for-the-badge)
![Platforms](https://img.shields.io/badge/Windows%20%7C%20macOS-supported-30D158?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52?style=for-the-badge)
![License](https://img.shields.io/badge/license-MIT-8E8E93?style=for-the-badge)

[English](README.md) · [Русский](README.ru.md)

<!-- Replace with your main screenshot -->
<img src="docs/screenshots/hero.png" alt="MuMU LauncheR main window" width="420">

</div>

---

## Why MuMU LauncheR?

If you run more than a handful of MuMuPlayer instances, you know the pain: open the manager, find the right profile, wait, repeat. **MuMU LauncheR** turns that into a single control panel built for people who run *many* profiles.

- ⚡ **Start 20 profiles in a few clicks**: tick them, press start, done.
- 🧠 **Smart launch queue**: if MuMuPlayer is closed, it starts it for you, waits until it is *fully* ready, then launches your profiles one by one with a safe delay.
- 🗂️ **Never lose track**: color notes, emoji stickers, search by name, ID or note.
- 🛠️ **Bulk config**: change resolution, DPI, CPU and RAM for **all profiles at once**.
- 🌍 **16 languages**, dark and light themes, one codebase for **Windows and macOS**.

---

## Features

### Launch and control
| | |
|---|---|
| **Multi-select launch** | Check any profiles, then start or stop all checked ones with one button |
| **Smart queue** | Auto-starts MuMuPlayer minimized, waits for full readiness, launches profiles with a 0.5 s stagger |
| **Self-healing** | If a profile doesn't come up after a cold start, the launcher re-sends the open command |
| **Real Stop** | Stop also cancels the pending launch queue, so profiles don't keep starting after you press it |
| **Close all** | One button to shut every running profile down |
| **Live status** | Running profiles are tracked in real time (polled twice a second) |

### Organize
| | |
|---|---|
| **Smart sections** | List is split into `ON`, `ALL`, `ON (SEARCH)` and `SEARCH` groups |
| **Instant search** | Find by profile name, ID **or note text** |
| **Sorting** | Name A→Z / Z→A, ID 0→9 / 9→0, plus a "running first" toggle |
| **Color notes** | Attach a note to any profile and tag it with one of 9 colors; autosaves as you type |
| **Stickers** | 18 built-in emoji stickers per profile, or add your own, reorder them, set the default |

### Manage devices
| | |
|---|---|
| **Create** | New **Tablet 2560 × 1440** or **Phone 1440 × 2560** in one click |
| **Clone / Delete** | With confirmation; running devices are shut down safely first |
| **Edit config** | Per-profile JSON editor with validation |
| **Bulk config** | Paste a config snippet once, apply it to every profile |

### Comfort
- 🌗 Dark and light themes
- 📌 Always-on-top mode
- 🌐 16 languages with built-in language search: Русский, Українська, English, Español, Deutsch, 中文, Français, Italiano, Português, Polski, Türkçe, 日本語, 한국어, العربية, हिन्दी, Nederlands
- 💾 Everything (checkmarks, notes, colors, stickers) is saved automatically and restored on next start

---

## Screenshots

<table> <tr> <td align="center"><img src="docs/screenshots/main-dark.png" width="300"><br><sub>Главное окно, тёмная тема</sub></td> <td align="center"><img src="docs/screenshots/main-light.png" width="300"><br><sub>Светлая тема</sub></td> </tr> <tr> <td align="center"><img src="docs/screenshots/notes-stickers.png" width="300"><br><sub>Цветные заметки и стикеры</sub></td> <td align="center"><img src="docs/screenshots/bulk-config.png" width="300"><br><sub>Массовый конфиг</sub></td> </tr> </table>
---

## Installation

**Requirements:** Python 3.9+ and [MuMuPlayer Pro](https://www.mumuplayer.com/) installed.

```bash
git clone https://github.com/clickrisk/MuMU-LauncheR.git
cd MuMU-LauncheR
pip install -r requirements.txt
```

### Windows

```bash
python windows/mumu_launcher_win.py
```

The launcher auto-detects `MuMuManager.exe` in the usual MuMuPlayer install folders (Program Files and other drives). If yours is somewhere unusual, point to it with an environment variable:

```bat
set MUMU_MANAGER=D:\Games\MuMuPlayer\nx_main\MuMuManager.exe
python windows\mumu_launcher_win.py
```

Settings are stored in `%APPDATA%\MuMu Launcher\config.json`.

### macOS

```bash
python3 macos/mumu_launcher.py
```

---

## Quick start

1. Launch the app. Your MuMuPlayer profiles appear automatically.
2. Tick the profiles you want and press **Start**.
3. Click a profile's sticker to add a **note**, pick a **color**, or change its **sticker**.
4. Use **⚙ Settings** to switch theme, language, or enable *Always on top*.
5. Need the same resolution on every profile? Open **Edit config of all profiles**, paste a snippet like this and apply:

```json
"resolution_mode": "custom",
"resolution_width.custom": "1280",
"resolution_height.custom": "720",
"resolution_dpi.custom": "180",
"performance_mode": "custom",
"performance_cpu.custom": "1",
"performance_mem.custom": "2"
```

> ⚠️ Running devices are shut down automatically before a config change, because MuMuPlayer only applies config to stopped profiles.

---

## Project structure

```
MuMU-LauncheR/
├── macos/       # macOS version (mumu_launcher.py)
├── windows/     # Windows version (MuMuManager.exe backend)
├── docs/screenshots/
├── requirements.txt
└── LICENSE
```

---

## Contributing

Issues, ideas and pull requests are welcome. Found a bug or want a feature? [Open an issue](../../issues).
If the launcher saves you time, a ⭐ on the repo helps a lot.

## License

Released under the [MIT License](LICENSE).

<div align="center">

Made with ❤️ by **[@clickrisk](https://github.com/clickrisk)**

</div>
