import os, json, time, joblib, collections
from datetime import datetime
import numpy as np
import torch
from live_core import WINDOW, net_totals, established, window_features, ClassicalAE, HybridQAE

BASE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.normpath(os.path.join(BASE, "..", "models"))
OUT = os.path.join(BASE, "monitor_status.json")

scaler = joblib.load(os.path.join(MODELS, "live_scaler.pkl"))
thr = joblib.load(os.path.join(MODELS, "live_thresholds.pkl"))
c_model, q_model = ClassicalAE(), HybridQAE()
c_model.load_state_dict(torch.load(os.path.join(MODELS, "live_classical.pth"), weights_only=True))
q_model.load_state_dict(torch.load(os.path.join(MODELS, "live_quantum.pth"), weights_only=True))
c_model.eval(); q_model.eval()

def err(model, x):
    with torch.no_grad():
        t = torch.tensor(x, dtype=torch.float32)
        return float(torch.mean((model(t) - t) ** 2))

sent, recv, est = (collections.deque(maxlen=WINDOW) for _ in range(3))
history = collections.deque(maxlen=120)
events = collections.deque(maxlen=8)
streak, alerting, tick = 0, False, 0
c_err = q_err = 0.0
prev_s, prev_r = net_totals()
print(f"Monitoring (window {WINDOW}s). Thresholds: {thr}. Ctrl+C to stop.")

try:
    while True:
        time.sleep(1)
        s, r = net_totals()
        sent.append(s - prev_s); recv.append(r - prev_r); est.append(established())
        prev_s, prev_r = s, r
        tick += 1
        warm = len(sent) / WINDOW
        out_kbps = float(np.mean(list(sent)[-5:])) / 1024

        if len(sent) == WINDOW and tick % 3 == 0:
            x = scaler.transform(window_features(sent, recv, est).reshape(1, -1))
            c_err, q_err = err(c_model, x), err(q_model, x)
            streak = streak + 1 if q_err > thr["quantum"] else 0
            now = datetime.now().strftime("%H:%M:%S")
            if streak >= 2 and not alerting:
                alerting = True
                events.appendleft({"time": now, "event": "ALERT: sustained anomaly in outbound traffic pattern",
                                   "q_err": round(q_err, 5)})
            elif streak == 0 and alerting:
                alerting = False
                events.appendleft({"time": now, "event": "Back to normal", "q_err": round(q_err, 5)})
            history.append({"t": now, "c": c_err, "q": q_err, "out": out_kbps})

        state = "WARMUP" if warm < 1 else ("ALERT" if alerting else "NORMAL")
        status = {"state": state, "warm": warm, "out_kbps": out_kbps,
                  "in_kbps": float(np.mean(list(recv)[-5:])) / 1024,
                  "established": int(est[-1]),
                  "c_err": c_err, "q_err": q_err,
                  "c_thr": thr["classical"], "q_thr": thr["quantum"],
                  "history": list(history), "events": list(events)}
        tmp = OUT + ".tmp"
        with open(tmp, "w") as f:
            json.dump(status, f)
        os.replace(tmp, OUT)
except KeyboardInterrupt:
    print("Stopped.")