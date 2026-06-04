"""
StreamDesk — ESP32 macro-pad controller for Windows.
  python streamdesk.py          -> open GUI
  python streamdesk.py --tray   -> start minimised to tray
"""

import sys, os, json, socket, subprocess, threading, time
import argparse, ctypes, ctypes.wintypes, traceback, logging, shutil
import zipfile, io

# ── Logging ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE   = os.path.join(SCRIPT_DIR, "streamdesk.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("StreamDesk")
log.info("=== StreamDesk starting ===")

# ── Auto-install missing packages ────────────────────────────────────────────
def _ensure(pkg, mod=None):
    try:
        __import__(mod or pkg)
    except ImportError:
        log.info(f"pip install {pkg} ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", pkg]
        )

for _pkg, _mod in [
    ("pywin32",  "win32gui"),
    ("pystray",  "pystray"),
    ("Pillow",   "PIL"),
    ("psutil",   "psutil"),
    ("requests", "requests"),
]:
    _ensure(_pkg, _mod)

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser
import pystray
from PIL import Image, ImageDraw
import psutil, win32gui, win32process
import requests

# ─────────────────────────────────────────────────────────────────────────────
#  KEY SENDING — pure ctypes SendInput, NO admin required
# ─────────────────────────────────────────────────────────────────────────────
#  Reference: https://docs.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput

KEYEVENTF_KEYDOWN  = 0x0000
KEYEVENTF_KEYUP    = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
INPUT_KEYBOARD     = 1

# Virtual-key codes
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_J = 0x4A
VK_L = 0x4C

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.wintypes.WORD),
        ("wScan",       ctypes.wintypes.WORD),
        ("dwFlags",     ctypes.wintypes.DWORD),
        ("time",        ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 28)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.wintypes.DWORD), ("_u", _INPUT_UNION)]

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_SendInput = _user32.SendInput

def _press_vk(vk: int):
    """Press and release a virtual key via SendInput (no admin needed)."""
    # log.info(f">>> _press_vk called: vk=0x{vk:02X}")
    flags = KEYEVENTF_EXTENDEDKEY if vk in (
        VK_MEDIA_PLAY_PAUSE, VK_MEDIA_NEXT_TRACK, VK_MEDIA_PREV_TRACK
    ) else 0
    # log.info(f">>> _press_vk flags=0x{flags:02X} extended={bool(flags)}")
    inp_down = _INPUT(
        type=INPUT_KEYBOARD,
        _u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=vk, wScan=0,
                                        dwFlags=flags | KEYEVENTF_KEYDOWN,
                                        time=0, dwExtraInfo=None))
    )
    inp_up = _INPUT(
        type=INPUT_KEYBOARD,
        _u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=vk, wScan=0,
                                        dwFlags=flags | KEYEVENTF_KEYUP,
                                        time=0, dwExtraInfo=None))
    )
    arr = (_INPUT * 2)(inp_down, inp_up)
    sizeof_input = ctypes.sizeof(_INPUT)
    # log.info(f">>> SendInput calling: count=2, sizeof(_INPUT)={sizeof_input}")
    sent = _SendInput(2, arr, sizeof_input)
    # log.info(f">>> SendInput returned: {sent} (expected 2)  vk=0x{vk:02X}")
    if sent != 2:
        err = ctypes.get_last_error()
        log.error(f">>> SendInput FAILED: sent={sent} GetLastError={err} vk=0x{vk:02X}")
    else:
        log.info(f">>> SendInput SUCCESS vk=0x{vk:02X}")

def send_media_playpause():  _press_vk(VK_MEDIA_PLAY_PAUSE)
def send_media_next():       _press_vk(VK_MEDIA_NEXT_TRACK)
def send_media_prev():       _press_vk(VK_MEDIA_PREV_TRACK)
def send_youtube_forward():  _press_vk(VK_L)
def send_youtube_rewind():   _press_vk(VK_J)

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS / DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────

APP_NAME    = "StreamDesk"
VERSION     = "1.1.0"
CONFIG_FILE = os.path.join(SCRIPT_DIR, "streamdesk_config.json")
NIRCMD      = os.path.join(SCRIPT_DIR, "nircmd.exe")
TASK_NAME   = "StreamDesk"

BROWSER_EXE = {"chrome.exe","msedge.exe","firefox.exe",
               "brave.exe","opera.exe","vivaldi.exe"}

ACTION_TYPES = [
    "Launch Application",
    "Open Folder in VS Code",
    "Run CMD Script / BAT file",
    "Media: Play/Pause",
    "Media: Next Track",
    "Media: Previous Track",
    "YouTube: Forward 10s",
    "YouTube: Rewind 10s",
    "Set Volume",
    "Custom Command",
    "Do Nothing",
]

NO_VALUE_TYPES = {
    "Media: Play/Pause","Media: Next Track","Media: Previous Track",
    "YouTube: Forward 10s","YouTube: Rewind 10s","Do Nothing",
}

ACTION_HINTS = {
    "Launch Application":        "Full path to .exe, or any shell command.",
    "Open Folder in VS Code":    "Full folder path — opens as VS Code workspace.",
    "Run CMD Script / BAT file": "Full path to a .bat/.cmd — runs in new console.",
    "Set Volume":                "0-100  (requires nircmd.exe).",
    "Custom Command":            "Any shell command.",
    "YouTube: Forward 10s":      "Sends L key — YouTube must be the active window.",
    "YouTube: Rewind 10s":       "Sends J key — YouTube must be the active window.",
    "Media: Play/Pause":         "System-wide media key — no admin needed.",
    "Media: Next Track":         "System-wide media key — no admin needed.",
    "Media: Previous Track":     "System-wide media key — no admin needed.",
    "Do Nothing":                "Button press is ignored.",
}

