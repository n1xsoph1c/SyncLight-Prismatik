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
import time
import webbrowser
import subprocess
import urllib.request as urlreq
from pathlib import Path

import hid
from flask import Flask, jsonify, request, render_template_string
import pystray
from PIL import Image, ImageDraw

# ── Constants ─────────────────────────────────────────────────────────────────

VERSION      = "1.1.1"
GITHUB_REPO  = "n1xsoph1c/synclight"
VENDOR_ID    = 0x1A86
PRODUCT_ID   = 0xFE07
TASK_NAME    = "SynclightBridge"
def _app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA', '')) / 'SynclightBridge'
    return Path(__file__).parent

CONFIG_PATH  = _app_dir() / "synclight_config.json"

DEFAULT_CONFIG = {
    "ip": "127.0.0.1",
    "port": 21324,
    "run_on_boot": False,
    "web_port": 8420,
    "zone_offset": 0,    # shift zone start by N positions (wraps around)
    "zone_reverse": False,  # reverse zone traversal direction
    "color_order": "RGB",
    "led_count": 80,
    "debug_view": False,
}

# ── Config ────────────────────────────────────────────────────────────────────

config: dict = {}

def load_config():
    global config
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
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

# Node protocol constants (ported from deobfuscated SyncLight app)
DEFAULT_LED_COUNT = 80

_cmd_seq     = 1
bridge_stop  = threading.Event()
bridge_thread: threading.Thread | None = None
hid_device   = None
bridge_socket: socket.socket | None = None
bridge_lock = threading.Lock()
bridge_status = {"connected": False, "led_color": [0, 0, 0], "packets": 0, "input_colors": [], "output_colors": [], "mapping_indices": []}


def get_led_count() -> int:
  try:
    value = int(config.get("led_count", DEFAULT_LED_COUNT))
  except (TypeError, ValueError):
    value = DEFAULT_LED_COUNT
  return max(1, min(240, value))


