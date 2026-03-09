#!/usr/bin/env python3
"""
Synclight Bridge — Installer
Installs dependencies and optionally sets up auto-start on Windows.
"""

import subprocess
import sys
import os
from pathlib import Path

REQUIREMENTS = ["hidapi", "flask", "pystray", "pillow"]
SCRIPT_DIR   = Path(__file__).parent.resolve()
APP_SCRIPT   = SCRIPT_DIR / "synclight_app.py"


def header():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║     Synclight Bridge  —  Installer   ║")
    print("  ╚══════════════════════════════════════╝")
    print()


def check_python():
    if sys.version_info < (3, 10):
        print(f"[ERROR] Python 3.10+ required (you have {sys.version.split()[0]})")
        sys.exit(1)
    print(f"[OK] Python {sys.version.split()[0]}")


def install_packages():
    print("\n[1/3] Installing Python packages...")
    for pkg in REQUIREMENTS:
        print(f"      pip install {pkg} ...", end=" ", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "-q"],
            capture_output=True,
        )
        if result.returncode == 0:
            print("OK")
        else:
            print("FAILED")
            print(result.stderr.decode(errors="replace"))
            sys.exit(1)


def setup_boot():
    print("\n[2/3] Auto-start on login...")
    ans = input("      Run Synclight automatically when you log in? [Y/n]: ").strip().lower()
    if ans in ("", "y", "yes"):
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        vbs_path = SCRIPT_DIR / "start_synclight_app.vbs"
        vbs_path.write_text(
            f'Set oShell = CreateObject("WScript.Shell")\n'
            f'oShell.Run """{pythonw}"" ""{APP_SCRIPT}""", 0, False\n'
        )
        result = subprocess.run(
            ["powershell", "-Command",
             f'$a=New-ScheduledTaskAction -Execute "wscript.exe" -Argument "{vbs_path}";'
             f'$t=New-ScheduledTaskTrigger -AtLogOn;'
             f'$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0;'
             f'Register-ScheduledTask -TaskName "SynclightBridge" -Action $a -Trigger $t -Settings $s -Force'],
            capture_output=True,
        )
        if result.returncode == 0:
            print("      [OK] Scheduled task created — will start on next login.")
        else:
            print("      [WARN] Could not create scheduled task (try running as admin).")
    else:
        print("      Skipped.")


def launch():
    print("\n[3/3] Launching Synclight Bridge...")
    ans = input("      Launch now? [Y/n]: ").strip().lower()
    if ans in ("", "y", "yes"):
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        if pythonw.exists():
            subprocess.Popen([str(pythonw), str(APP_SCRIPT)])
        else:
            subprocess.Popen([sys.executable, str(APP_SCRIPT)])
        print("      [OK] Started. Look for the tray icon in the bottom-right corner.")
    else:
        print("      You can start it later with:  python synclight_app.py")


def main():
    header()
    check_python()
    install_packages()
    setup_boot()
    launch()
    print()
    print("  Installation complete!")
    print(f"  Settings UI: http://127.0.0.1:8420")
    print()


if __name__ == "__main__":
    main()
