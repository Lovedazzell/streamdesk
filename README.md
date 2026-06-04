# StreamDesk

A configurable macro-pad controller for Windows. Listens on UDP and executes actions like launching apps, controlling media, running scripts, and adjusting volume.

---

## Quick Start

1. **First run — install everything:**
   ```
   Double-click install_and_run.bat
   ```
   This installs all Python packages and launches the app.

2. **Or run setup.py** for a guided install + desktop shortcut:
   ```
   python setup.py
   ```

---

## Files

| File | Purpose |
|---|---|
| `streamdesk.py` | Main application (GUI + UDP server) |
| `setup.py` | One-click installer + shortcut creator |
| `install_and_run.bat` | Batch installer / launcher |
| `run_hidden.vbs` | Starts app silently at login (used by Task Scheduler) |
| `streamdesk_config.json` | Your saved config (auto-created) |
| `nircmd.exe` | Volume control utility (auto-downloaded) |

---

## UDP Commands

Send UTF-8 text over UDP to `<PC_IP>:5005`:

| Command | Action |
|---|---|
| `BTN1` … `BTN16` | Trigger configured button |
| `MEDIA:PLAYPAUSE` | Play / pause |
| `MEDIA:NEXT` | Next track |
| `MEDIA:PREV` | Previous track |
| `VOL:75` | Set volume to 75% |

---

## Auto-start

Open **Settings → Auto-start** and check the box. StreamDesk registers itself in Windows Task Scheduler to run at login.

To add the firewall rule (allows UDP on port 5005):  
**Settings → Windows Firewall → Add Firewall Rule**  
*(requires running as Administrator)*

---

## Action Types

- **Launch Application** — path to any .exe or shell command
- **Open Folder in VS Code** — opens a folder in VS Code
- **Run CMD Script / BAT file** — runs a .bat or .cmd in a new console
- **Media: Play/Pause / Next / Prev** — system media keys
- **YouTube: Forward/Rewind 10s** — sends J/L keys when YouTube is focused
- **Set Volume** — 0–100 (requires nircmd.exe)
- **Custom Command** — any shell command

---

## Requirements

- Python 3.9+
- Windows 10/11
- Packages: `pywin32`, `pystray`, `Pillow`, `keyboard`, `psutil`, `requests`
  (all installed automatically)
