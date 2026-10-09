import os, sys, time, csv
from datetime import datetime
import psutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

label = sys.argv[1] if len(sys.argv) > 1 else "normal"   # normal | leak
out_path = os.path.join(DATA_DIR, f"traffic_{label}.csv")

def totals():
    nics = psutil.net_io_counters(pernic=True)
    sent = sum(v.bytes_sent for v in nics.values())
    recv = sum(v.bytes_recv for v in nics.values())
    return sent, recv

def established():
    try:
        return sum(1 for c in psutil.net_connections(kind="tcp") if c.status == "ESTABLISHED")
    except Exception:
        return 0

new_file = not os.path.exists(out_path)
f = open(out_path, "a", newline="")
w = csv.writer(f)
if new_file:
    w.writerow(["ts", "sent_bytes", "recv_bytes", "established"])

print(f"Collecting '{label}' traffic -> {out_path}  (Ctrl+C to stop)")
prev_s, prev_r = totals()
n = 0
try:
    while True:
        time.sleep(1)
        s, r = totals()
        w.writerow([datetime.now().isoformat(timespec="seconds"),
                    s - prev_s, r - prev_r, established()])
        f.flush()
        prev_s, prev_r = s, r
        n += 1
        if n % 30 == 0:
            print(f"  {n} seconds collected")
except KeyboardInterrupt:
    print(f"\nStopped. {n} samples saved.")
finally:
    f.close()