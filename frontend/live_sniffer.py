"""
Q-Harvest :: live_sniffer.py (FINAL STABLE VERSION)
"""
import os
import json
import time
import threading
import collections
from datetime import datetime

import numpy as np
import joblib
import torch
import torch.nn as nn
import pennylane as qml
from pennylane import qnn
from scapy.all import sniff, IP, TCP, UDP

# 1. PATHS
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "models"))
OUTPUT_JSON = os.path.join(BASE_DIR, "live_status.json")

SCALER_PATH = os.path.join(MODELS_DIR, "scaler.pkl")
PCA_PATH = os.path.join(MODELS_DIR, "pca_transformer.pkl")
PCA_SCALER_PATH = os.path.join(MODELS_DIR, "pca_angle_scaler.pkl")
QUANTUM_MODEL_PATH = os.path.join(MODELS_DIR, "quantum_autoencoder.pth")
QUANTUM_THRESHOLD_PATH = os.path.join(MODELS_DIR, "quantum_threshold.pkl")

# 2. QUANTUM MODEL DEFINITION
N_QUBITS = 4
N_LAYERS = 3
dev = qml.device("default.qubit", wires=N_QUBITS)

@qml.qnode(dev, interface="torch")
def quantum_circuit(inputs, weights):
    qml.AngleEmbedding(inputs, wires=range(N_QUBITS))
    qml.BasicEntanglerLayers(weights, wires=range(N_QUBITS))
    return [qml.expval(qml.PauliZ(i)) for i in range(N_QUBITS)]

weight_shapes = {"weights": (N_LAYERS, N_QUBITS)}

class QuantumAutoencoder(nn.Module):
    def __init__(self, qnode, weight_shapes):
        super(QuantumAutoencoder, self).__init__()
        self.quantum_layer = qnn.TorchLayer(qnode, weight_shapes)
        self.classical_output = nn.Linear(4, 11)

    def forward(self, x):
        q_out = self.quantum_layer(x)
        return self.classical_output(q_out)

# 3. LOAD ARTIFACTS
print("[Q-Harvest] Loading preprocessing artifacts and quantum model...")
scaler = joblib.load(SCALER_PATH)
pca = joblib.load(PCA_PATH)
pca_scaler = joblib.load(PCA_SCALER_PATH)
quantum_threshold = float(joblib.load(QUANTUM_THRESHOLD_PATH))

model = QuantumAutoencoder(quantum_circuit, weight_shapes)
model.load_state_dict(torch.load(QUANTUM_MODEL_PATH, map_location="cpu", weights_only=True))
model.eval()
print(f"[Q-Harvest] All artifacts loaded successfully. Threshold: {quantum_threshold:.6f}")

# 4. CONNECTION TRACKER (Prevents flickering by aggregating traffic over 2 seconds)
class ConnectionTracker:
    WINDOW_SECONDS = 2.0

    def __init__(self):
        self.lock = threading.Lock()
        self.connections = {}
        self.window_records = collections.deque()

    def _key(self, src_ip, dst_ip, dst_port, proto):
        return (src_ip, dst_ip, dst_port, proto)

    def process_packet(self, pkt):
        if IP not in pkt: return
        ts = time.time()
        ip_layer = pkt[IP]
        src_ip, dst_ip = ip_layer.src, ip_layer.dst
        pkt_len = len(pkt)

        if TCP in pkt:
            proto, dst_port, flags = "tcp", pkt[TCP].dport, str(pkt[TCP].flags)
        elif UDP in pkt:
            proto, dst_port, flags = "udp", pkt[UDP].dport, ""
        else: return

        with self.lock:
            key = self._key(src_ip, dst_ip, dst_port, proto)
            record = self.connections.get(key)
            if record is None:
                record = {"start_time": ts, "last_time": ts, "src_bytes": 0, "syn_seen": False, "synack_seen": False}
                self.connections[key] = record
                self.window_records.append(record)

            record["last_time"] = ts
            record["src_bytes"] += pkt_len

            if "S" in flags and "A" not in flags: record["syn_seen"] = True
            if "S" in flags and "A" in flags: record["synack_seen"] = True

    def compute_feature_vector(self):
        with self.lock:
            records = list(self.window_records)
            self.window_records.clear()
            self.connections.clear()

        if not records:
            # Return a safe "idle" vector so the dashboard stays green
            return np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0], dtype=np.float64)

        total = len(records)
        duration = float(np.mean([r["last_time"] - r["start_time"] for r in records]))
        src_bytes = float(np.sum([r["src_bytes"] for r in records]))
        
        syn_only_count = sum(1 for r in records if r["syn_seen"] and not r["synack_seen"])
        serror_rate = syn_only_count / total if total > 0 else 0.0

        return np.array([
            duration, src_bytes, 0.0, float(total), float(total),
            serror_rate, serror_rate, 0.0, 0.0, 1.0 - serror_rate, serror_rate
        ], dtype=np.float64)

tracker = ConnectionTracker()

# 5. INFERENCE LOOP
def run_inference_cycle():
    raw_features = tracker.compute_feature_vector().reshape(1, -1)

    scaled_11 = scaler.transform(raw_features)
    pca_4 = pca.transform(scaled_11)
    angle_ready = pca_scaler.transform(pca_4)
    angle_ready = np.clip(angle_ready, 0, np.pi)

    input_tensor = torch.tensor(angle_ready, dtype=torch.float32)
    with torch.no_grad():
        reconstruction = model(input_tensor)
        target_tensor = torch.tensor(scaled_11, dtype=torch.float32)
        mse_error = torch.mean((reconstruction - target_tensor) ** 2).item()

    # Use the exact threshold from training
    is_anomaly = mse_error > quantum_threshold

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "reconstruction_error": round(mse_error, 6),
        "threshold": round(quantum_threshold, 6),
        "is_anomaly": bool(is_anomaly),
        "status": "ATTACK DETECTED" if is_anomaly else "NORMAL"
    }

def write_status(status):
    tmp_path = OUTPUT_JSON + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(status, f, indent=2, default=lambda o: float(o))
    os.replace(tmp_path, OUTPUT_JSON)

# 6. MAIN
print("[Q-Harvest] Starting live packet sniffer (Ctrl+C to stop)...")
sniff_thread = threading.Thread(target=lambda: sniff(prn=tracker.process_packet, store=False), daemon=True)
sniff_thread.start()

try:
    while True:
        time.sleep(ConnectionTracker.WINDOW_SECONDS)
        try:
            status = run_inference_cycle()
            write_status(status)
            print(f"[Q-Harvest] {status['timestamp']} | Error: {status['reconstruction_error']:.6f} | Status: {status['status']}")
        except Exception as e:
            print(f"[Q-Harvest] Warning: Inference cycle skipped due to error: {e}")
except KeyboardInterrupt:
    print("\n[Q-Harvest] Sniffer stopped by user.")