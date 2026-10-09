import os, warnings
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import joblib
import pennylane as qml

warnings.filterwarnings("ignore")
rng = np.random.default_rng(42)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "models"))

FEATURES = ['duration','src_bytes','dst_bytes','count','srv_count',
            'serror_rate','srv_serror_rate','rerror_rate','srv_rerror_rate',
            'same_srv_rate','diff_srv_rate']

# ---------- model definitions (same as app.py) ----------
class ClassicalAutoencoder(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(input_dim, 8), nn.ReLU(), nn.Linear(8, 4))
        self.decoder = nn.Sequential(nn.Linear(4, 8), nn.ReLU(), nn.Linear(8, input_dim), nn.Sigmoid())
    def forward(self, x):
        return self.decoder(self.encoder(x))

class QuantumAutoencoder(nn.Module):
    def __init__(self):
        super().__init__()
        n_qubits, n_layers = 4, 3
        dev = qml.device("default.qubit", wires=n_qubits)
        @qml.qnode(dev, interface="torch")
        def circuit(inputs, weights):
            qml.AngleEmbedding(inputs, wires=range(n_qubits))
            qml.BasicEntanglerLayers(weights, wires=range(n_qubits))
            return [qml.expval(qml.PauliZ(i)) for i in range(n_qubits)]
        self.quantum_layer = qml.qnn.TorchLayer(circuit, {"weights": (n_layers, n_qubits)})
        self.classical_output = nn.Linear(4, 11)
    def forward(self, x):
        return self.classical_output(self.quantum_layer(x))

# ---------- load trained artifacts ----------
scaler = joblib.load(os.path.join(MODELS_DIR, "scaler.pkl"))
pca = joblib.load(os.path.join(MODELS_DIR, "pca_transformer.pkl"))
pca_scaler = joblib.load(os.path.join(MODELS_DIR, "pca_angle_scaler.pkl"))
c_thresh = float(joblib.load(os.path.join(MODELS_DIR, "threshold.pkl")))
q_thresh = float(joblib.load(os.path.join(MODELS_DIR, "quantum_threshold.pkl")))

c_model = ClassicalAutoencoder(11)
c_model.load_state_dict(torch.load(os.path.join(MODELS_DIR, "classical_autoencoder.pth"),
                                   map_location="cpu", weights_only=True))
c_model.eval()

q_model = QuantumAutoencoder()
q_model.load_state_dict(torch.load(os.path.join(MODELS_DIR, "quantum_autoencoder.pth"),
                                   map_location="cpu", weights_only=True))
q_model.eval()

# ---------- scoring ----------
def score(df):
    scaled = scaler.transform(df[FEATURES])
    x = torch.tensor(scaled, dtype=torch.float32)
    with torch.no_grad():
        c_err = torch.mean((x - c_model(x)) ** 2, dim=1).numpy()
        angles = pca_scaler.transform(pca.transform(scaled))
        angles = np.clip(angles, 0, np.pi)
        q_out = q_model(torch.tensor(angles, dtype=torch.float32))
        q_err = torch.mean((x - q_out) ** 2, dim=1).numpy()
    return c_err, q_err

# ---------- scenarios ----------
def load_real_normal(n=300):
    for p in [os.path.join(BASE_DIR, "..", "data", "raw", "KDDTest+.txt"),
              os.path.join(BASE_DIR, "..", "data", "KDDTest+.txt")]:
        if os.path.exists(p):
            idx = [0, 4, 5, 22, 23, 24, 25, 26, 27, 28, 29, 41]
            df = pd.read_csv(p, header=None, usecols=idx)
            df.columns = FEATURES + ["label"]
            return df[df["label"] == "normal"][FEATURES].sample(n, random_state=42)
    return None

def make_dos(n=200):
    c = rng.integers(150, 512, n)
    return pd.DataFrame({
        'duration': 0.0, 'src_bytes': 0.0, 'dst_bytes': 0.0,
        'count': c, 'srv_count': c,
        'serror_rate': rng.uniform(0.9, 1.0, n), 'srv_serror_rate': rng.uniform(0.9, 1.0, n),
        'rerror_rate': 0.0, 'srv_rerror_rate': 0.0,
        'same_srv_rate': 1.0, 'diff_srv_rate': 0.0})

def make_slow_leak(n=200):
    # ASSUMPTION: long-lived, steady, low-volume transfer, few connections, no errors
    c = rng.integers(1, 5, n)
    return pd.DataFrame({
        'duration': rng.uniform(200, 3000, n),
        'src_bytes': rng.uniform(1500, 6000, n),
        'dst_bytes': rng.uniform(100, 600, n),
        'count': c, 'srv_count': c,
        'serror_rate': 0.0, 'srv_serror_rate': 0.0,
        'rerror_rate': 0.0, 'srv_rerror_rate': 0.0,
        'same_srv_rate': 1.0, 'diff_srv_rate': 0.0})

scenarios = {}
real_normal = load_real_normal()
if real_normal is not None:
    scenarios["Real normal (KDDTest+)"] = real_normal
else:
    print("NOTE: KDDTest+.txt not found, skipping real-normal baseline.\n")
scenarios["Synthetic DoS flood"] = make_dos()
scenarios["Synthetic SLOW LEAK (HNDL)"] = make_slow_leak()

print(f"Thresholds -> classical: {c_thresh:.6f} | quantum: {q_thresh:.6f}\n")
print(f"{'Scenario':<30}{'Classical flagged':>20}{'Quantum flagged':>20}{'Mean C err':>14}{'Mean Q err':>14}")
print("-" * 98)
for name, df in scenarios.items():
    c_err, q_err = score(df)
    print(f"{name:<30}{(c_err > c_thresh).mean()*100:>19.1f}%{(q_err > q_thresh).mean()*100:>19.1f}%"
          f"{c_err.mean():>14.6f}{q_err.mean():>14.6f}")