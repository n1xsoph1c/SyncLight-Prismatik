"""
Robobloq Synclight USB HID Driver
Reverse engineered from USB capture - VID_1A86 PID_FE07

Protocol:
  64-byte HID interrupt packets to endpoint 0x01
  [0-1]  = 52 42          (magic header)
  [2]    = 10             (color command)
  [3]    = seq            (incrementing counter, wraps at 0xFF)
  [4-5]  = 86 01          (subcommand, fixed)
  [6]    = R              (red 0-255)
  [7]    = G              (green 0-255)
  [8]    = B              (blue 0-255)
  [9-14] = 4f 50 00 00 00 fe  (fixed)
  [15]   = checksum       (sum of bytes 0-14, masked to 0xFF)
  [16-63]= 00             (padding)

Usage:
  python synclight_driver.py              # test: cycle RED/GREEN/BLUE
  python synclight_driver.py 255 0 0      # set static color (R G B)
  python synclight_driver.py --hyperion   # run as Hyperion UDP listener
  python synclight_driver.py --list       # list all matching HID interfaces

Requirements:
  pip install hidapi        # NOTE: use hidapi, NOT hid - hidapi bundles the DLL on Windows
"""

import hid
import time
import sys
import struct

VENDOR_ID  = 0x1A86
PRODUCT_ID = 0xFE07

_seq = 0

def build_packet(r, g, b, seq):
    """Build a 64-byte color command packet."""
    pkt = bytearray(64)
    pkt[0]  = 0x52
    pkt[1]  = 0x42
    pkt[2]  = 0x10
    pkt[3]  = seq & 0xFF
    pkt[4]  = 0x86
    pkt[5]  = 0x01
    pkt[6]  = r & 0xFF
    pkt[7]  = g & 0xFF
    pkt[8]  = b & 0xFF
    pkt[9]  = 0x4f
    pkt[10] = 0x50
    pkt[11] = 0x00
    pkt[12] = 0x00
    pkt[13] = 0x00
    pkt[14] = 0xfe
    pkt[15] = sum(pkt[0:15]) & 0xFF  # checksum
    return bytes(pkt)

def set_color(device, r, g, b):
    """Send a single color command to the strip."""
    global _seq
    pkt = build_packet(r, g, b, _seq)
    # HID write requires prepending a 0x00 report ID byte on Windows
    result = device.write(b"\x00" + pkt)
    if result < 0:
        print(f"[WARN] write() returned {result} - packet may not have been sent")
    _seq = (_seq + 1) & 0xFF

def open_device():
    """Open the Synclight HID device, selecting the correct vendor control interface.

    VID_1A86 PID_FE07 (CH9328 chip) exposes TWO HID interfaces:
      - Interface 0: standard keyboard/mouse  (usage_page=0x0001)  <- wrong one
      - Interface 1: vendor control           (usage_page=0xFF00)  <- we want this

    hid.open(VID, PID) grabs whichever comes first (often the keyboard one),
    so we enumerate all interfaces and explicitly pick the vendor-defined one.
    """
    all_ifaces = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not all_ifaces:
        print(f"[ERR] No HID device found with VID=0x{VENDOR_ID:04X} PID=0x{PRODUCT_ID:04X}")
        print("      Make sure the strip is plugged in.")
        sys.exit(1)

    # Prefer any interface that is NOT the standard HID keyboard/mouse page (0x0001).
    target = None
    for dev in all_ifaces:
        if dev.get("usage_page", 0) != 0x0001:
            target = dev
            break
    if target is None:
        target = all_ifaces[0]   # fallback: first interface

    try:
        d = hid.device()
        d.open_path(target["path"])
        d.set_nonblocking(1)
        print(f"[OK] Connected: {d.get_manufacturer_string()} - {d.get_product_string()}")
        print(f"     Interface {target.get(chr(105)+chr(110)+chr(116)+chr(101)+chr(114)+chr(102)+chr(97)+chr(99)+chr(101)+chr(95)+chr(110)+chr(117)+chr(109)+chr(98)+chr(101)+chr(114), chr(63))}, "
              f"usage_page=0x{target.get(chr(117)+chr(115)+chr(97)+chr(103)+chr(101)+chr(95)+chr(112)+chr(97)+chr(103)+chr(101), 0):04X}")
        return d
    except Exception as e:
        print(f"[ERR] Could not open device: {e}")
        print("      Close the Synclight app if it is running, then try again.")
        sys.exit(1)

def list_interfaces():
    """Print all HID interfaces matching the Synclight VID/PID."""
    all_ifaces = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not all_ifaces:
        print(f"No device found (VID=0x{VENDOR_ID:04X} PID=0x{PRODUCT_ID:04X})")
        return
    print(f"Found {len(all_ifaces)} interface(s):")
    for i, dev in enumerate(all_ifaces):
        print(f"  [{i}] interface={dev.get(chr(105)+chr(110)+chr(116)+chr(101)+chr(114)+chr(102)+chr(97)+chr(99)+chr(101)+chr(95)+chr(110)+chr(117)+chr(109)+chr(98)+chr(101)+chr(114),chr(63)):2}  "
              f"usage_page=0x{dev.get(chr(117)+chr(115)+chr(97)+chr(103)+chr(101)+chr(95)+chr(112)+chr(97)+chr(103)+chr(101),0):04X}  "
              f"path={dev[chr(112)+chr(97)+chr(116)+chr(104)]}")

def demo_cycle(device):
    """Cycle through RED / GREEN / BLUE with 1s delay."""
    colors = [
        (255, 0,   0,   "RED"),
        (0,   255, 0,   "GREEN"),
        (0,   0,   255, "BLUE"),
        (255, 255, 0,   "YELLOW"),
        (0,   255, 255, "CYAN"),
        (255, 0,   255, "MAGENTA"),
        (255, 255, 255, "WHITE"),
        (0,   0,   0,   "OFF"),
    ]
    print("Running color cycle demo. Ctrl+C to stop.")
    for r, g, b, name in colors:
        print(f"  Setting {name} ({r},{g},{b})")
        set_color(device, r, g, b)
        time.sleep(1.0)

def hyperion_listener(device, port=19446):
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    sock.settimeout(0.1)
    print(f"[Hyperion] Listening on UDP 127.0.0.1:{port}")
    print("[Hyperion] Configure Hyperion: controller=udpraw, target=127.0.0.1, port=19446")
    print("[Hyperion] Ctrl+C to stop.")
    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                if len(data) >= 3:
                    pixel_count = len(data) // 3
                    r_total = g_total = b_total = 0
                    for i in range(pixel_count):
                        r_total += data[i*3]
                        g_total += data[i*3 + 1]
                        b_total += data[i*3 + 2]
                    r = r_total // pixel_count
                    g = g_total // pixel_count
                    b = b_total // pixel_count
                    set_color(device, r, g, b)
            except socket.timeout:
                pass
    except KeyboardInterrupt:
        print("\n[Hyperion] Stopped.")
        set_color(device, 0, 0, 0)

if __name__ == "__main__":
    if "--list" in sys.argv:
        list_interfaces()
        sys.exit(0)

    device = open_device()

    if "--hyperion" in sys.argv:
        hyperion_listener(device)
    elif len(sys.argv) == 4:
        try:
            r, g, b = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
            print(f"Setting color: R={r} G={g} B={b}")
            set_color(device, r, g, b)
            print("Done.")
        except ValueError:
            print("Usage: synclight_driver.py <R> <G> <B>  (values 0-255)")
    else:
        demo_cycle(device)

    device.close()
