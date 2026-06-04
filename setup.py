"""
StreamDesk Setup — run once to install all dependencies and create shortcuts.
Usage:  python setup.py
"""
import sys
import os
import subprocess
import shutil

REQUIRED = [
    ("pywin32",   "win32gui"),
    ("pystray",   "pystray"),
    ("Pillow",    "PIL"),
    ("keyboard",  "keyboard"),
    ("psutil",    "psutil"),
    ("requests",  "requests"),
]

def pip_install(pkg):
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", pkg],
        stdout=subprocess.DEVNULL
    )

def main():
    print("=" * 50)
    print("  StreamDesk Setup")
    print("=" * 50)
    print()

    # 1. Install packages
    for pkg, mod in REQUIRED:
        try:
            __import__(mod)
            print(f"  [ok]  {pkg}")
        except ImportError:
            print(f"  [..] installing {pkg} …", end=" ", flush=True)
            try:
                pip_install(pkg)
                print("done")
            except Exception as e:
                print(f"FAILED: {e}")

    # 2. pywin32 post-install (registers COM objects)
    try:
        import win32api   # noqa: F401
    except ImportError:
        try:
            scripts = os.path.join(os.path.dirname(sys.executable), "Scripts")
            post = os.path.join(scripts, "pywin32_postinstall.py")
            if os.path.exists(post):
                subprocess.check_call([sys.executable, post, "-install"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    print()
    print("  All dependencies installed.")

    # 3. Create desktop shortcut
    try:
        import winshell   # optional
    except ImportError:
        pass

    # Manually create a .lnk via PowerShell (no extra deps)
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    lnk     = os.path.join(desktop, "StreamDesk.lnk")
    target  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "streamdesk.py")
    ps = (
        f'$ws = New-Object -ComObject WScript.Shell;'
        f'$s  = $ws.CreateShortcut("{lnk}");'
        f'$s.TargetPath = "{sys.executable}";'
        f'$s.Arguments  = \\"{target}\\";'
        f'$s.WorkingDirectory = "{os.path.dirname(target)}";'
        f'$s.Description = "StreamDesk Macro Controller";'
        f'$s.Save()'
    )
    try:
        subprocess.run(["powershell", "-Command", ps], capture_output=True)
        print(f"  Desktop shortcut created: {lnk}")
    except Exception:
        print("  (Could not create desktop shortcut)")

    print()
    print("  Setup complete! Launching StreamDesk…")
    print()

    # 4. Launch
    subprocess.Popen([sys.executable,
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "streamdesk.py")])

if __name__ == "__main__":
    main()
    input("Press Enter to close…")
