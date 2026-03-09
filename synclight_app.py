"""
Synclight Bridge — System tray app with Web UI
Bridges Prismatik DRGB UDP output to the Robobloq Synclight USB LED strip.

Author: n1xsoph1c (https://github.com/n1xsoph1c)
"""

import threading
import socket
import json
import os
import sys
import webbrowser
import subprocess
import urllib.request as urlreq
from pathlib import Path

import hid
from flask import Flask, jsonify, request, render_template_string
import pystray
from PIL import Image, ImageDraw

# ── Constants ─────────────────────────────────────────────────────────────────

VERSION      = "1.0.0"
GITHUB_REPO  = "n1xsoph1c/synclight"
VENDOR_ID    = 0x1A86
PRODUCT_ID   = 0xFE07
TASK_NAME    = "SynclightBridge"
CONFIG_PATH  = Path(__file__).parent / "synclight_config.json"

DEFAULT_CONFIG = {
    "ip": "127.0.0.1",
    "port": 21324,
    "run_on_boot": False,
    "web_port": 8420,
}

# ── Config ────────────────────────────────────────────────────────────────────

config: dict = {}

def load_config():
    global config
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            config = {**DEFAULT_CONFIG, **json.load(f)}
    else:
        config = DEFAULT_CONFIG.copy()
        save_config()

def save_config():
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

# ── Bridge ────────────────────────────────────────────────────────────────────

_seq         = 0
bridge_stop  = threading.Event()
bridge_thread: threading.Thread | None = None
hid_device   = None
bridge_status = {"connected": False, "led_color": [0, 0, 0], "packets": 0}


def build_packet(r: int, g: int, b: int) -> bytes:
    global _seq
    pkt = bytearray(64)
    pkt[0]=0x52; pkt[1]=0x42; pkt[2]=0x10; pkt[3]=_seq & 0xFF
    pkt[4]=0x86; pkt[5]=0x01
    pkt[6]=r & 0xFF; pkt[7]=g & 0xFF; pkt[8]=b & 0xFF
    pkt[9]=0x4F; pkt[10]=0x50
    pkt[11]=0x00; pkt[12]=0x00; pkt[13]=0x00; pkt[14]=0xFE
    pkt[15] = sum(pkt[0:15]) & 0xFF
    _seq = (_seq + 1) & 0xFF
    return bytes(pkt)


def open_synclight():
    ifaces = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not ifaces:
        return None
    target = next((d for d in ifaces if d.get("usage_page", 0) != 0x0001), ifaces[0])
    d = hid.device()
    d.open_path(target["path"])
    d.set_nonblocking(1)
    return d


def bridge_loop():
    global hid_device
    bridge_stop.clear()
    bridge_status["packets"] = 0

    dev = open_synclight()
    if not dev:
        bridge_status["connected"] = False
        return

    hid_device = dev
    bridge_status["connected"] = True

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    try:
        sock.bind((config["ip"], config["port"]))
    except Exception as e:
        bridge_status["connected"] = False
        dev.close()
        return

    last = (-1, -1, -1)
    while not bridge_stop.is_set():
        try:
            data, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except Exception:
            break

        # DRGB UDP: byte 0 = 0x02, byte 1 = timeout, then R,G,B per LED
        if len(data) < 5 or data[0] != 0x02:
            continue

        rgb_data = data[2:]
        n = len(rgb_data) // 3
        if n == 0:
            continue

        r = sum(rgb_data[i * 3]     for i in range(n)) // n
        g = sum(rgb_data[i * 3 + 1] for i in range(n)) // n
        b = sum(rgb_data[i * 3 + 2] for i in range(n)) // n

        if (r, g, b) != last:
            try:
                dev.write(b"\x00" + build_packet(r, g, b))
                bridge_status["led_color"] = [r, g, b]
                bridge_status["packets"]  += 1
                last = (r, g, b)
            except Exception:
                break

    try:
        dev.write(b"\x00" + build_packet(0, 0, 0))
        dev.close()
    except Exception:
        pass

    sock.close()
    bridge_status["connected"] = False
    hid_device = None


def start_bridge():
    global bridge_thread
    if bridge_thread and bridge_thread.is_alive():
        return
    bridge_thread = threading.Thread(target=bridge_loop, daemon=True)
    bridge_thread.start()


def stop_bridge():
    bridge_stop.set()
    if bridge_thread:
        bridge_thread.join(timeout=3)


def restart_bridge():
    stop_bridge()
    start_bridge()

# ── Boot (Task Scheduler) ─────────────────────────────────────────────────────

