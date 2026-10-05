# StreamDesk

StreamDesk is a Windows desktop companion for an ESP32 macro pad. It receives commands from the ESP32 over the local network and performs actions on the Windows PC.

## Features

* ESP32 macro-pad support
* Windows system controls
* Application launching
* Media controls
* Volume control
* System tray support
* Configurable buttons
* Windows auto-start
* Runs in the background
* Logging
* Settings UI

---

# Requirements

* Windows 10 or Windows 11
* Python 3.9+
* ESP32 macro pad
* Same local network for the ESP32 and Windows PC

Required Python packages:

```text
pywin32
pystray
Pillow
keyboard
psutil
requests
```

---

# Project Files

```text
StreamDesk/
│
├── streamdesk.py
├── streamdesk_config.json
│
├── run_hidden.vbs
├── run_as_admin.bat
├── install_and_run.bat
├── set_scheduler.bat
│
├── nircmd.exe
└── streamdesk.log
```

## Important Files

### `streamdesk.py`

Main StreamDesk application.

It contains:

* GUI
* ESP32 communication
* System controls
* Tray functionality
* Settings
* Configuration
* Windows auto-start registration

---

### `run_hidden.vbs`

Silent launcher used by Windows Task Scheduler.

The scheduled task starts:

```text
wscript.exe
    ↓
run_hidden.vbs
    ↓
pythonw.exe
    ↓
streamdesk.py --tray
```

The `--tray` argument starts StreamDesk minimized to the Windows system tray.

---

### `run_as_admin.bat`

Manually starts StreamDesk with Administrator privileges.

Use this when you want to launch the application manually as Administrator.

---

### `install_and_run.bat`

Installs the required Python packages and starts StreamDesk.

It also attempts to download `nircmd.exe` for volume-control functionality.

---

### `set_scheduler.bat`

Configures Windows auto-start.

This is the recommended way to manually configure or repair StreamDesk auto-start.

Every time `set_scheduler.bat` is run, it:

1. Checks for `run_hidden.vbs`
2. Deletes the existing `StreamDesk` scheduled task
3. Creates a new scheduled task
4. Configures it to start at Windows logon
5. Adds a 30-second startup delay
6. Configures the task to run with highest privileges
7. Uses `run_hidden.vbs` as the launcher
8. Verifies the scheduled task

Run:

```text
set_scheduler.bat
```

**Important:** Run it as **Administrator**.

To run as Administrator:

```text
Right-click set_scheduler.bat
        ↓
Run as administrator
```

---

# Windows Auto-Start

StreamDesk uses **Windows Task Scheduler** for automatic startup.

The scheduled task is named:

```text
StreamDesk
```

The startup flow is:

```text
Windows Login
     ↓
Task Scheduler
     ↓
StreamDesk task
     ↓
Wait 30 seconds
     ↓
wscript.exe
     ↓
run_hidden.vbs
     ↓
pythonw.exe
     ↓
streamdesk.py --tray
     ↓
StreamDesk runs in system tray
```

## Configure Auto-Start from StreamDesk

Open:

```text
StreamDesk
    → Settings
        → Startup
            → Start with Windows
```

When enabled, StreamDesk attempts to create the `StreamDesk` scheduled task automatically.

If Windows permissions prevent the task from being created, use:

```text
set_scheduler.bat
```

and run it as Administrator.

---

# Check Auto-Start

Open Command Prompt and run:

```cmd
schtasks /query /tn "StreamDesk" /v /fo list
```

If the task exists, Windows will display information such as:

```text
TaskName:       \StreamDesk
Status:         Ready
Task To Run:    wscript.exe ...
Schedule Type:  At logon
```

If you see:

```text
ERROR: The system cannot find the file specified.
```

the `StreamDesk` scheduled task does not exist.

Run:

```text
set_scheduler.bat
```

as Administrator to recreate it.

---

# Remove Auto-Start

You can disable auto-start from:

```text
StreamDesk
    → Settings
        → Startup
            → Start with Windows
```

Or manually remove the task using Command Prompt:

```cmd
schtasks /delete /tn "StreamDesk" /f
```

After deleting it, StreamDesk will no longer automatically start when Windows logs in.

---

# Manual Start

To manually start StreamDesk:

```text
install_and_run.bat
```

or:

```text
run_as_admin.bat
```

---

# Running in the System Tray

When started by Windows Task Scheduler, StreamDesk is launched using:

```text
streamdesk.py --tray
```

This causes the main window to remain hidden and StreamDesk to run from the system tray.

You can open the main window from the StreamDesk tray icon.

---

# Configuration

StreamDesk stores configuration in:

```text
streamdesk_config.json
```

The application also writes logs to:

```text
streamdesk.log
```

---

# Troubleshooting

## Auto-start does not work

First check:

```cmd
schtasks /query /tn "StreamDesk" /v /fo list
```

If the task does not exist, run:

```text
set_scheduler.bat
```

as Administrator.

---

## StreamDesk starts but the window is not visible

This is expected when Windows starts StreamDesk.

The scheduled task launches:

```text
streamdesk.py --tray
```

Check the Windows system tray for the StreamDesk icon.

---

## Python cannot be found

`run_hidden.vbs` searches several common Python installation locations.

It also attempts to locate:

```text
pythonw.exe
```

through the Windows PATH.

If Python was installed in a custom location, update the Python paths inside:

```text
run_hidden.vbs
```

---

## Check the scheduled task manually

Open:

```text
Task Scheduler
```

by pressing:

```text
Win + R
```

and running:

```text
taskschd.msc
```

Look for:

```text
StreamDesk
```

under the scheduled tasks.

---

# Auto-Start Task Configuration

The expected configuration is:

| Setting            | Value               |
| ------------------ | ------------------- |
| Task name          | `StreamDesk`        |
| Trigger            | At log on           |
| Delay              | 30 seconds          |
| Action             | `wscript.exe`       |
| Script             | `run_hidden.vbs`    |
| Run level          | Highest privileges  |
| Battery            | Start if on battery |
| Battery transition | Don't stop          |
| Execution limit    | Unlimited           |

---

# Development

Run StreamDesk directly with Python:

```cmd
python streamdesk.py
```

Run it in tray mode:

```cmd
python streamdesk.py --tray
```

---

# License

This project is for personal/internal use unless otherwise specified.
