import numpy as np
import psutil
import torch
import torch.nn as nn
import pennylane as qml

WINDOW = 30   # seconds of history per decision
N_FEAT = 8

def net_totals():
    nics = psutil.net_io_counters(pernic=True)
    return (sum(v.bytes_sent for v in nics.values()),
            sum(v.bytes_recv for v in nics.values()))

def established():
    try:
        return sum(1 for c in psutil.net_connections(kind="tcp") if c.status == "ESTABLISHED")
    except Exception:
        return 0

def window_features(sent, recv, est):
    sent = np.asarray(sent, float); recv = np.asarray(recv, float); est = np.asarray(est, float)
    ms, mr = sent.mean(), recv.mean()
    def steady(x, m):
        return 0.0 if m < 1 else 1.0 / (1.0 + x.std() / m)
    return np.array([
        np.log1p(ms),                      # outbound rate
        np.log1p(mr),                      # inbound rate
        steady(sent, ms),                  # how steady outbound is (leaks are steady)
        steady(recv, mr),
        est.mean(),                        # open connections
        ms / (ms + mr + 1.0),              # outbound share
        np.log1p(sent.max() / (ms + 1.0)), # burstiness
        float((sent > 0).mean()),          # fraction of seconds sending
    ])

def make_windows(sent, recv, est, step=3):
    return np.array([window_features(sent[i:i+WINDOW], recv[i:i+WINDOW], est[i:i+WINDOW])
                     for i in range(0, len(sent) - WINDOW + 1, step)])

class ClassicalAE(nn.Module):
    def __init__(self):
        super().__init__()
        self.enc = nn.Sequential(nn.Linear(N_FEAT, 6), nn.ReLU(), nn.Linear(6, 4))
        self.dec = nn.Sequential(nn.Linear(4, 6), nn.ReLU(), nn.Linear(6, N_FEAT), nn.Sigmoid())
    def forward(self, x):
        return self.dec(self.enc(x))

class HybridQAE(nn.Module):
    """8 features -> 4 angles -> 4-qubit circuit (the quantum bottleneck) -> 8 features"""
    def __init__(self):
        super().__init__()
        dev = qml.device("default.qubit", wires=4)
        @qml.qnode(dev, interface="torch")
        def circuit(inputs, weights):
            qml.AngleEmbedding(inputs, wires=range(4))
            qml.BasicEntanglerLayers(weights, wires=range(4))
            return [qml.expval(qml.PauliZ(i)) for i in range(4)]
        self.enc = nn.Sequential(nn.Linear(N_FEAT, 4), nn.Sigmoid())
        self.q = qml.qnn.TorchLayer(circuit, {"weights": (3, 4)})
        self.dec = nn.Sequential(nn.Linear(4, 6), nn.ReLU(), nn.Linear(6, N_FEAT), nn.Sigmoid())
    def forward(self, x):
        return self.dec(self.q(self.enc(x) * 3.14159265))