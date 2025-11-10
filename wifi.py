#!/usr/bin/env python3
"""
Wi-Fi Network Pro Dashboard (Modern Dark Theme + Speedtest Integration + SSID + Health)
Run:  python wifi_pro_dashboard.py
Open: http://127.0.0.1:5000
"""
import os, platform, subprocess, threading, time, csv, re
from collections import deque
from datetime import datetime
from flask import Flask, render_template_string, jsonify
import requests
import speedtest

# ---------------- CONFIG ----------------
WIFI_TARGETS = {
    "Shakti_2.4GHz": "192.168.1.1",
    "SHAKTI_5GHz": "192.168.1.2",
    "Air_Shakti_564_5GHz": "192.168.1.3",
    "Air_Shakti_564_2.4GHz": "192.168.1.4",
    "Air_Shakti_501_2.4GHz": "192.168.1.5",
    "Air_Shakti_501_5GHz": "192.168.1.6",
    "Lawful_Connect_2.4GHz": "192.168.1.7",
    "Lawfull_Conect_5GHz": "192.168.1.8",
    "Airtel_Zerotouch": "192.168.1.9",
    "Airtel_Zerotouch_5G": "192.168.1.10"
}

CHECK_INTERVAL = 8
HISTORY_LENGTH = 300
LOG_FILE = "wifi_pro_log.csv"

# ----------------------------------------
app = Flask(__name__)
status_store = {n: {"ip": i, "status": "Unknown", "last": None, "latency": None} for n, i in WIFI_TARGETS.items()}
history = {n: deque(maxlen=HISTORY_LENGTH) for n in WIFI_TARGETS}
last_status = {n: "Unknown" for n in WIFI_TARGETS}
lock = threading.Lock()

_ping_time_re = re.compile(r'time[=<]\s*([\d\.]+)\s*ms', re.IGNORECASE)
_windows_avg_re = re.compile(r'Average = (\d+)ms', re.IGNORECASE)

def ping_latency(host, timeout=2):
    sys = platform.system().lower()
    cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host] if sys == "windows" else ["ping", "-c", "1", "-W", str(int(timeout)), host]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 1)
        out = p.stdout + p.stderr
    except Exception:
        return False, None
    if p.returncode == 0:
        m = _ping_time_re.search(out) or _windows_avg_re.search(out)
        if m:
            try:
                return True, float(m.group(1))
            except:
                pass
        return True, None
    return False, None

# --- NEW: Get current Wi-Fi SSID ---
def get_current_ssid():
    sys = platform.system().lower()
    try:
        if sys == "windows":
            out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"], text=True)
            m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.MULTILINE)
            if m: return m.group(1).strip()
        elif sys == "linux":
            out = subprocess.check_output(["iwgetid", "-r"], text=True)
            return out.strip()
        elif sys == "darwin":  # macOS
            out = subprocess.check_output(
                ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
                text=True)
            m = re.search(r" SSID: (.+)", out)
            if m: return m.group(1).strip()
    except Exception:
        pass
    return "Unknown"

def run_speedtest():
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        dl = st.download() / 1_000_000
        ul = st.upload() / 1_000_000
        ping = st.results.ping
        return round(dl, 2), round(ul, 2), round(ping, 1)
    except Exception as e:
        print("Speedtest failed:", e)
        return None, None, None

def compute_health(download_mbps):
    if download_mbps is None: return "Unknown", "text-gray-400"
    if download_mbps >= 100: return "Excellent", "text-green-400"
    if download_mbps >= 50: return "Good", "text-yellow-400"
    if download_mbps >= 10: return "Fair", "text-orange-400"
    return "Weak", "text-red-500"

def monitor_loop():
    while True:
        for name, ip in WIFI_TARGETS.items():
            ok, lat = ping_latency(ip)
            status = "UP" if ok else "DOWN"
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with lock:
                status_store[name].update({"ip": ip, "status": status, "last": ts, "latency": lat})
                history[name].append((ts, 1 if ok else 0, lat))
            last_status[name] = status
        time.sleep(CHECK_INTERVAL)

# ---------------- FLASK ----------------
HTML = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>Wi-Fi Pro Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css" />
<style>body{font-family:'Inter',sans-serif}.dataTables_wrapper{padding:1rem}</style>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
<header class="bg-gray-900 border-b border-gray-800 p-4 shadow-xl sticky top-0 z-10">
<div class="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center">
<h1 class="text-2xl font-extrabold text-white flex items-center gap-3">📶 Wi-Fi Pro Dashboard</h1>
<div class="flex flex-wrap justify-center space-x-4 text-sm font-medium text-gray-400">
<span class="p-2 px-3 rounded-md bg-gray-800">Check every <b class="text-white">{{ interval }}s</b></span>
<span class="p-2 px-3 rounded-md bg-gray-800">Networks: <b class="text-white">{{ total }}</b></span>
</div></div></header>