def _safe_int(value, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def _next_cmd_id() -> int:
  global _cmd_seq
  _cmd_seq += 1
  if _cmd_seq >= 255:
    _cmd_seq = 1
  return _cmd_seq


def _apply_color_order(r: int, g: int, b: int) -> tuple[int, int, int]:
  order = config.get("color_order", "RGB")
  if order == "GRB":
    return g & 0xFF, r & 0xFF, b & 0xFF
  if order == "BGR":
    return b & 0xFF, g & 0xFF, r & 0xFF
  if order == "RBG":
    return r & 0xFF, b & 0xFF, g & 0xFF
  if order == "GBR":
    return g & 0xFF, b & 0xFF, r & 0xFF
  if order == "BRG":
    return b & 0xFF, r & 0xFF, g & 0xFF
  return r & 0xFF, g & 0xFF, b & 0xFF


def _resample_leds(led_colors: list) -> list[tuple[int, int, int]]:
  led_count = get_led_count()
  n = len(led_colors)
  if n == led_count:
    return led_colors
  if n == 0:
    return [(0, 0, 0)] * led_count
  return [
    led_colors[min(int(i * n / led_count), n - 1)]
    for i in range(led_count)
  ]


def _build_sync_sections(led_colors: list) -> bytearray:
  led_count = get_led_count()
  colors = [_apply_color_order(r, g, b) for r, g, b in _resample_leds(led_colors)]
  sections = bytearray()
  start = 1
  run_color = colors[0]

  for index in range(2, led_count + 1):
    color = colors[index - 1]
    if color == run_color:
      continue
    sections.extend([start, run_color[0], run_color[1], run_color[2], index - 1])
    start = index
    run_color = color

  sections.extend([start, run_color[0], run_color[1], run_color[2], led_count])
  return sections


def _build_sync_packet(led_colors: list) -> bytes:
  sections = _build_sync_sections(led_colors)
  packet_len = 7 + len(sections)
  packet = bytearray(packet_len)
  packet[0] = 0x53  # 'S'
  packet[1] = 0x43  # 'C'
  packet[2] = (packet_len >> 8) & 0xFF
  packet[3] = packet_len & 0xFF
  packet[4] = _next_cmd_id()
  packet[5] = 0x80
  packet[6 : 6 + len(sections)] = sections
  packet[-1] = sum(packet[:-1]) & 0xFF
  return bytes(packet)


def _write_chunked_hid(dev, payload: bytes) -> bool:
  try:
    for offset in range(0, len(payload), 64):
      chunk = payload[offset : offset + 64]
      bytes_written = dev.write(b"\x00" + chunk)
      if bytes_written <= 0:
        return False
    return True
  except Exception:
    return False


def send_sc_frame(dev, led_colors: list) -> bool:
  """Send per-LED colors using the app's native setSyncScreen packet format."""
  packet = _build_sync_packet(led_colors)
  return _write_chunked_hid(dev, packet)


def open_synclight():
    ifaces = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    if not ifaces:
        return None
    target = next((d for d in ifaces if d.get("usage_page", 0) != 0x0001), ifaces[0])
    d = hid.device()
    d.open_path(target["path"])
    d.set_nonblocking(0)  # Must be blocking to prevent packet drops and hardware desync!
    return d


def bridge_loop():
    global hid_device, bridge_socket
    bridge_stop.clear()
    bridge_status["packets"] = 0

    dev = open_synclight()
    if dev is None:
        bridge_status["connected"] = False
        return

    hid_device = dev
    bridge_status["connected"] = True

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
    sock.settimeout(0.5)
    sock.bind((config["ip"], config["port"]))
    bridge_socket = sock

    last_mapped = []
    last_map_key = None
    cached_zone_indices = []

    try:
        while not bridge_stop.is_set():
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            # DRGB: byte 0 = 0x02, byte 1 = timeout, then R,G,B per LED
            if len(data) < 5 or data[0] != 0x02:
                continue

            rgb_data = data[2:]
            n_src = len(rgb_data) // 3
            if n_src == 0:
                continue

            # Map Prismatik zones → device LEDs (configurable led_count)
            offset  = config.get("zone_offset", 0)
            reverse = config.get("zone_reverse", False)
            led_count = get_led_count()
            map_key = (n_src, led_count, offset, reverse)

            if map_key != last_map_key:
                cached_zone_indices = []
                for i in range(led_count):
                    idx = int(((i + 0.5) * n_src) / led_count)
                    idx = max(0, min(n_src - 1, idx))
                    if reverse:
                        idx = n_src - 1 - idx
                    cached_zone_indices.append((idx + offset) % n_src)
                last_map_key = map_key

            mapped = [
                (rgb_data[idx * 3], rgb_data[idx * 3 + 1], rgb_data[idx * 3 + 2])
                for idx in cached_zone_indices
            ]

            if mapped != last_mapped:
                send_sc_frame(dev, mapped)
                mid = mapped[len(mapped) // 2]
                bridge_status["led_color"] = list(mid)
                bridge_status["packets"] += 1
                if config.get("debug_view", False):
                    bridge_status["input_colors"] = [(rgb_data[i * 3], rgb_data[i * 3 + 1], rgb_data[i * 3 + 2]) for i in range(n_src)]
                    bridge_status["output_colors"] = mapped
                    bridge_status["mapping_indices"] = cached_zone_indices
                last_mapped = mapped

    except Exception:
        pass
    finally:
        send_sc_frame(dev, [(0, 0, 0)] * get_led_count())
        dev.close()
        sock.close()
        bridge_socket = None
        bridge_status["connected"] = False
        hid_device = None


def start_bridge() -> bool:
    global bridge_thread
    if bridge_thread and bridge_thread.is_alive():
        return False
    bridge_stop.clear()
    bridge_thread = threading.Thread(target=bridge_loop, daemon=True)
    bridge_thread.start()
    return True


def stop_bridge(timeout: float = 3.0) -> bool:
    bridge_stop.set()
    if bridge_socket is not None:
        try:
            bridge_socket.close()
        except Exception:
            pass
    if bridge_thread:
        bridge_thread.join(timeout=timeout)
    return not (bridge_thread and bridge_thread.is_alive())


def restart_bridge() -> bool:
    with bridge_lock:
        stopped = stop_bridge()
        started = start_bridge()
    return stopped and (started or (bridge_thread is not None and bridge_thread.is_alive()))

# ── Boot (Task Scheduler) ─────────────────────────────────────────────────────

def set_boot(enabled: bool):
    if getattr(sys, 'frozen', False):
        exe = f'"{Path(sys.executable).resolve()}"'
    else:
        exe = f'"{Path(sys.executable).parent / "pythonw.exe"}" "{Path(__file__).resolve()}"'

    if enabled:
        # Remove any registry-based autostart set by the installer first
        subprocess.run(
            ["reg", "delete",
             r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
             "/v", "SynclightBridge", "/f"],
            capture_output=True,
        )
        subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME,
             "/SC", "ONLOGON", "/TR", exe, "/RL", "HIGHEST", "/F"],
            capture_output=True,
        )
    else:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
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
    <h3>LED Hardware Alignment</h3>
    <p style="font-size:12px;color:#777;margin-bottom:12px">Shift indices to align physical lights with screen edges in real-time.</p>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px">
      <span style="font-size:13px;width:60px">Rotation</span>
      <button class="btn btn-s" style="padding:6px 14px" onclick="shiftMapping(-1)">&#8592; -1</button>
      <span id="map-offset" style="font-size:16px;font-weight:bold;width:30px;text-align:center">0</span>
      <button class="btn btn-s" style="padding:6px 14px" onclick="shiftMapping(1)">+1 &#8594;</button>
    </div>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px">
      <span style="font-size:13px;width:60px">Reverse</span>
      <label class="sw"><input type="checkbox" id="map-rev" onchange="toggleRev()"><span class="sl"></span></label>
    </div>
    <div style="display:flex;gap:10px;align-items:center;">
      <span style="font-size:13px;width:60px">Color Order</span>
      <select id="color-order" onchange="changeColorOrder()" style="background:#252545;color:#e0e0e0;border:none;padding:5px 8px;border-radius:4px;outline:none;font-size:13px;">
        <option value="RGB">RGB (Standard)</option>
        <option value="GRB">GRB</option>
        <option value="BGR">BGR</option>
        <option value="RBG">RBG</option>
        <option value="GBR">GBR</option>
        <option value="BRG">BRG</option>
      </select>
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
      <div>
        <label>LED Count</label>
        <input type="number" id="led_count" placeholder="80" min="1" max="240">
      </div>
    </div>
    <div class="togrow" style="margin-bottom:16px">
      <span class="toglabel">Run on System Boot</span>
      <label class="sw"><input type="checkbox" id="boot"><span class="sl"></span></label>
    </div>
    <div class="togrow" style="margin-bottom:16px">
      <span class="toglabel">Show Live Debug Panel</span>
      <label class="sw"><input type="checkbox" id="debug_view"><span class="sl"></span></label>
    </div>
    <button class="btn btn-p" onclick="save()">Save &amp; Restart Bridge</button>
  </div>

  <div class="card" id="debug-card" style="display:none">
    <h3>Live Debug View</h3>
    <div style="font-size:12px;color:#777;margin-bottom:4px">Prismatik Zones (Hover to see Zone ID & Color)</div>
    <div id="strip-in" style="display:flex;gap:3px;flex-wrap:wrap;margin-bottom:12px"></div>
    <div style="font-size:12px;color:#777;margin-bottom:4px">LED Hardware Output (Hover to see mapped Region & Color)</div>
    <div id="strip-out" style="display:flex;gap:3px;flex-wrap:wrap"></div>
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
function showMsg(text, isError=false){
  const m=document.getElementById('umsg');
  m.style.display='block';
  m.style.color=isError?'#ff4455':'#888';
  m.textContent=text;
}

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
    if(document.activeElement.id !== 'ip') { document.getElementById('ip').value=d.config.ip; }
    if(document.activeElement.id !== 'port') { document.getElementById('port').value=d.config.port; }
    if(document.activeElement.id !== 'led_count') { document.getElementById('led_count').value=d.config.led_count || 80; }
    if(document.activeElement.id !== 'boot') { document.getElementById('boot').checked=d.config.run_on_boot; }
    if(document.activeElement.id !== 'debug_view') { document.getElementById('debug_view').checked=!!d.config.debug_view; }
    document.getElementById('ver').textContent=d.version;
    document.getElementById('map-offset').textContent = d.config.zone_offset !== undefined ? d.config.zone_offset : 0;
    if(document.activeElement.id !== 'map-rev') { document.getElementById('map-rev').checked = d.config.zone_reverse || false; }
    if(document.activeElement.id !== 'color-order') { document.getElementById('color-order').value = d.config.color_order || 'RGB'; }
    document.getElementById('debug-card').style.display = d.config.debug_view ? 'block' : 'none';
    if(d.config.debug_view && d.input_colors) {
      document.getElementById('strip-in').innerHTML = d.input_colors.map((c,i) => `<div title="Prismatik Zone ${i}: RGB(${c[0]},${c[1]},${c[2]})" style="width:28px;height:28px;border-radius:3px;background:rgb(${c[0]},${c[1]},${c[2]});border:1px solid #335;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:bold;color:#fff;text-shadow:0 0 3px #000, 0 0 3px #000;">${i}</div>`).join('');
    }
    if(d.config.debug_view && d.output_colors && d.mapping_indices) {
      document.getElementById('strip-out').innerHTML = d.output_colors.map((c,i) => `<div title="LED ${i} (mapped from Zone ${d.mapping_indices[i]}): RGB(${c[0]},${c[1]},${c[2]})" style="position:relative;width:28px;height:28px;border-radius:3px;background:rgb(${c[0]},${c[1]},${c[2]});border:1px solid #335;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:bold;color:#fff;text-shadow:0 0 3px #000, 0 0 3px #000;margin-bottom:14px">${i}<div style="position:absolute;bottom:-16px;font-size:10px;color:#888;font-weight:normal;text-shadow:none">z${d.mapping_indices[i]}</div></div>`).join('');
    }
    if(!d.config.debug_view){
      document.getElementById('strip-in').innerHTML = '';
      document.getElementById('strip-out').innerHTML = '';
    }
  }catch(e){}
}
async function shiftMapping(delta){
  const el = document.getElementById('map-offset');
  const next = (parseInt(el.textContent) || 0) + delta;
  el.textContent = next;
  await fetch('/api/mapping', {method:'POST', body:JSON.stringify({zone_offset: next})});
}
async function toggleRev(){
  const rev = document.getElementById('map-rev').checked;
  await fetch('/api/mapping', {method:'POST', body:JSON.stringify({zone_reverse: rev})});
}
async function changeColorOrder(){
  const val = document.getElementById('color-order').value;
  await fetch('/api/mapping', {method:'POST', body:JSON.stringify({color_order: val})});
}
async function save(){
  const portRaw = parseInt(document.getElementById('port').value, 10);
  const ledRaw = parseInt(document.getElementById('led_count').value, 10);
  const safePort = Number.isFinite(portRaw) ? portRaw : 21324;
  const safeLedCount = Number.isFinite(ledRaw) ? ledRaw : 80;
  showMsg('Saving settings and restarting bridge...');
  const res = await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ip:document.getElementById('ip').value,
      port:safePort,
      led_count:safeLedCount,
      run_on_boot:document.getElementById('boot').checked,
      debug_view:document.getElementById('debug_view').checked})});
  const body = await res.json();
  showMsg(body.ok ? 'Saved. Bridge restarted.' : (body.error || 'Save failed.'), !body.ok);
  setTimeout(poll,500);
}
async function doRestart(){
  showMsg('Restarting bridge...');
  const res = await fetch('/api/restart',{method:'POST'});
  const body = await res.json();
  showMsg(body.ok ? 'Bridge restarted.' : (body.error || 'Restart failed.'), !body.ok);
  setTimeout(poll,500);
}
async function checkUpdate(){
  showMsg('Checking for updates...');
  try{
    const d=await(await fetch('/api/check_update')).json();
    if(d.error){showMsg('Update check failed: '+d.error,true);}
    else if(d.update_available){
      const m=document.getElementById('umsg');
      m.style.display='block';
      m.style.color='#888';
      m.innerHTML='Update available: v'+d.latest+' (current: v'+d.current+') — <a href="https://github.com/GITHUB_REPO_PLACEHOLDER/releases" target="_blank" style="color:#00c8ff">Download</a>';
    }
    else{showMsg('You are up to date (v'+d.current+')');}
  }catch(e){
    showMsg('Update check failed: network error', true);
  }
}
poll(); setInterval(poll,500);
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