def set_boot(enabled: bool):
    script_path = Path(__file__).resolve()
    pythonw     = Path(sys.executable).parent / "pythonw.exe"
    vbs_path    = script_path.parent / "start_synclight_app.vbs"

    if enabled:
        vbs_path.write_text(
            f'Set oShell = CreateObject("WScript.Shell")\n'
            f'oShell.Run """{pythonw}"" ""{script_path}""", 0, False\n'
        )
        subprocess.run(
            ["powershell", "-Command",
             f'$a=New-ScheduledTaskAction -Execute "wscript.exe" -Argument "{vbs_path}";'
             f'$t=New-ScheduledTaskTrigger -AtLogOn;'
             f'$s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0;'
             f'Register-ScheduledTask -TaskName "{TASK_NAME}" -Action $a -Trigger $t -Settings $s -Force'],
            capture_output=True,
        )
    else:
        subprocess.run(
            ["powershell", "-Command",
             f'Unregister-ScheduledTask -TaskName "{TASK_NAME}" -Confirm:$false'],
            capture_output=True,
        )

    config["run_on_boot"] = enabled
    save_config()

# ── Web UI ────────────────────────────────────────────────────────────────────

app = Flask(__name__)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Synclight Bridge</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d1a;color:#e0e0e0;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.wrap{max-width:460px;width:100%}
.card{background:#14142a;border:1px solid #252545;border-radius:14px;padding:22px;margin-bottom:14px}
h1{font-size:22px;color:#00c8ff;letter-spacing:.5px}
.sub{color:#555;font-size:12px;margin-top:2px}
h3{font-size:13px;color:#888;text-transform:uppercase;letter-spacing:.8px;margin-bottom:14px}
.stat{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid #1e1e38}
.stat:last-child{border:none}
.slabel{color:#666;font-size:13px}
.sval{font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px}
.dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.dot.on{background:#00ff88;box-shadow:0 0 7px #00ff88;animation:pulse 2s infinite}
.dot.off{background:#ff4455}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.swatch{width:28px;height:28px;border-radius:6px;border:1px solid #2a2a4a;flex-shrink:0}
.badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700}
.ok{background:#00ff8818;color:#00ff88;border:1px solid #00ff8833}
.err{background:#ff445518;color:#ff4455;border:1px solid #ff445533}
label{display:block;font-size:12px;color:#777;margin-bottom:5px}
input[type=text],input[type=number]{width:100%;background:#0d0d1a;border:1px solid #252545;color:#e0e0e0;padding:9px 12px;border-radius:8px;font-size:14px;transition:border .2s}
input:focus{outline:none;border-color:#00c8ff}
.row{display:flex;gap:12px}
.row>div{flex:1}
.togrow{display:flex;justify-content:space-between;align-items:center;padding:4px 0}
.toglabel{font-size:14px}
.sw{position:relative;width:42px;height:23px;flex-shrink:0}
.sw input{opacity:0;width:0;height:0}
.sl{position:absolute;inset:0;background:#252545;border-radius:23px;cursor:pointer;transition:.25s}
.sl:before{content:'';position:absolute;width:17px;height:17px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.25s}
input:checked+.sl{background:#00c8ff}
input:checked+.sl:before{transform:translateX(19px)}
.btnrow{display:flex;gap:8px;flex-wrap:wrap}
.btn{padding:9px 18px;border-radius:8px;border:none;cursor:pointer;font-size:13px;font-weight:600;transition:all .2s;letter-spacing:.3px}
.btn-p{background:#00c8ff;color:#000}
.btn-p:hover{background:#00aadd}
.btn-s{background:#1e1e38;color:#ccc;border:1px solid #252545}
.btn-s:hover{background:#252545}
#umsg{margin-top:10px;font-size:13px;color:#888;display:none}
.foot{text-align:center;color:#333;font-size:12px;margin-top:6px}
.foot a{color:#444;text-decoration:none}
.foot a:hover{color:#00c8ff}
</style>
</head>
<body>
<div class="wrap">

  <div class="card">
    <h1>&#9728; Synclight Bridge</h1>
    <p class="sub">Robobloq Synclight + Prismatik DRGB</p>
  </div>

  <div class="card">
    <h3>Live Status</h3>
    <div class="stat">
      <span class="slabel">Bridge</span>
      <span class="sval" id="bridge-st">—</span>
    </div>
    <div class="stat">
      <span class="slabel">LED Color</span>
      <span class="sval">
        <span class="swatch" id="swatch"></span>
        <span id="hex-val">#000000</span>
      </span>
    </div>
    <div class="stat">
      <span class="slabel">Packets received</span>
      <span class="sval" id="pkts">0</span>
    </div>
    <div class="stat">
      <span class="slabel">Listening on</span>
      <span class="sval" id="listen">—</span>
    </div>
  </div>

  <div class="card">
    <h3>Settings</h3>
    <div class="row" style="margin-bottom:14px">
      <div>
        <label>Prismatik IP</label>
        <input type="text" id="ip" placeholder="127.0.0.1">
      </div>
      <div>
        <label>UDP Port</label>
        <input type="number" id="port" placeholder="21324">
      </div>
    </div>
    <div class="togrow" style="margin-bottom:16px">
      <span class="toglabel">Run on System Boot</span>
      <label class="sw"><input type="checkbox" id="boot"><span class="sl"></span></label>
    </div>
    <button class="btn btn-p" onclick="save()">Save &amp; Restart Bridge</button>
  </div>

  <div class="card">
    <h3>Actions</h3>
    <div class="btnrow">
      <button class="btn btn-s" onclick="doRestart()">Restart Bridge</button>
      <button class="btn btn-s" onclick="checkUpdate()">Check for Updates</button>
    </div>
    <div id="umsg"></div>
  </div>

  <div class="foot">
    Synclight Bridge v<span id="ver">—</span> &nbsp;&middot;&nbsp;
    <a href="https://github.com/GITHUB_REPO_PLACEHOLDER" target="_blank">GitHub</a>
    &nbsp;&middot;&nbsp; by n1xsoph1c
  </div>

</div>
<script>
async function poll(){
  try{
    const d=await(await fetch('/api/status')).json();
    const ok=d.connected;
    document.getElementById('bridge-st').innerHTML=ok
      ?'<span class="dot on"></span><span class="badge ok">Connected</span>'
      :'<span class="dot off"></span><span class="badge err">Disconnected</span>';
    const [r,g,b]=d.led_color;
    const hex='#'+[r,g,b].map(x=>x.toString(16).padStart(2,'0')).join('');
    document.getElementById('swatch').style.background=hex;
    document.getElementById('hex-val').textContent=hex;
    document.getElementById('pkts').textContent=d.packets;
    document.getElementById('listen').textContent=d.config.ip+':'+d.config.port;
    document.getElementById('ip').value=d.config.ip;
    document.getElementById('port').value=d.config.port;
    document.getElementById('boot').checked=d.config.run_on_boot;
    document.getElementById('ver').textContent=d.version;
  }catch(e){}
}
async function save(){
  await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ip:document.getElementById('ip').value,
      port:parseInt(document.getElementById('port').value),
      run_on_boot:document.getElementById('boot').checked})});
  setTimeout(poll,1200);
}
async function doRestart(){
  await fetch('/api/restart');
  setTimeout(poll,1500);
}
async function checkUpdate(){
  const m=document.getElementById('umsg');
  m.style.display='block'; m.textContent='Checking...';
  const d=await(await fetch('/api/check_update')).json();
  if(d.error){m.textContent='Error: '+d.error;}
  else if(d.update_available){m.innerHTML='Update available: v'+d.latest+' (current: v'+d.current+') — <a href="https://github.com/GITHUB_REPO_PLACEHOLDER/releases" target="_blank" style="color:#00c8ff">Download</a>';}
  else{m.textContent='You are up to date (v'+d.current+')';}
}
poll(); setInterval(poll,2000);
</script>
</body>
</html>"""

HTML = HTML.replace("GITHUB_REPO_PLACEHOLDER", GITHUB_REPO)


@app.route("/")
def index():
    return HTML


@app.route("/api/status")
def api_status():
    return jsonify({**bridge_status, "config": config, "version": VERSION})


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True)
    changed = False
    if "ip" in data:
        config["ip"] = data["ip"]
        changed = True
    if "port" in data:
        config["port"] = int(data["port"])
        changed = True
    if "run_on_boot" in data:
        set_boot(bool(data["run_on_boot"]))
    if changed:
        save_config()
        threading.Thread(target=restart_bridge, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/restart")
def api_restart():
    threading.Thread(target=restart_bridge, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/check_update")
def api_check_update():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urlreq.Request(url, headers={"User-Agent": "synclight-bridge"})
        with urlreq.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        latest = data["tag_name"].lstrip("v")
        return jsonify({"current": VERSION, "latest": latest,
                        "update_available": latest != VERSION})
    except Exception as e:
        return jsonify({"error": str(e)})


# ── Tray Icon ─────────────────────────────────────────────────────────────────

def make_icon_image():
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=(0, 200, 255, 255))
    draw.ellipse([16, 16, 48, 48], fill=(0, 100, 160, 255))
    return img


def open_ui(_icon=None, _item=None):
    webbrowser.open(f"http://127.0.0.1:{config['web_port']}")


def quit_app(icon, _item):
    stop_bridge()
    icon.stop()
    os._exit(0)


def run_tray():
    icon = pystray.Icon(
        "Synclight",
        make_icon_image(),
        "Synclight Bridge",
        menu=pystray.Menu(
            pystray.MenuItem("Open Settings", open_ui, default=True),
            pystray.MenuItem("Restart Bridge", lambda i, it: threading.Thread(target=restart_bridge, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        ),
    )
    icon.run()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    load_config()
    start_bridge()

    flask_thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=config["web_port"],
            debug=False, use_reloader=False
        ),
        daemon=True,
    )
    flask_thread.start()

    # Small delay then open browser so Flask is ready
    def _open():
        import time; time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{config['web_port']}")
    threading.Thread(target=_open, daemon=True).start()

    run_tray()  # blocks until Quit


if __name__ == "__main__":
    main()
