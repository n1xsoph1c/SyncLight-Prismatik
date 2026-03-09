# Synclight Bridge

**Reverse-engineered USB driver and Prismatik bridge for the Robobloq Synclight LED strip.**

Control your Robobloq Synclight from Prismatik (ambilight software) on Windows — with a background tray app, a web settings UI, and auto-start on boot.

> Made by [n1xsoph1c](https://github.com/n1xsoph1c)

---

## What is this?

The Robobloq Synclight is a USB HID LED strip (VID `0x1A86` / PID `0xFE07`) sold with Robobloq's own app. This project reverse-engineers the USB protocol and bridges it to [Prismatik](https://github.com/psieg/Lightpack), a screen-capture ambilight application for Windows.

Once set up, your Synclight reacts to your screen in real time — no Robobloq app needed.

---

## How it works

### USB Protocol (reverse engineered)

The Synclight exposes two USB HID interfaces:

| Interface | Usage Page | Purpose |
|-----------|-----------|---------|
| 0 | `0xFF00` (vendor) | **LED control** ← correct one |
| 1 | `0x0001` (keyboard) | Keyboard HID — ignore |

Each color update is a **64-byte interrupt transfer** to endpoint `0x01`:

```
Offset  Value   Meaning
──────────────────────────────────────────────────
 0      0x52    Command header 'R'
 1      0x42    Command header 'B'
 2      0x10    Payload length
 3      seq     Sequence counter (0–255, wraps)
 4      0x86    Sub-command
 5      0x01    Sub-command
 6      R       Red   (0–255)
 7      G       Green (0–255)
 8      B       Blue  (0–255)
 9      0x4F    Fixed
10      0x50    Fixed
11–14   0x00…   Padding / fixed
14      0xFE    End marker
15      chk     Checksum = sum(bytes[0:15]) & 0xFF
16–63   0x00    Padding
```

The 64-byte payload is prefixed with a **report ID byte `0x00`** before writing via hidapi (standard HID report framing), making the actual write 65 bytes.

### Prismatik DRGB UDP

Prismatik captures your screen, maps regions to LEDs, and can push color data over UDP using the **DRGB protocol** (from WLED):

```
Byte 0:    0x02          — DRGB packet type
Byte 1:    timeout       — seconds before strip turns off (255 = never)
Bytes 2+:  R G B R G B … — one RGB triplet per configured LED
```

`synclight_prismatik.py` / `synclight_app.py` listen on UDP, average all LED colors into one, and write that color to the Synclight strip via HID.

---

## Requirements

- Windows 10/11
- Python 3.10+
- [Prismatik](https://github.com/psieg/Lightpack/releases) installed
- Robobloq Synclight plugged in via USB

---

## Installation

### Quick install

```bash
git clone https://github.com/n1xsoph1c/synclight.git
cd synclight
python install.py
```

The installer will:
1. Install Python dependencies (`hidapi`, `flask`, `pystray`, `pillow`)
2. Optionally register a Windows login task (auto-start)
3. Launch the tray app

### Manual install

```bash
pip install hidapi flask pystray pillow
python synclight_app.py
```

---

## Prismatik Setup

> **This step is required.** Prismatik must be configured to send DRGB UDP to the bridge.

1. Open **Prismatik**
2. Go to **Settings → Device**
3. Click **Device Setup Wizard**
4. Select **DRGB UDP**
5. Set:
   - **IP Address:** `127.0.0.1`
   - **Port:** `21324`
   - **Number of LEDs:** `80` (or however many you have configured)
6. Click **Apply**

Prismatik will now push color data to the bridge over UDP.

### Prismatik LED layout

For best results, configure LED zones around the edges of your monitor in Prismatik's **LED placement** screen. The bridge averages all LED colors into one value sent to the strip — the more LEDs you map to your screen edges, the smoother the color blending.

---

## Usage

### As a tray app (recommended)

```bash
python synclight_app.py
```

- A tray icon appears in the bottom-right of your taskbar
- **Left-click / Open Settings** → opens the web UI at `http://127.0.0.1:8420`
- **Restart Bridge** → reconnects to the Synclight HID device and UDP socket
- **Quit** → turns off the LEDs and exits

### Web UI

Open `http://127.0.0.1:8420` in any browser:

- **Live Status** — shows bridge state, current LED color, and packet count
- **Settings** — change the UDP IP/port; toggle auto-start on boot
- **Actions** — restart the bridge, check for updates on GitHub

### Standalone bridge (no tray)

```bash
python synclight_prismatik.py
```

Listens for Prismatik UDP and drives the LED strip. No UI. Ctrl+C to stop (turns LEDs off).

### Direct control (testing / scripting)

```bash
python synclight_driver.py               # Demo color cycle
python synclight_driver.py 255 0 0       # Set static color (red)
python synclight_driver.py --list        # List HID interfaces
```

---

## Configuration

Settings are stored in `synclight_config.json` next to the app:

```json
{
  "ip": "127.0.0.1",
  "port": 21324,
  "run_on_boot": false,
  "web_port": 8420
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `ip` | `127.0.0.1` | IP to listen on for Prismatik UDP |
| `port` | `21324` | UDP port (must match Prismatik config) |
| `run_on_boot` | `false` | Auto-start via Windows Task Scheduler |
| `web_port` | `8420` | Port for the local settings web UI |

---

## File Overview

| File | Description |
|------|-------------|
| `synclight_driver.py` | Low-level HID driver; USB protocol implementation |
| `synclight_prismatik.py` | Minimal headless bridge (no UI) |
| `synclight_app.py` | Full tray app with web UI (recommended) |
| `install.py` | One-shot installer |
| `synclight_config.json` | Runtime config (auto-created) |

---

## Troubleshooting

**LEDs don't change with the screen**
- Make sure Prismatik device is set to DRGB UDP, IP `127.0.0.1`, port `21324`
- The web UI should show "Connected" and a rising packet count
- Try clicking **Restart Bridge** in the tray or web UI

**"Synclight not found" error**
- Unplug and replug the USB strip
- Check Device Manager for `USB-SERIAL CH340` or similar — the strip needs the CH34x driver
- Run `python synclight_driver.py --list` to see enumerated HID interfaces

**Tray icon doesn't appear**
- Run `python synclight_app.py` from a terminal to see error output
- Make sure `pystray` and `pillow` are installed: `pip install pystray pillow`

**Port already in use**
- Another process is on port `21324`. Change the port in the web UI and update Prismatik to match.

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Credits

- Protocol reverse-engineered by [n1xsoph1c](https://github.com/n1xsoph1c) using Wireshark USB captures
- [Prismatik](https://github.com/psieg/Lightpack) by psieg / Woodenshark
- [hidapi](https://github.com/trezor/cython-hidapi) Python bindings
- [pystray](https://github.com/moses-palmer/pystray) system tray library