ACTION_EXAMPLES = {
    "Launch Application":
        'e.g.  "C:\\Program Files\\Notepad++\\notepad++.exe"\n'
        'or    chrome.exe',
    "Open Folder in VS Code":
        'e.g.  D:\\my_project',
    "Run CMD Script / BAT file":
        'e.g.  C:\\Users\\me\\Desktop\\scripts\\dev.bat',
    "Set Volume":
        'e.g.  50  (50%)   |   0 = mute   |   100 = max',
    "Custom Command":
        'e.g.  start chrome https://github.com',
}

DEFAULT_CONFIG = {
    "udp_port":       5005,
    "cooldown_ms":    200,
    "start_minimized": False,
    "buttons": {
        f"BTN{i}": {
            "label":        f"Button {i}",
            "action_type":  "Do Nothing",
            "action_value": "",
            "color":        "#2a2a3e",
        }
        for i in range(1, 17)
    },
    "special": {
        "MEDIA:PLAYPAUSE": {"action_type": "Media: Play/Pause",     "action_value": ""},
        "MEDIA:NEXT":      {"action_type": "Media: Next Track",     "action_value": ""},
        "MEDIA:PREV":      {"action_type": "Media: Previous Track", "action_value": ""},
    },
}

# ─────────────────────────────────────────────────────────────────────────────
#  THEME
# ─────────────────────────────────────────────────────────────────────────────

DARK_BG   = "#0f0f1a"
PANEL_BG  = "#16162a"
CARD_BG   = "#1e1e35"
ACCENT    = "#50c88c"
ACCENT2   = "#7b6cff"
TEXT_MAIN = "#e8e8f0"
TEXT_SUB  = "#888899"
BORDER    = "#2a2a4a"

