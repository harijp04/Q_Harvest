"""
Q-Harvest Dummy Cloud Server - Unified local lab detector.

Detects:
- High-rate HTTP DoS
- Slowloris-style connection exhaustion
- Slow data exfiltration simulation
- Normal traffic

LOCAL LAB ONLY: binds to 127.0.0.1:8080.
"""

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import deque
from pathlib import Path
import json
import threading
import time

HOST = "127.0.0.1"
PORT = 8080

BASE_DIR = Path(__file__).resolve().parent
STATUS_FILE = BASE_DIR / "manual_status.json"

lock = threading.Lock()
request_times = deque(maxlen=10000)
upload_events = deque(maxlen=10000)

active_connections = 0
slowloris_since = None

last_state = "NORMAL"


def now():
    return time.time()


def write_status(state, event, req_rate=0.0, upload_rate=0.0, upload_events_10s=0, active=0):
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "state": state,
        "event": event,
        "target": f"http://{HOST}:{PORT}",
        "request_rate_rps": round(req_rate, 2),
        "upload_rate_kbps": round(upload_rate, 2),
        "upload_events_10s": int(upload_events_10s),
        "active_connections": int(active),
    }
    tmp = STATUS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(STATUS_FILE)


class QHarvestServer(ThreadingHTTPServer):
    daemon_threads = True

    def process_request_thread(self, request, client_address):
        global active_connections
        with lock:
            active_connections += 1
        try:
            super().process_request_thread(request, client_address)
        finally:
            with lock:
                active_connections = max(0, active_connections - 1)


def detector_loop():
    global last_state, slowloris_since

    alert_hold_until = 0.0
    latched_state = "NORMAL"
    latched_event = "Traffic within normal demo limits"

    while True:
        time.sleep(1)
        t = now()

        with lock:
            while request_times and t - request_times[0] > 10:
                request_times.popleft()
            while upload_events and t - upload_events[0][0] > 30:
                upload_events.popleft()

            req_rate = float(sum(1 for x in request_times if t - x <= 1))

            recent_uploads = [(ts, size) for ts, size in upload_events if t - ts <= 10]
            upload_count = len(recent_uploads)
            upload_rate = (sum(size for _, size in recent_uploads) / 1024.0) / 10.0

            active = active_connections

        # Require sustained many live connections for Slowloris.
        if active >= 20:
            if slowloris_since is None:
                slowloris_since = t
        else:
            slowloris_since = None

        slowloris_detected = (
            slowloris_since is not None and
            (t - slowloris_since) >= 2.0
        )

        detected_state = "NORMAL"
        detected_event = "Traffic within normal demo limits"

        # Priority: Slowloris -> high-rate DoS -> slow exfiltration.
        if slowloris_detected:
            detected_state = "SLOWLORIS_DETECTED"
            detected_event = f"Slowloris-style connection exhaustion detected ({active} active connections)"
        elif req_rate >= 40:
            detected_state = "DOS_DETECTED"
            detected_event = f"High request-rate DoS-like traffic detected ({req_rate:.0f} req/s)"
        elif upload_count >= 5 and upload_rate >= 1.0:
            detected_state = "SLOW_LEAK_DETECTED"
            detected_event = "Sustained low-rate outbound upload pattern detected"

        if detected_state == "SLOWLORIS_DETECTED":
            latched_state = detected_state
            latched_event = detected_event
            alert_hold_until = t + 8.0
        elif detected_state == "DOS_DETECTED":
            latched_state = detected_state
            latched_event = detected_event
            alert_hold_until = t + 8.0
        elif detected_state == "SLOW_LEAK_DETECTED":
            latched_state = detected_state
            latched_event = detected_event
            alert_hold_until = t + 10.0
        elif t >= alert_hold_until:
            latched_state = "NORMAL"
            latched_event = "Traffic within normal demo limits"

        if latched_state != last_state:
            print(f"[Q-Harvest] {last_state} -> {latched_state}: {latched_event}")
            last_state = latched_state

        write_status(
            latched_state,
            latched_event,
            req_rate,
            upload_rate,
            upload_count,
            active
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "QHarvestDummyCloud/2.0"

    def log_message(self, fmt, *args):
        return

    def _record_request(self):
        with lock:
            request_times.append(now())

    def do_GET(self):
        self._record_request()
        body = json.dumps({
            "service": "Q-Harvest Dummy Cloud",
            "status": "online",
            "message": "Local isolated demo server"
        }).encode()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._record_request()
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length) if length else b""

        with lock:
            upload_events.append((now(), len(data)))

        body = json.dumps({
            "received_bytes": len(data),
            "status": "accepted"
        }).encode()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    print("=" * 72)
    print(" Q-HARVEST DUMMY CLOUD SERVER")
    print("=" * 72)
    print(f" Local target : http://{HOST}:{PORT}")
    print(" Detects      : DoS / Slowloris / Slow Data Leak / Normal")
    print(" Ctrl+C to stop.\n")

    write_status("NORMAL", "Server started")

    threading.Thread(target=detector_loop, daemon=True).start()

    server = QHarvestServer((HOST, PORT), Handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Q-Harvest] Dummy cloud stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
