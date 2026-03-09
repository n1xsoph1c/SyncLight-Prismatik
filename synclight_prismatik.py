"""
Prismatik -> Synclight bridge (DRGB UDP mode)

In Prismatik: set device to DRGB UDP, IP 127.0.0.1, port 21324, any LED count.
Run this script, then use Prismatik normally (screen grab, mood lamp, on/off, all work).

Usage:
    python synclight_prismatik.py

Requirements:
    pip install hidapi
"""

import socket
import hid
import sys

VENDOR_ID  = 0x1A86
PRODUCT_ID = 0xFE07
UDP_PORT   = 21324   # must match Prismatik's DRGB UDP port setting

_seq = 0

def build_packet(r, g, b):
    global _seq
    pkt = bytearray(64)
    pkt[0]  = 0x52; pkt[1]  = 0x42; pkt[2]  = 0x10
    pkt[3]  = _seq & 0xFF
    pkt[4]  = 0x86; pkt[5]  = 0x01
    pkt[6]  = r & 0xFF; pkt[7]  = g & 0xFF; pkt[8]  = b & 0xFF
    pkt[9]  = 0x4F; pkt[10] = 0x50
    pkt[11] = 0x00; pkt[12] = 0x00; pkt[13] = 0x00; pkt[14] = 0xFE
    pkt[15] = sum(pkt[0:15]) & 0xFF
    _seq = (_seq + 1) & 0xFF
    return bytes(pkt)

def open_synclight():
    ifaces = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not ifaces:
        print(f"[ERR] Synclight not found. Is it plugged in?")
        sys.exit(1)
    target = next((d for d in ifaces if d.get("usage_page", 0) != 0x0001), ifaces[0])
    d = hid.device()
    d.open_path(target["path"])
    d.set_nonblocking(1)
    print(f"[Synclight] Connected: {d.get_manufacturer_string()} - {d.get_product_string()}")
    return d

def run():
    dev = open_synclight()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", UDP_PORT))
    print(f"[UDP] Listening on 127.0.0.1:{UDP_PORT}  (Ctrl+C to stop)")
    print(f"[UDP] In Prismatik: device = DRGB UDP, IP = 127.0.0.1, port = {UDP_PORT}")

    last = (-1, -1, -1)

    try:
        while True:
            data, _ = sock.recvfrom(4096)

            # DRGB packet: byte 0 = 0x02, byte 1 = timeout, then R,G,B per LED
            if len(data) < 5 or data[0] != 0x02:
                continue

            rgb_data = data[2:]  # skip 2-byte header
            n = len(rgb_data) // 3
            if n == 0:
                continue

            r = sum(rgb_data[i*3]   for i in range(n)) // n
            g = sum(rgb_data[i*3+1] for i in range(n)) // n
            b = sum(rgb_data[i*3+2] for i in range(n)) // n

            if (r, g, b) != last:
                dev.write(b"\x00" + build_packet(r, g, b))
                last = (r, g, b)

    except KeyboardInterrupt:
        print("\nStopped.")
        dev.write(b"\x00" + build_packet(0, 0, 0))
        dev.close()
        sock.close()

if __name__ == "__main__":
    run()