FONT_SUB   = ("Segoe UI", 10)
FONT_LABEL = ("Segoe UI", 9)
FONT_BTN   = ("Segoe UI", 9, "bold")
FONT_MONO  = ("Consolas", 9)

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG I/O
# ─────────────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Merge in any missing top-level keys from defaults
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except Exception as e:
            log.error(f"Config load error: {e}")
    return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        log.info("Config saved.")
    except Exception as e:
        log.error(f"Config save error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  WINDOWS HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def relaunch_as_admin():
    script  = os.path.abspath(__file__)
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    params = " ".join([f'"{script}"'] + sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", pythonw, params, None, 1)
    sys.exit(0)

def is_youtube_active() -> bool:
    try:
        hwnd  = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd).lower()
        if "youtube" not in title:
            return False
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        return proc.name().lower() in BROWSER_EXE
    except Exception:
        return False

def find_vscode() -> str:
    for name in ("code", "code.cmd"):
        found = shutil.which(name)
        if found:
            return found
    for c in [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
    ]:
        if os.path.exists(c):
            return c
    return ""

def set_volume(level: int):
    try:
        if os.path.exists(NIRCMD):
            vol = int(level / 100 * 65535)
            subprocess.Popen(
                [NIRCMD, "setsysvolume", str(vol)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            # log.info(f"Volume -> {level}%")
        else:
            log.error(f"nircmd.exe not found at {NIRCMD}. "
                      "Go to Settings → Volume → Download.")
    except Exception as e:
        log.error(f"set_volume: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  TASK SCHEDULER / FIREWALL
# ─────────────────────────────────────────────────────────────────────────────

def is_autostart_enabled() -> bool:
    r = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME],
        capture_output=True, text=True,
    )
    return r.returncode == 0

def enable_autostart():
    vbs = os.path.join(SCRIPT_DIR, "run_hidden.vbs")
    cmd = (
        f'$a=New-ScheduledTaskAction -Execute "wscript.exe" -Argument \'"{vbs}"\';'
        f'$t=New-ScheduledTaskTrigger -AtLogon;$t.Delay="PT30S";'
        f'$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries '
        f'-DontStopIfGoingOnBatteries -ExecutionTimeLimit 0;'
        f'Register-ScheduledTask -TaskName "{TASK_NAME}" -Action $a '
        f'-Trigger $t -Settings $s -RunLevel Highest -Force'
    )
    r = subprocess.run(["powershell", "-Command", cmd], capture_output=True, text=True)
    log.info(f"enable_autostart rc={r.returncode} {r.stderr.strip()}")
    return r.returncode == 0

def disable_autostart():
    r = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True,
    )
    return r.returncode == 0

def add_firewall_rule(port: int = 5005):
    cmd = (
        f'New-NetFirewallRule -DisplayName "StreamDesk UDP {port}" '
        f'-Direction Inbound -Protocol UDP -LocalPort {port} '
        f'-Action Allow -ErrorAction SilentlyContinue'
    )
    subprocess.run(["powershell", "-Command", cmd], capture_output=True)

def download_nircmd(status_cb=None):
    if os.path.exists(NIRCMD):
        return True
    for url in [
        "https://www.nirsoft.net/utils/nircmd-x64.zip",
        "https://www.nirsoft.net/utils/nircmd.zip",
    ]:
        try:
            if status_cb:
                status_cb(f"Downloading nircmd …")
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    for name in z.namelist():
                        if name.lower() == "nircmd.exe":
                            z.extract(name, SCRIPT_DIR)
                            log.info("nircmd.exe downloaded OK.")
                            return True
        except Exception as e:
            log.warning(f"nircmd download failed ({url}): {e}")
    return False

# ─────────────────────────────────────────────────────────────────────────────
#  ACTION EXECUTOR
# ─────────────────────────────────────────────────────────────────────────────

_last_ts: dict  = {}
_cfg_ref: list  = [{}]   # mutable box so UDP thread always sees latest config

def execute_action(cfg: dict, command: str):
    """Entry point — called from UDP thread with the raw ESP32 command string."""
    log.info(f">>> EXECUTE: {command!r}")

    cooldown = cfg.get("cooldown_ms", 200) / 1000
    now = time.time()
    if command in _last_ts and now - _last_ts[command] < cooldown:
        log.warning(f">>> COOLDOWN SKIP {command!r} ({now - _last_ts[command]:.3f}s ago, limit={cooldown}s)")
        return
    _last_ts[command] = now

    # VOL:xx
    if command.startswith("VOL:"):
        # log.info(f">>> VOL command detected")
        try:
            set_volume(int(command.split(":", 1)[1]))
        except ValueError:
            log.error(f">>> Bad VOL value: {command!r}")
        return

    # Special media commands
    spec = cfg.get("special", {}).get(command)
    # log.info(f">>> special lookup [{command!r}] = {spec}")
    if spec:
        # log.info(f">>> dispatching SPECIAL: {spec}")
        _run_action(spec["action_type"], spec.get("action_value", ""))
        return

    # Numbered buttons
    buttons = cfg.get("buttons", {})
    btn = buttons.get(command)
    log.info(f">>> button lookup [{command!r}] = {btn}")
    if btn:
        # log.info(f">>> dispatching BUTTON type={btn['action_type']!r}")
        _run_action(btn["action_type"], btn.get("action_value", ""))
        return

    # log.error(f">>> UNRECOGNISED COMMAND: {command!r}")
    # log.error(f">>> Known buttons : {sorted(buttons.keys())}")
    # log.error(f">>> Known specials: {sorted(cfg.get('special',{}).keys())}")

def _run_action(atype: str, aval: str):
    # log.info(f">>> _run_action: type={atype!r}  value={aval!r}")
    try:
        if atype == "Do Nothing":
            pass

        elif atype == "Launch Application":
            if aval:
                subprocess.Popen(aval, shell=True)
            else:
                log.warning("Launch Application: no path configured")

        elif atype == "Open Folder in VS Code":
            if aval:
                code = find_vscode()
                if code:
                    subprocess.Popen([code, aval], shell=False)
                else:
                    log.error("VS Code not found")
            else:
                log.warning("VS Code action: no folder configured")

        elif atype == "Run CMD Script / BAT file":
            if aval:
                subprocess.Popen(
                    ["cmd", "/k", aval],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                log.warning("Run CMD: no script configured")

        elif atype == "Media: Play/Pause":
            # log.info(">>> Calling send_media_playpause() via SendInput ...")
            send_media_playpause()
            # log.info(">>> send_media_playpause() returned")

        elif atype == "Media: Next Track":
            # log.info(">>> Calling send_media_next() via SendInput ...")
            send_media_next()
            # log.info(">>> send_media_next() returned")
# 
        elif atype == "Media: Previous Track":
            # log.info(">>> Calling send_media_prev() via SendInput ...")
            send_media_prev()
            # log.info(">>> send_media_prev() returned")

        elif atype == "YouTube: Forward 10s":
            yt = is_youtube_active()
            # log.info(f">>> YouTube active = {yt}")
            if yt:
                # log.info(">>> Calling send_youtube_forward() ...")
                send_youtube_forward()
                # log.info(">>> send_youtube_forward() returned")
            else:
                log.warning(">>> YouTube Forward skipped — YouTube/browser not in foreground")

        elif atype == "YouTube: Rewind 10s":
            yt = is_youtube_active()
            # log.info(f">>> YouTube active = {yt}")
            if yt:
                # log.info(">>> Calling send_youtube_rewind() ...")
                send_youtube_rewind()
                # log.info(">>> send_youtube_rewind() /returned")
            else:
                log.warning(">>> YouTube Rewind skipped — YouTube/browser not in foreground")

        elif atype == "Set Volume":
            try:
                set_volume(int(aval))
            except ValueError:
                log.error(f"Set Volume: bad value {aval!r}")

        elif atype == "Custom Command":
            if aval:
                subprocess.Popen(aval, shell=True)
            else:
                log.warning("Custom Command: empty")

        else:
            log.warning(f"Unknown action type: {atype!r}")

    except Exception as e:
        log.error(f"_run_action crashed: {e}\n{traceback.format_exc()}")

# ─────────────────────────────────────────────────────────────────────────────
#  UDP SERVER
# ─────────────────────────────────────────────────────────────────────────────

_udp_running = False
_udp_thread  = None

def start_udp(cfg: dict):
    global _udp_running, _udp_thread
    _cfg_ref[0] = cfg

    log.info("=== start_udp() called ===")
    log.info(f"=== _udp_running={_udp_running} ===")

    if _udp_running:
        log.warning("=== UDP already running — skipping start ===")
        return
    
    _udp_running = True
    log.info("=== _udp_running set to True, starting thread ... ===")

    def _loop():
        log.info("=== UDP thread _loop() ENTERED ===")
        loop_count = 0
        while _udp_running:
            loop_count += 1
            sock = None
            port = _cfg_ref[0].get("udp_port", 5005)
            log.info(f"=== UDP outer loop #{loop_count}: attempting bind on 0.0.0.0:{port} ===")
            try:
                log.info("=== creating socket ===")
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                log.info("=== socket created OK ===")

                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                log.info("=== SO_REUSEADDR set ===")

                sock.bind(("0.0.0.0", port))
                log.info(f"=== BOUND to 0.0.0.0:{port} — now listening for ESP32 packets ===")

                sock.settimeout(1.0)

                recv_count = 0
                timeout_count = 0
                while _udp_running:
                    try:
                        raw, addr = sock.recvfrom(256)
                        recv_count += 1
                        # log.info(f"=== PACKET #{recv_count} from {addr[0]}:{addr[1]} ===")
                        # log.info(f"=== RAW bytes: {raw!r} ===")
                        line = raw.decode("utf-8", errors="ignore").strip()
                        # log.info(f"=== DECODED: {line!r}  len={len(line)} ===")
                        if line:
                            # log.info(f"=== passing to execute_action: {line!r} ===")
                            execute_action(_cfg_ref[0], line)
                            # log.info(f"=== execute_action returned for: {line!r} ===")
                        else:
                            log.warning("=== packet decoded to empty string — ignoring ===")
                    except socket.timeout:
                        timeout_count += 1
                        # if timeout_count % 10 == 0:
                            # log.info(f"=== UDP alive — {timeout_count} timeouts, {recv_count} packets received so far ===")
                        continue
                    except Exception as e:
                        log.error(f"=== UDP recv error: {e} ===")
                        log.error(traceback.format_exc())

            except OSError as e:
                log.error(f"=== OSError binding to port {port}: {e} ===")
                log.error(f"=== errno={e.errno} — common causes: port already in use, firewall, or antivirus ===")
                log.error(traceback.format_exc())
                log.info("=== retrying in 5s ... ===")
                time.sleep(5)
            except Exception as e:
                log.error(f"=== UNEXPECTED error in UDP loop: {e} ===")
                log.error(traceback.format_exc())
                time.sleep(5)
            finally:
                if sock:
                    log.info("=== closing socket ===")
                    try: sock.close()
                    except: pass

        log.info("=== UDP _loop() EXITED (_udp_running is False) ===")

    _udp_thread = threading.Thread(target=_loop, daemon=True, name="UDP")
    _udp_thread.start()
    log.info(f"=== UDP thread started: {_udp_thread} ===")

    # Verify thread is alive after a short delay
    def _check_thread():
        time.sleep(2)
        alive = _udp_thread.is_alive()
        log.info(f"=== UDP thread alive check (2s after start): {alive} ===")
        if not alive:
            log.error("=== UDP THREAD DIED IMMEDIATELY — check errors above ===")

    threading.Thread(target=_check_thread, daemon=True, name="UDP-checker").start()

def stop_udp():
    global _udp_running
    _udp_running = False

def update_cfg(cfg: dict):
    _cfg_ref[0] = cfg

# ─────────────────────────────────────────────────────────────────────────────
#  TRAY
# ─────────────────────────────────────────────────────────────────────────────

_tray_icon = None

def _make_tray_img() -> Image.Image:
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, fill=(24, 24, 40))
    draw.rounded_rectangle([4, 4, 60, 60], radius=14, outline=(80, 200, 140), width=3)
    draw.ellipse([22, 22, 42, 42], fill=(80, 200, 140))
    return img

def start_tray(show_cb, quit_cb):
    global _tray_icon
    _tray_icon = pystray.Icon(
        APP_NAME, _make_tray_img(), f"{APP_NAME} {VERSION}",
        menu=pystray.Menu(
            pystray.MenuItem("Open StreamDesk", lambda *_: show_cb(), default=True),
            pystray.MenuItem("Quit",            lambda *_: quit_cb()),
        ),
    )
    threading.Thread(target=_tray_icon.run, daemon=True, name="tray").start()

def stop_tray():
    if _tray_icon:
        try: _tray_icon.stop()
        except: pass

# ─────────────────────────────────────────────────────────────────────────────
#  BUTTON EDITOR DIALOG
# ─────────────────────────────────────────────────────────────────────────────

class ButtonEditor(tk.Toplevel):
    def __init__(self, parent, btn_id, btn_cfg, on_save):
        super().__init__(parent)
        self.title(f"Edit {btn_id}")
        self.configure(bg=DARK_BG)
        self.resizable(True, False)
        self.grab_set()
        self._btn_id  = btn_id
        self._btn_cfg = dict(btn_cfg)
        self._on_save = on_save
        self._build()
        self.geometry("660x440")
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width()  // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2
        self.geometry(f"+{px - self.winfo_width()//2}+{py - self.winfo_height()//2}")

    def _build(self):
        P = dict(padx=22, pady=7)
        tk.Label(self, text=f"Configure  {self._btn_id}",
                 bg=DARK_BG, fg=ACCENT,
                 font=("Segoe UI", 14, "bold")).pack(**P, anchor="w")

        # Label
        r = tk.Frame(self, bg=DARK_BG); r.pack(fill="x", **P)
        tk.Label(r, text="Button Label:", bg=DARK_BG, fg=TEXT_SUB,
                 font=FONT_LABEL, width=16, anchor="w").pack(side="left")
        self._label_var = tk.StringVar(
            value=self._btn_cfg.get("label", self._btn_id))
        tk.Entry(r, textvariable=self._label_var, bg=CARD_BG, fg=TEXT_MAIN,
                 insertbackground=TEXT_MAIN, relief="flat",
                 font=FONT_MONO).pack(side="left", fill="x", expand=True, ipady=5)

        # Action type
        r2 = tk.Frame(self, bg=DARK_BG); r2.pack(fill="x", **P)
        tk.Label(r2, text="Action Type:", bg=DARK_BG, fg=TEXT_SUB,
                 font=FONT_LABEL, width=16, anchor="w").pack(side="left")
        self._atype_var = tk.StringVar(
            value=self._btn_cfg.get("action_type", "Do Nothing"))
        cb = ttk.Combobox(r2, textvariable=self._atype_var,
                          values=ACTION_TYPES, state="readonly", width=42)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", self._refresh)

        # Hint
        self._hint_var = tk.StringVar()
        tk.Label(self, textvariable=self._hint_var,
                 bg=DARK_BG, fg=ACCENT2,
                 font=("Segoe UI", 9, "italic"),
                 wraplength=610, justify="left").pack(fill="x", padx=22, pady=(2, 0))

        # Value row
        self._val_frame = tk.Frame(self, bg=DARK_BG)
        self._val_frame.pack(fill="x", padx=22, pady=(6, 0))
        tk.Label(self._val_frame, text="Path / Value:",
                 bg=DARK_BG, fg=TEXT_SUB,
                 font=FONT_LABEL, width=16, anchor="w").grid(row=0, column=0, sticky="w")
        self._aval_var = tk.StringVar(
            value=self._btn_cfg.get("action_value", ""))
        tk.Entry(self._val_frame, textvariable=self._aval_var,
                 bg=CARD_BG, fg=TEXT_MAIN,
                 insertbackground=TEXT_MAIN, relief="flat",
                 font=FONT_MONO).grid(row=0, column=1, sticky="ew", ipady=5, padx=(0, 8))
        tk.Button(self._val_frame, text=" Browse… ", bg=ACCENT2, fg=TEXT_MAIN,
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  command=self._browse).grid(row=0, column=2)
        self._val_frame.columnconfigure(1, weight=1)

        # Example
        self._ex_var = tk.StringVar()
        tk.Label(self, textvariable=self._ex_var,
                 bg=DARK_BG, fg=TEXT_SUB,
                 font=("Consolas", 8),
                 wraplength=610, justify="left").pack(fill="x", padx=22, pady=(4, 0))

        self._refresh()

        # Color picker
        r3 = tk.Frame(self, bg=DARK_BG); r3.pack(fill="x", padx=22, pady=10)
        tk.Label(r3, text="Button Color:", bg=DARK_BG, fg=TEXT_SUB,
                 font=FONT_LABEL, width=16, anchor="w").pack(side="left")
        self._color = self._btn_cfg.get("color", "#2a2a3e")
        self._cprev = tk.Label(r3, bg=self._color, width=6, height=1)
        self._cprev.pack(side="left", padx=(0, 10))
        tk.Button(r3, text="Pick Color", bg=CARD_BG, fg=ACCENT,
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  command=self._pick_color).pack(side="left")

        # Save / Cancel
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(12, 0))
        btns = tk.Frame(self, bg=DARK_BG)
        btns.pack(side="bottom", fill="x", padx=22, pady=12)
        tk.Button(btns, text="Cancel", bg=CARD_BG, fg=TEXT_SUB,
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  padx=16, pady=6, command=self.destroy).pack(side="right", padx=(8, 0))
        tk.Button(btns, text="  Save  ", bg=ACCENT, fg="#0f0f1a",
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  padx=16, pady=6, command=self._save).pack(side="right")

    def _refresh(self, *_):
        atype = self._atype_var.get()
        self._hint_var.set(ACTION_HINTS.get(atype, ""))
        self._ex_var.set(ACTION_EXAMPLES.get(atype, ""))
        if atype in NO_VALUE_TYPES:
            self._val_frame.pack_forget()
        else:
            self._val_frame.pack(fill="x", padx=22, pady=(6, 0))

    def _browse(self):
        atype = self._atype_var.get()
        if "Folder" in atype:
            p = filedialog.askdirectory(title="Select Folder")
        elif "BAT" in atype or "Script" in atype or "CMD" in atype:
            p = filedialog.askopenfilename(
                title="Select Script",
                filetypes=[("Batch scripts","*.bat *.cmd"),("All","*.*")])
        else:
            p = filedialog.askopenfilename(
                title="Select File",
                filetypes=[("Executables","*.exe *.cmd *.bat"),("All","*.*")])
        if p:
            self._aval_var.set(p)

    def _pick_color(self):
        c = colorchooser.askcolor(color=self._color, title="Button Color")
        if c and c[1]:
            self._color = c[1]
            self._cprev.config(bg=self._color)

    def _save(self):
        self._btn_cfg["label"]        = self._label_var.get().strip() or self._btn_id
        self._btn_cfg["action_type"]  = self._atype_var.get()
        self._btn_cfg["action_value"] = self._aval_var.get().strip()
        self._btn_cfg["color"]        = self._color
        self._on_save(self._btn_id, self._btn_cfg)
        self.destroy()

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN APP
# ─────────────────────────────────────────────────────────────────────────────

