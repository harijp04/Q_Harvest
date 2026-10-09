import os, joblib
import numpy as np, pandas as pd, torch, torch.nn as nn
from sklearn.preprocessing import MinMaxScaler
from live_core import make_windows, ClassicalAE, HybridQAE

torch.manual_seed(0); np.random.seed(0)
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(BASE, "..", "data"))
MODELS = os.path.normpath(os.path.join(BASE, "..", "models"))
os.makedirs(MODELS, exist_ok=True)
EPOCHS = 80

def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    return d["sent_bytes"].values, d["recv_bytes"].values, d["established"].values

def train(model, X, bs=32, lr=0.01):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    X = torch.tensor(X, dtype=torch.float32)
    for ep in range(EPOCHS):
        perm = torch.randperm(len(X)); tot = 0.0
        for i in range(0, len(X), bs):
            b = X[perm[i:i+bs]]
            opt.zero_grad()
            loss = nn.functional.mse_loss(model(b), b)
            loss.backward(); opt.step()
            tot += loss.item() * len(b)
        if (ep + 1) % 20 == 0:
            print(f"   epoch {ep+1}/{EPOCHS}  loss {tot/len(X):.6f}")
    model.eval()
    return model

def errors(model, X):
    with torch.no_grad():
        x = torch.tensor(X, dtype=torch.float32)
        return torch.mean((model(x) - x) ** 2, dim=1).numpy()

normal = load("traffic_normal.csv")
if normal is None:
    raise SystemExit("data/traffic_normal.csv missing - run: python collector.py normal")
Xn = make_windows(*normal, step=3)
print(f"normal windows: {len(Xn)}")
if len(Xn) < 60:
    raise SystemExit("Not enough normal data - record at least ~10 more minutes.")

n_val = max(10, int(0.2 * len(Xn)))
Xtr_raw, Xval_raw = Xn[:-(n_val + 10)], Xn[-n_val:]   # chronological split with a gap
scaler = MinMaxScaler().fit(Xtr_raw)
Xtr, Xval = scaler.transform(Xtr_raw), scaler.transform(Xval_raw)

leak = load("traffic_leak.csv")
Xleak = scaler.transform(make_windows(*leak, step=3)) if leak is not None else None

models = {"classical": ClassicalAE(), "quantum": HybridQAE()}
thresholds, rows = {}, []
for name, m in models.items():
    print(f"\nTraining {name} autoencoder ...")
    train(m, Xtr)
    thr = float(np.percentile(errors(m, Xval), 95))
    thresholds[name] = thr
    torch.save(m.state_dict(), os.path.join(MODELS, f"live_{name}.pth"))
    ev, el = errors(m, Xval), (errors(m, Xleak) if Xleak is not None else None)
    rows.append((name, thr, (ev > thr).mean() * 100, ev.mean(),
                 (el > thr).mean() * 100 if el is not None else float("nan"),
                 el.mean() if el is not None else float("nan")))

joblib.dump(scaler, os.path.join(MODELS, "live_scaler.pkl"))
joblib.dump(thresholds, os.path.join(MODELS, "live_thresholds.pkl"))

print("\n" + "=" * 86)
print(f"{'model':<11}{'threshold':>12}{'false alarms %':>17}{'mean err (normal)':>20}{'LEAK flagged %':>16}{'mean err (leak)':>16}")
for r in rows:
    print(f"{r[0]:<11}{r[1]:>12.6f}{r[2]:>17.1f}{r[3]:>20.6f}{r[4]:>16.1f}{r[5]:>16.6f}")
print("=" * 86)