@app.route("/api/mapping", methods=["POST"])
def api_mapping():
    data = request.get_json(force=True)
    if "zone_offset" in data:
        config["zone_offset"] = int(data["zone_offset"])
    if "zone_reverse" in data:
        config["zone_reverse"] = bool(data["zone_reverse"])
    if "color_order" in data:
        config["color_order"] = str(data["color_order"])
    save_config()
    return jsonify({"ok": True})


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True)
    changed = False
    if "ip" in data:
        config["ip"] = data["ip"]
        changed = True
    if "port" in data:
        config["port"] = _safe_int(data["port"], config.get("port", 21324), 1, 65535)
        changed = True
    if "led_count" in data:
        config["led_count"] = _safe_int(data["led_count"], get_led_count(), 1, 240)
        changed = True
    if "debug_view" in data:
        config["debug_view"] = bool(data["debug_view"])
        changed = True
    if "run_on_boot" in data:
        set_boot(bool(data["run_on_boot"]))
    if changed:
        save_config()
        restarted = restart_bridge()
        if not restarted:
            return jsonify({"ok": False, "error": "Bridge restart timed out"})
    return jsonify({"ok": True})


@app.route("/api/restart", methods=["POST"])
def api_restart():
    restarted = restart_bridge()
    if not restarted:
        return jsonify({"ok": False, "error": "Bridge restart timed out"})
    return jsonify({"ok": True})


@app.route("/api/check_update")
def api_check_update():
  try:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urlreq.Request(
      url,
      headers={
        "User-Agent": "synclight-bridge",
        "Accept": "application/vnd.github+json",
      },
    )
    with urlreq.urlopen(req, timeout=5) as r:
      data = json.loads(r.read())
    if "tag_name" not in data:
      return jsonify({"error": data.get("message", "Invalid release response")})
    latest = str(data["tag_name"]).lstrip("v")
    return jsonify({
      "current": VERSION,
      "latest": latest,
      "update_available": latest != VERSION,
    })
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

def _watchdog():
    """Restart the bridge if its thread exits unexpectedly (not via stop_bridge)."""
    import time
    while True:
        time.sleep(5)
        if bridge_stop.is_set():
            continue
        if bridge_thread is None or not bridge_thread.is_alive():
            start_bridge()


def main():
    load_config()
    start_bridge()

    threading.Thread(target=_watchdog, daemon=True, name="BridgeWatchdog").start()

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