class StreamDeskApp:
    def __init__(self, root: tk.Tk, tray_mode: bool = False):
        self.root = root
        self.cfg  = load_config()

        root.title(f"{APP_NAME}  v{VERSION}")
        root.configure(bg=DARK_BG)
        root.minsize(920, 660)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=CARD_BG, background=CARD_BG,
                        foreground=TEXT_MAIN, selectbackground=CARD_BG,
                        selectforeground=TEXT_MAIN, borderwidth=0)
        style.configure("TNotebook",     background=DARK_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_BG, foreground=TEXT_SUB,
                        padding=[14, 6], font=FONT_SUB)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD_BG)],
                  foreground=[("selected", ACCENT)])

        self._build_ui()
        start_udp(self.cfg)
        start_tray(self._show, self._quit)

        if tray_mode or self.cfg.get("start_minimized", False):
            root.withdraw()

        if not os.path.exists(NIRCMD):
            threading.Thread(target=self._bg_dl_nircmd, daemon=True).start()

        log.info(f"Admin: {is_admin()}  |  Python {sys.version.split()[0]}")
        self._set_status(f"Listening on UDP port {self.cfg.get('udp_port',5005)}")

    # ── background tasks ──────────────────────────────────────────────────────

    def _bg_dl_nircmd(self):
        ok = download_nircmd(self._set_status)
        self._set_status("nircmd.exe ready ✓" if ok else "nircmd.exe download failed")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=PANEL_BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text=APP_NAME, bg=PANEL_BG, fg=ACCENT,
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=20, pady=10)
        tk.Label(hdr, text=f"v{VERSION}", bg=PANEL_BG, fg=TEXT_SUB,
                 font=FONT_LABEL).pack(side="left")

        # Admin badge
        if is_admin():
            tk.Label(hdr, text="ADMIN", bg=PANEL_BG, fg=ACCENT,
                     font=FONT_BTN).pack(side="left", padx=16)
        else:
            tk.Label(hdr, text="NOT ADMIN", bg=PANEL_BG, fg="#ff8866",
                     font=FONT_BTN).pack(side="left", padx=4)
            tk.Label(hdr, text="(only needed for volume/nircmd)",
                     bg=PANEL_BG, fg=TEXT_SUB, font=FONT_LABEL).pack(side="left")

        self._status_var = tk.StringVar()
        tk.Label(hdr, textvariable=self._status_var,
                 bg=PANEL_BG, fg=ACCENT, font=FONT_LABEL).pack(side="right", padx=20)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)
        self._build_buttons_tab(nb)
        self._build_settings_tab(nb)
        self._build_log_tab(nb)
        self._build_about_tab(nb)

    # ── Buttons tab ───────────────────────────────────────────────────────────

    def _build_buttons_tab(self, nb):
        frame = tk.Frame(nb, bg=DARK_BG)
        nb.add(frame, text="  Buttons  ")

        tb = tk.Frame(frame, bg=PANEL_BG, pady=6)
        tb.pack(fill="x")
        tk.Label(tb, text="Double-click a card to configure it",
                 bg=PANEL_BG, fg=TEXT_SUB, font=FONT_LABEL).pack(side="left", padx=16)
        tk.Button(tb, text="  Save All  ", bg=ACCENT, fg="#0f0f1a",
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  padx=12, pady=4, command=self._save_all).pack(side="right", padx=12)

        self._grid_frame = tk.Frame(frame, bg=DARK_BG)
        self._grid_frame.pack(fill="both", expand=True, padx=16, pady=16)
        self._btn_widgets: dict = {}
        self._rebuild_grid()

    def _rebuild_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._btn_widgets.clear()
        buttons = self.cfg.get("buttons", {})
        ids = sorted(buttons.keys(),
                     key=lambda x: int(x[3:]) if x[3:].isdigit() else 999)
        cols = 4
        for idx, bid in enumerate(ids):
            row, col = divmod(idx, cols)
            card = self._make_card(self._grid_frame, bid, buttons[bid])
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            self._btn_widgets[bid] = card
        for c in range(cols):
            self._grid_frame.columnconfigure(c, weight=1)

    def _make_card(self, parent, bid, bcfg):
        color = bcfg.get("color", "#2a2a3e")
        atype = bcfg.get("action_type", "Do Nothing")
        label = bcfg.get("label", bid)
        card  = tk.Frame(parent, bg=CARD_BG, relief="flat",
                         highlightbackground=BORDER, highlightthickness=1,
                         cursor="hand2")
        tk.Frame(card, bg=color, height=4).pack(fill="x")
        inner = tk.Frame(card, bg=CARD_BG, padx=10, pady=8)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=bid, bg=CARD_BG, fg=TEXT_SUB,
                 font=("Segoe UI", 8)).pack(anchor="w")
        lbl = tk.Label(inner, text=label, bg=CARD_BG, fg=TEXT_MAIN,
                       font=("Segoe UI", 10, "bold"),
                       wraplength=160, justify="left")
        lbl.pack(anchor="w")
        tk.Label(inner, text=atype, bg=CARD_BG,
                 fg=ACCENT if atype != "Do Nothing" else TEXT_SUB,
                 font=FONT_LABEL, wraplength=160, justify="left").pack(anchor="w")
        for w in [card, inner, lbl] + list(card.winfo_children()):
            w.bind("<Double-Button-1>", lambda e, b=bid: self._edit_btn(b))
            w.bind("<Enter>",  lambda e, c=card: c.config(highlightbackground=ACCENT))
            w.bind("<Leave>",  lambda e, c=card: c.config(highlightbackground=BORDER))
        return card

    def _edit_btn(self, bid):
        bcfg = self.cfg["buttons"].get(bid, {})
        ButtonEditor(self.root, bid, bcfg, self._on_btn_saved)

    def _on_btn_saved(self, bid, new_cfg):
        self.cfg["buttons"][bid] = new_cfg
        update_cfg(self.cfg)
        save_config(self.cfg)
        self._rebuild_grid()
        self._set_status(f"Saved {bid}")

    def _save_all(self):
        save_config(self.cfg)
        update_cfg(self.cfg)
        self._set_status("All saved")

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self, nb):
        frame = tk.Frame(nb, bg=DARK_BG)
        nb.add(frame, text="  Settings  ")
        wrap = tk.Frame(frame, bg=DARK_BG)
        wrap.pack(fill="both", expand=True, padx=32, pady=24)

        def sec(t):
            tk.Label(wrap, text=t, bg=DARK_BG, fg=ACCENT,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(18, 4))
            tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x", pady=(0, 10))

        def row(label, factory):
            r = tk.Frame(wrap, bg=DARK_BG); r.pack(fill="x", pady=4)
            tk.Label(r, text=label, bg=DARK_BG, fg=TEXT_MAIN,
                     font=FONT_SUB, width=30, anchor="w").pack(side="left")
            factory(r)

        # Admin
        sec("Admin / Permissions")
        def _admin_row(r):
            if is_admin():
                tk.Label(r, text="Running as Administrator  ✓",
                         bg=DARK_BG, fg=ACCENT, font=FONT_BTN).pack(side="left")
            else:
                tk.Label(r, text="Media keys & volume work WITHOUT admin  ✓",
                         bg=DARK_BG, fg=ACCENT, font=FONT_BTN).pack(side="left", padx=(0,12))
                tk.Button(r, text="Restart as Admin (only needed for nircmd volume)",
                          bg=CARD_BG, fg=TEXT_SUB, relief="flat",
                          font=FONT_BTN, cursor="hand2", pady=4, padx=10,
                          command=relaunch_as_admin).pack(side="left")
        row("Administrator", _admin_row)

        # Network
        sec("Network")
        self._port_var = tk.IntVar(value=self.cfg.get("udp_port", 5005))
        def _port_row(r):
            tk.Entry(r, textvariable=self._port_var, width=8,
                     bg=CARD_BG, fg=TEXT_MAIN,
                     insertbackground=TEXT_MAIN,
                     relief="flat", font=FONT_MONO).pack(side="left", ipady=4, padx=(0,8))
            tk.Label(r, text="(restart required for port changes)",
                     bg=DARK_BG, fg=TEXT_SUB, font=FONT_LABEL).pack(side="left")
        row("UDP Port", _port_row)
        def _fw_row(r):
            tk.Button(r, text="Add Firewall Rule (needs Admin)",
                      bg=CARD_BG, fg=ACCENT, relief="flat",
                      font=FONT_BTN, cursor="hand2", pady=4, padx=10,
                      command=self._add_firewall).pack(side="left")
        row("Windows Firewall", _fw_row)

        # Startup
        sec("Startup")
        self._autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        def _auto_row(r):
            tk.Checkbutton(r, variable=self._autostart_var,
                           bg=DARK_BG, fg=TEXT_MAIN,
                           selectcolor=DARK_BG, activebackground=DARK_BG,
                           font=FONT_SUB,
                           text="Start with Windows  (30s delay so desktop is ready)",
                           command=self._toggle_autostart).pack(side="left")
        row("Auto-start", _auto_row)
        self._min_var = tk.BooleanVar(value=self.cfg.get("start_minimized", False))
        def _min_row(r):
            tk.Checkbutton(r, variable=self._min_var,
                           bg=DARK_BG, fg=TEXT_MAIN,
                           selectcolor=DARK_BG, activebackground=DARK_BG,
                           font=FONT_SUB,
                           text="Start minimised to tray").pack(side="left")
        row("Start Minimised", _min_row)

        # Behaviour
        sec("Behaviour")
        self._cd_var = tk.IntVar(value=self.cfg.get("cooldown_ms", 200))
        def _cd_row(r):
            tk.Scale(r, variable=self._cd_var, from_=50, to=1000,
                     orient="horizontal", length=200,
                     bg=DARK_BG, fg=TEXT_MAIN,
                     highlightthickness=0, troughcolor=CARD_BG,
                     activebackground=ACCENT, sliderrelief="flat").pack(side="left")
            tk.Label(r, text="ms debounce",
                     bg=DARK_BG, fg=TEXT_SUB,
                     font=FONT_LABEL).pack(side="left", padx=8)
        row("Cooldown", _cd_row)

        # Volume
        sec("Volume (nircmd.exe)")
        def _nc_row(r):
            found  = os.path.exists(NIRCMD)
            status = "Found  ✓" if found else "Not found"
            color  = ACCENT  if found else "#ff6666"
            tk.Label(r, text=status, bg=DARK_BG, fg=color,
                     font=FONT_BTN).pack(side="left", padx=(0,12))
            tk.Button(r, text="Download", bg=CARD_BG, fg=ACCENT,
                      relief="flat", font=FONT_BTN, cursor="hand2",
                      pady=4, padx=10,
                      command=lambda: threading.Thread(
                          target=self._bg_dl_nircmd, daemon=True).start()
                      ).pack(side="left")
        row("nircmd.exe", _nc_row)

        tk.Frame(wrap, bg=DARK_BG, height=16).pack()
        tk.Button(wrap, text="  Save Settings  ", bg=ACCENT, fg="#0f0f1a",
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  padx=16, pady=8,
                  command=self._save_settings).pack(anchor="w")

    def _toggle_autostart(self):
        if self._autostart_var.get():
            ok = enable_autostart()
            self._set_status("Auto-start enabled" if ok else "FAILED — run as Admin")
            if not ok:
                self._autostart_var.set(False)
        else:
            ok = disable_autostart()
            self._set_status("Auto-start disabled" if ok else "Failed to remove task")

    def _add_firewall(self):
        if not is_admin():
            messagebox.showwarning(
                "Admin Required",
                "Run StreamDesk as Administrator to add the firewall rule.\n"
                f"Or add manually: UDP inbound port {self.cfg.get('udp_port',5005)}")
            return
        add_firewall_rule(self.cfg.get("udp_port", 5005))
        self._set_status("Firewall rule added")

    def _save_settings(self):
        self.cfg["udp_port"]        = self._port_var.get()
        self.cfg["cooldown_ms"]     = self._cd_var.get()
        self.cfg["start_minimized"] = self._min_var.get()
        save_config(self.cfg)
        update_cfg(self.cfg)
        self._set_status("Settings saved")

    # ── Log tab ───────────────────────────────────────────────────────────────

    def _build_log_tab(self, nb):
        frame = tk.Frame(nb, bg=DARK_BG)
        nb.add(frame, text="  Log  ")

        tb = tk.Frame(frame, bg=PANEL_BG, pady=6)
        tb.pack(fill="x")
        tk.Label(tb, text="Live activity log — also saved to streamdesk.log",
                 bg=PANEL_BG, fg=TEXT_SUB, font=FONT_LABEL).pack(side="left", padx=16)
        tk.Button(tb, text="Open log file", bg=CARD_BG, fg=ACCENT,
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  command=lambda: os.startfile(LOG_FILE)
                  ).pack(side="right", padx=12, pady=4)
        tk.Button(tb, text="Clear", bg=CARD_BG, fg=TEXT_SUB,
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  command=self._clear_log).pack(side="right", padx=4, pady=4)

        self._log_text = tk.Text(
            frame, bg="#0a0a15", fg="#aaffaa",
            font=("Consolas", 8), relief="flat",
            state="disabled", wrap="word",
        )
        sb = tk.Scrollbar(frame, command=self._log_text.yview)
        self._log_text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

        # Hook logging into the text widget
        class _TkHandler(logging.Handler):
            def __init__(self_, w):
                super().__init__()
                self_._w = w
            def emit(self_, record):
                msg = self_.format(record) + "\n"
                try:
                    self_._w.after(0, self_._append, msg)
                except Exception:
                    pass
            def _append(self_, msg):
                self_._w.config(state="normal")
                self_._w.insert("end", msg)
                self_._w.see("end")
                self_._w.config(state="disabled")

        h = _TkHandler(self._log_text)
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger("StreamDesk").addHandler(h)

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ── About tab ─────────────────────────────────────────────────────────────

    def _build_about_tab(self, nb):
        frame = tk.Frame(nb, bg=DARK_BG)
        nb.add(frame, text="  About  ")
        inner = tk.Frame(frame, bg=DARK_BG)
        inner.place(relx=0.5, rely=0.38, anchor="center")

        tk.Label(inner, text=APP_NAME, bg=DARK_BG, fg=TEXT_MAIN,
                 font=("Segoe UI", 24, "bold")).pack()
        tk.Label(inner, text=f"Version {VERSION}", bg=DARK_BG, fg=TEXT_SUB,
                 font=FONT_SUB).pack(pady=(2, 16))

        info = (
            "ESP32 sends UDP packets to this PC on port 5005.\n\n"
            "UDP Commands:\n"
            "  BTN1 … BTN16      Trigger a configured button\n"
            "  MEDIA:PLAYPAUSE   Play/Pause\n"
            "  MEDIA:NEXT        Next track\n"
            "  MEDIA:PREV        Previous track\n"
            "  VOL:75            Set volume to 75%\n\n"
            "Media keys use Windows SendInput — NO admin required.\n"
            "Volume requires nircmd.exe (Settings → Download).\n\n"
            f"Log file:    {LOG_FILE}\n"
            f"Config file: {CONFIG_FILE}"
        )
        tk.Label(inner, text=info, bg=DARK_BG, fg=TEXT_SUB,
                 font=("Consolas", 9), justify="left").pack()

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=16)
        tk.Label(inner, text="Test a command (simulates ESP32 sending it):",
                 bg=DARK_BG, fg=TEXT_SUB, font=FONT_LABEL).pack()
        tr = tk.Frame(inner, bg=DARK_BG); tr.pack(pady=6)
        self._test_var = tk.StringVar(value="BTN1")
        tk.Entry(tr, textvariable=self._test_var, width=18,
                 bg=CARD_BG, fg=TEXT_MAIN,
                 insertbackground=TEXT_MAIN, relief="flat",
                 font=FONT_MONO).pack(side="left", ipady=4, padx=(0, 8))
        tk.Button(tr, text="Fire!", bg=ACCENT2, fg=TEXT_MAIN,
                  relief="flat", font=FONT_BTN, cursor="hand2",
                  padx=12, pady=4, command=self._test_fire).pack(side="left")

    def _test_fire(self):
        cmd = self._test_var.get().strip()
        if cmd:
            execute_action(self.cfg, cmd)
            self._set_status(f"Fired: {cmd}")

    # ── Tray / window ─────────────────────────────────────────────────────────

    def _show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_close(self):
        self.root.withdraw()   # minimise to tray, don't quit

    def _quit(self):
        save_config(self.cfg)
        stop_tray()
        stop_udp()
        self.root.destroy()

    def _set_status(self, msg: str):
        try:
            self._status_var.set(msg)
            self.root.after(6000, lambda: self._status_var.set(
                f"Listening on UDP port {self.cfg.get('udp_port', 5005)}"))
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tray", action="store_true",
                        help="Start minimised to system tray")
    args = parser.parse_args()

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    StreamDeskApp(root, tray_mode=args.tray)
    root.mainloop()

if __name__ == "__main__":
    main()
