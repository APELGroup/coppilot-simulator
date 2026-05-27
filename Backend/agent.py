"""
Edge-device agent (mock) — simulates a Raspberry Pi.

Runs two things concurrently:
  1. Telemetry loop  — POSTs live readings to the backend every INTERVAL seconds.
  2. HTTP server     — listens on --port (default 8765) for backend requests.
                       POST /flexibility  → runs the flexibility estimation script
                                            and returns results as JSON.

Install deps:
    pip install requests

Run:
    python agent.py --id pi-01 --name "Pi #1" --node "substation-a" --backend http://localhost:8000
    python agent.py --id pi-02 --name "Pi #2" --node "substation-a" --backend http://localhost:8000 --port 8766
"""

import argparse
import json
import math
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

INTERVAL = 5
MAX_BACKOFF = 60

_tick = 0
_device_id = ""   # set in main() before starting the HTTP server


# ── Telemetry ─────────────────────────────────────────────────────────────────

def collect_readings() -> dict:
    global _tick
    _tick += 1
    t = _tick * INTERVAL
    return {
        "power_p":       round(2.5 + 0.8 * math.sin(t / 30) + random.uniform(-0.05, 0.05), 3),
        "power_q":       round(1.0 + 0.3 * math.sin(t / 20) + random.uniform(-0.02, 0.02), 3),
        "voltage_v":     round(230 + 5   * math.sin(t / 40) + random.uniform(-0.5,  0.5),  2),
        "temperature_c": round(45  + 5   * math.sin(t / 60) + random.uniform(-1,    1),    1),
        "cpu_percent":   round(random.uniform(20, 80), 1),
    }


# ── Flexibility estimation script ─────────────────────────────────────────────
# Replace this function with real measurements when deploying on actual hardware.

def run_flexibility_script(device_id: str = "") -> dict:
    """
    Dummy Flexibility Operating Region (FOR) for this device.
    Parameters are derived from the device ID so each Pi produces a distinct shape.
    Replace with real measurements when deploying on actual hardware.
    """
    # Derive stable per-device parameters from the ID
    seed = sum(ord(c) for c in device_id)
    rng = random.Random(seed)

    steps = 15
    k = 10
    P_C = 0.0                      # centred at origin — negative P = reverse power flow
    Q_C = 0.0
    P_R = rng.uniform(0.8, 1.4)   # radius differs per device
    Q_R = rng.uniform(0.5, 1.0)
    p_phase = rng.uniform(0, math.pi)   # time-variation phase differs too
    q_phase = rng.uniform(0, math.pi)

    timestamps = [f"00:{str(m).zfill(2)}" for m in range(steps)]

    polytopes = []
    for t in range(steps):
        p_sc = 1 + 0.15 * math.sin(2 * math.pi * t / steps + p_phase) + random.uniform(-0.05, 0.05)
        q_sc = 1 + 0.10 * math.cos(2 * math.pi * t / steps + q_phase) + random.uniform(-0.03, 0.03)
        verts = []
        for i in range(k):
            angle = 2 * math.pi * i / k
            verts.append([
                round(P_C + P_R * p_sc * math.cos(angle), 3),
                round(Q_C + Q_R * q_sc * math.sin(angle), 3),
            ])
        polytopes.append({"t": timestamps[t], "vertices": verts})

    return {
        "window_minutes": steps,
        "step_minutes": 1,
        "timestamps": timestamps,
        "polytopes": polytopes,
    }


# ── HTTP server ───────────────────────────────────────────────────────────────

class AgentHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[agent-http] {fmt % args}")

    def do_POST(self):
        if self.path == "/flexibility":
            result = run_flexibility_script(_device_id)
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def start_http_server(port: int) -> None:
    server = HTTPServer(("0.0.0.0", port), AgentHandler)
    print(f"[agent] HTTP server listening on port {port}")
    server.serve_forever()


# ── Registration & telemetry loop ─────────────────────────────────────────────

def register(session: requests.Session, backend: str, device_id: str,
             name: str, node_id: str, port: int) -> None:
    backoff = 1
    while True:
        try:
            r = session.post(
                f"{backend}/devices/register",
                json={"id": device_id, "name": name, "node_id": node_id,
                      "extra": {"agent_port": port}},
                timeout=10,
            )
            r.raise_for_status()
            print(f"[agent] Registered '{name}' ({device_id}) → node '{node_id}'")
            return
        except Exception as exc:
            print(f"[agent] Registration failed ({exc}), retrying in {backoff}s…")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)


def run_telemetry_loop(session: requests.Session, backend: str, device_id: str) -> None:
    backoff = 1
    while True:
        try:
            readings = collect_readings()
            r = session.post(
                f"{backend}/devices/telemetry",
                json={"device_id": device_id, "readings": readings},
                timeout=10,
            )
            r.raise_for_status()
            backoff = 1
            print(f"[agent] P={readings['power_p']} kW  Q={readings['power_q']} kVAR")
        except Exception as exc:
            print(f"[agent] Telemetry error ({exc}), retrying in {backoff}s…")
            time.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
            continue
        time.sleep(INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="DT Lab mock edge-device agent")
    parser.add_argument("--id",      required=True,          help="Device ID, e.g. pi-01")
    parser.add_argument("--name",    required=True,          help="Display name")
    parser.add_argument("--node",    default="default-node", help="Edge Node ID")
    parser.add_argument("--backend", required=True,          help="Backend URL, e.g. http://localhost:8000")
    parser.add_argument("--port",    type=int, default=8765, help="Local HTTP server port (default 8765)")
    args = parser.parse_args()

    global _device_id
    _device_id = args.id

    backend = args.backend.rstrip("/")
    session = requests.Session()

    print(f"[agent] Starting — id: {args.id}  node: {args.node}  backend: {backend}")

    # Start HTTP server in background thread
    t = threading.Thread(target=start_http_server, args=(args.port,), daemon=True)
    t.start()

    # Register with backend (includes agent_port so backend knows where to call us)
    register(session, backend, args.id, args.name, args.node, args.port)

    # Telemetry loop (main thread)
    run_telemetry_loop(session, backend, args.id)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[agent] Stopped.")
        sys.exit(0)