<main class="max-w-7xl mx-auto p-4 md:p-8">
<div class="bg-gray-800 p-6 rounded-xl shadow-2xl mb-6">
  <div class="flex justify-between items-center mb-3">
    <h3 class="text-xl font-semibold">Speedtest (ISP Performance)</h3>
    <button id="runSpeedtest" class="bg-emerald-600 hover:bg-emerald-700 text-white font-medium rounded-lg px-4 py-2 text-sm">Run Speed Test</button>
  </div>
  <div id="speedResult" class="text-gray-400 text-sm"><p>Press “Run Speed Test” to measure your internet speed.</p></div>
</div>

<div class="bg-gray-800 rounded-xl shadow-2xl overflow-x-auto p-6">
<h3 class="text-xl font-semibold mb-4">Live Network Status</h3>
<table id="netTable" class="display w-full text-sm text-left text-gray-400">
<thead><tr><th>Name</th><th>IP</th><th>Status</th><th>Latency (ms)</th><th>Last Checked</th></tr></thead><tbody></tbody>
</table></div>

</main>

<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
<script>
const interval = {{interval}};

function formatStatus(status) {
  if (status === "UP") return `<span class='text-green-400 font-semibold'>UP</span>`;
  if (status === "DOWN") return `<span class='text-red-500 font-semibold'>DOWN</span>`;
  return `<span class='text-gray-400'>${status}</span>`;
}

function renderTable(data) {
  const rows = Object.entries(data).map(([n, d]) => [
    n, d.ip, formatStatus(d.status), d.latency ?? "-", d.last ?? "-"
  ]);
  table.clear(); table.rows.add(rows); table.draw();
}

async function updateAll() {
  const s = await fetch("/api/status").then(r => r.json());
  renderTable(s);
}

let table;
$(document).ready(function() {
  table = $('#netTable').DataTable({
    columns: [
      { title: "Name" },
      { title: "IP" },
      { title: "Status" },
      { title: "Latency" },
      { title: "Last Checked" }
    ],
    paging: false, searching: false, info: false, dom: 'rt'
  });
  updateAll();
  setInterval(updateAll, interval * 1000);
});

// --- SPEEDTEST + Wi-Fi ---
document.getElementById("runSpeedtest").addEventListener("click", async () => {
  const btn = document.getElementById("runSpeedtest");
  const resDiv = document.getElementById("speedResult");
  btn.disabled = true;
  btn.textContent = "Running...";
  resDiv.innerHTML = "<p class='text-yellow-400'>Testing speed...</p>";

  try {
    const res = await fetch("/api/speedtest");
    const j = await res.json();

    if (j.download_mbps) {
      const dlColor = j.download_mbps >= 100 ? "text-green-400"
                      : j.download_mbps >= 50 ? "text-yellow-400"
                      : j.download_mbps >= 10 ? "text-orange-400"
                      : "text-red-500";
      const ulColor = j.upload_mbps >= 50 ? "text-green-400"
                      : j.upload_mbps >= 10 ? "text-yellow-400"
                      : "text-red-500";
      const pingColor = j.ping_ms < 50 ? "text-green-400"
                        : j.ping_ms < 100 ? "text-yellow-400"
                        : "text-red-500";

      resDiv.innerHTML = `
        <div class='mb-2 text-sm'>
          <p>Connected Wi-Fi: <b class='text-emerald-400'>${j.ssid}</b></p>
          <p>Wi-Fi Health: <b class='${j.health_color}'>${j.health}</b></p>
        </div>
        <div class='grid grid-cols-3 gap-4 text-center'>
          <div><p class='${dlColor} text-3xl font-bold'>${j.download_mbps}</p><p class='text-gray-500 text-xs'>Download (Mbps)</p></div>
          <div><p class='${ulColor} text-3xl font-bold'>${j.upload_mbps}</p><p class='text-gray-500 text-xs'>Upload (Mbps)</p></div>
          <div><p class='${pingColor} text-3xl font-bold'>${j.ping_ms}</p><p class='text-gray-500 text-xs'>Ping (ms)</p></div>
        </div>
        <p class='text-xs text-gray-500 mt-2'>Last test at ${j.time}</p>`;
    } else {
      resDiv.innerHTML = "<p class='text-red-400'>Speedtest failed.</p>";
    }
  } catch (e) {
    resDiv.innerHTML = "<p class='text-red-400'>Error running speedtest.</p>";
  }

  btn.disabled = false;
  btn.textContent = "Run Speed Test";
});
</script>
</body></html>"""

@app.route("/")
def index():
    return render_template_string(HTML, interval=CHECK_INTERVAL, total=len(WIFI_TARGETS))

@app.route("/api/status")
def api_status():
    with lock:
        return jsonify(status_store)

@app.route("/api/speedtest")
def api_speedtest():
    ssid = get_current_ssid()
    dl, ul, ping = run_speedtest()
    health, color = compute_health(dl)
    return jsonify({
        "ssid": ssid,
        "download_mbps": dl,
        "upload_mbps": ul,
        "ping_ms": ping,
        "health": health,
        "health_color": color,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    print("Wi-Fi Pro Dashboard running at http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
