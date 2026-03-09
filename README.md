# Synclight Bridge

**An independent, community-made bridge that lets Prismatik control the Robobloq Synclight USB LED strip.**

> This project is not affiliated with, endorsed by, or connected to Robobloq in any way.
> It was developed independently through USB traffic analysis for personal interoperability use.

---

## What is this?

The Robobloq Synclight is a USB HID LED strip (VID `0x1A86` / PID `0xFE07`).
This project documents its USB communication protocol and uses that documentation to bridge it with [Prismatik](https://github.com/psieg/Lightpack) — an open-source screen-capture ambilight application.

Once set up, your Synclight reacts to your screen in real time.

---

## Disclaimer

This software is provided **as-is**, for **personal, non-commercial interoperability use** only.

- This project is **not** affiliated with, authorized by, or endorsed by Robobloq or any of its partners.
- The USB protocol was documented by observing traffic between the hardware and its official software on a personally-owned device — a standard interoperability research practice protected in many jurisdictions (e.g. DMCA §1201(f), EU Software Directive Art. 6).
- No proprietary code, firmware, or copyrighted material from Robobloq was copied, extracted, or distributed.
- Use this software at your own risk. The authors take no responsibility for any damage to hardware, software, or warranty status.

---

## Installation

### One-click installer (recommended)

Download **SynclightSetup.exe** from the [latest release](https://github.com/n1xsoph1c/SyncLight-Prismatik/releases/latest) and run it.

The installer will:
- Install Synclight Bridge to `Program Files`
- Optionally create a desktop shortcut
- Optionally register auto-start at login
- Optionally download and install Prismatik

### Manual (Python)

```bash
pip install -r requirements.txt
python synclight_app.py
```

Requires Python 3.10+ and Windows 10/11.

---

## Prismatik Setup

> Required — Prismatik must be configured to send data to the bridge over UDP.

1. Open **Prismatik** → **Settings** → **Device**
2. Click **Device Setup Wizard** → select **UDP (DRGB)**
3. Set:
   - **IP Address:** `127.0.0.1`
   - **Port:** `21324`
   - **Number of LEDs:** `80` (or however many you've configured)
4. Click **Apply**

---

## Usage

After launching, a tray icon appears in the bottom-right of your taskbar:

| Action | Result |
|--------|--------|
| Left-click / Open Settings | Opens the web UI at `http://127.0.0.1:8420` |
| Restart Bridge | Reconnects to the USB device and UDP socket |
| Quit | Turns off LEDs and exits |

The web UI shows live status (connection, current LED color, packet count) and lets you change settings and toggle auto-start.

---

## Troubleshooting

**LEDs don't react to the screen**
- Confirm Prismatik device is set to UDP (DRGB), IP `127.0.0.1`, port `21324`
- Web UI should show "Connected" with a rising packet count
- Click **Restart Bridge** in the tray or web UI

**"Not found" / device not connecting**
- Unplug and replug the USB strip
- Check Device Manager for `USB-SERIAL CH340` — install the [CH34x driver](https://www.wch-ic.com/downloads/CH341SER_EXE.html) if missing
- Run `python synclight_driver.py --list` to enumerate HID interfaces

**Port conflict**
- Something else is on port `21324`. Change it in the web UI and update Prismatik to match.

---

## How it works (protocol documentation)

The Synclight exposes two USB HID interfaces:

| Interface | Usage Page | Purpose |
|-----------|-----------|---------|
| 0 | `0xFF00` (vendor) | LED control |
| 1 | `0x0001` (generic desktop) | Ignore |

Each color update is a **64-byte HID report** (prefixed with report ID `0x00`, so 65 bytes on the wire):

```
Offset  Value   Meaning
──────────────────────────────────────────────────
 0      0x52    Header byte 1
 1      0x42    Header byte 2
 2      0x10    Payload length
 3      seq     Sequence counter (0–255, wraps)
 4      0x86    Sub-command
 5      0x01    Sub-command
 6      R       Red   (0–255)
 7      G       Green (0–255)
 8      B       Blue  (0–255)
 9      0x4F    Fixed
10      0x50    Fixed
11–14   0x00    Padding
14      0xFE    End marker
15      chk     Checksum = sum(bytes[0:15]) & 0xFF
16–63   0x00    Padding
```

Prismatik sends averaged screen colors over UDP using the DRGB protocol. The bridge listens, averages all LED values into one color, and writes it to the strip.

---

## Project structure

```
synclight_app.py          Main tray app (recommended entry point)
synclight_driver.py       Low-level HID driver; direct color control
synclight_prismatik.py    Headless bridge (no UI)
requirements.txt          Python dependencies
packaging/
  synclight.spec          PyInstaller build spec
  build_icon.py           Icon generator (run once, output committed)
installer/
  synclight_setup.iss     Inno Setup 6 installer script
assets/
  icon.ico                Application icon
scripts/
  install.py              Legacy Python installer (dev use)
  start_synclight.vbs     Legacy VBS launcher (dev use)
.github/workflows/
  release.yml             CI/CD: builds installer on git tag push
```

---

## Building from source

```bash
# Generate icon (once)
python packaging/build_icon.py

# Build executable
pyinstaller packaging/synclight.spec --noconfirm

# Build installer (requires Inno Setup 6)
ISCC.exe /DAppVersion=1.0.0 installer\synclight_setup.iss
```

Or push a `v*` tag and let GitHub Actions do it automatically.

---

## License

GNU General Public License v2.0 — see [LICENSE](LICENSE).

This means you are free to use, study, modify, and redistribute this software under the same terms. You may **not** distribute proprietary derivatives.

---

## Credits

- Protocol documented by [n1xsoph1c](https://github.com/n1xsoph1c) via USB traffic analysis
- [Prismatik](https://github.com/psieg/Lightpack) by psieg / Woodenshark
- [hidapi](https://github.com/trezor/cython-hidapi) Python bindings
- [pystray](https://github.com/moses-palmer/pystray) system tray library
