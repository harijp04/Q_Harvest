import os, joblib
import numpy as np, pandas as pd, torch
from sklearn.metrics import roc_auc_score
from live_core import make_windows, ClassicalAE, HybridQAE

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(BASE, "..", "data"))
MODELS = os.path.normpath(os.path.join(BASE, "..", "models"))

def load(name):
    d = pd.read_csv(os.path.join(DATA, name))
    return d["sent_bytes"].values, d["recv_bytes"].values, d["established"].values

nraw, lraw = load("traffic_normal.csv"), load("traffic_leak.csv")
print(f"leak file: {len(lraw[0])} seconds | median outbound {np.median(lraw[0]):.0f} B/s | "
      f"seconds above 15000 B/s: {(lraw[0] > 15000).sum()}  (expect ~480 if the leak was counted)")

Xn = make_windows(*nraw, step=3)
n_val = max(10, int(0.2 * len(Xn)))
Xval_raw = Xn[-n_val:]
Xleak_raw = make_windows(*lraw, step=3)
scaler = joblib.load(os.path.join(MODELS, "live_scaler.pkl"))
Xval, Xleak = scaler.transform(Xval_raw), scaler.transform(Xleak_raw)

# windows mostly inside the leak: mean outbound above ~15 KB/s (feature 0 is log1p of mean sent)
inside = Xleak_raw[:, 0] > np.log1p(15000)
print(f"leak windows: {len(Xleak)} total, {inside.sum()} mostly inside the leak\n")

def errs(m, X):
    with torch.no_grad():
        x = torch.tensor(X, dtype=torch.float32)
        return torch.mean((m(x) - x) ** 2, dim=1).numpy()

for name, cls in [("classical", ClassicalAE), ("quantum", HybridQAE)]:
    m = cls()
    m.load_state_dict(torch.load(os.path.join(MODELS, f"live_{name}.pth"), weights_only=True))
    m.eval()
    ev, el = errs(m, Xval), errs(m, Xleak)
    y = np.r_[np.zeros(len(ev)), np.ones(inside.sum())]
    auc = roc_auc_score(y, np.r_[ev, el[inside]]) if inside.sum() else float("nan")
    print(f"{name}: AUC = {auc:.3f}   (0.5 = no better than a coin flip, 1.0 = perfect)")
    for p in (99, 95, 90):
        t = np.percentile(ev, p)
        print(f"   threshold = {p}th percentile of normal errors -> "
              f"leak windows detected {(el[inside] > t).mean() * 100:5.1f}%   (false alarms on val set ~{100 - p}%)")
    print()