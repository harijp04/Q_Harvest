"""Q-Harvest live detector.
Captures TCP/UDP traffic, builds an 11-feature NSL-KDD-inspired window,
and evaluates both Classical and Quantum autoencoders every 2 seconds.

Windows notes:
- Install Npcap with WinPcap API-compatible mode if capture fails.
- Run the terminal as Administrator.
- Use --list-ifaces to see adapters and --iface <name-or-index> to select one.
"""
import argparse
import collections
import json
import os
import threading
import time
import traceback
from datetime import datetime

import joblib
import numpy as np
import pennylane as qml
import torch
import torch.nn as nn
from pennylane import qnn
from scapy.all import AsyncSniffer, IP, TCP, UDP, conf, get_if_list

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "models"))
OUTPUT_JSON = os.path.join(BASE_DIR, "live_status.json")

FEATURES = [
    "duration", "src_bytes", "dst_bytes", "count", "srv_count",
    "serror_rate", "srv_serror_rate", "rerror_rate", "srv_rerror_rate",
    "same_srv_rate", "diff_srv_rate",
]

class ClassicalAutoencoder(nn.Module):
    def __init__(self, input_dim=11):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(input_dim, 8), nn.ReLU(), nn.Linear(8, 4))
        self.decoder = nn.Sequential(nn.Linear(4, 8), nn.ReLU(), nn.Linear(8, input_dim), nn.Sigmoid())

    def forward(self, x):
        return self.decoder(self.encoder(x))

N_QUBITS, N_LAYERS = 4, 3
_qdev = qml.device("default.qubit", wires=N_QUBITS)

@qml.qnode(_qdev, interface="torch")
def quantum_circuit(inputs, weights):
    qml.AngleEmbedding(inputs, wires=range(N_QUBITS))
    qml.BasicEntanglerLayers(weights, wires=range(N_QUBITS))
    return [qml.expval(qml.PauliZ(i)) for i in range(N_QUBITS)]

class QuantumAutoencoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.quantum_layer = qnn.TorchLayer(quantum_circuit, {"weights": (N_LAYERS, N_QUBITS)})
        self.classical_output = nn.Linear(4, 11)

    def forward(self, x):
        return self.classical_output(self.quantum_layer(x))


def load_torch_state(path):
    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        return torch.load(path, map_location="cpu")


def load_system():
    print("[Q-Harvest] Loading models...")
    scaler = joblib.load(os.path.join(MODELS_DIR, "scaler.pkl"))
    pca = joblib.load(os.path.join(MODELS_DIR, "pca_transformer.pkl"))
    pca_scaler = joblib.load(os.path.join(MODELS_DIR, "pca_angle_scaler.pkl"))
    c_thresh = float(joblib.load(os.path.join(MODELS_DIR, "threshold.pkl")))
    q_thresh = float(joblib.load(os.path.join(MODELS_DIR, "quantum_threshold.pkl")))

    c_model = ClassicalAutoencoder()
    c_model.load_state_dict(load_torch_state(os.path.join(MODELS_DIR, "classical_autoencoder.pth")))
    c_model.eval()

    q_model = QuantumAutoencoder()
    q_model.load_state_dict(load_torch_state(os.path.join(MODELS_DIR, "quantum_autoencoder.pth")))
    q_model.eval()
    print(f"[Q-Harvest] Classical threshold={c_thresh:.6f} | Quantum threshold={q_thresh:.6f}")
    return scaler, pca, pca_scaler, c_model, q_model, c_thresh, q_thresh


def interface_rows():
    rows = []
    try:
        for idx, iface in enumerate(conf.ifaces.values()):
            name = str(getattr(iface, "name", "") or "")
            desc = str(getattr(iface, "description", "") or "")
            ip = str(getattr(iface, "ip", "") or "")
            guid = str(getattr(iface, "network_name", "") or getattr(iface, "guid", "") or "")
            rows.append((idx, name, desc, ip, guid))
    except Exception:
        for idx, name in enumerate(get_if_list()):
            rows.append((idx, str(name), "", "", str(name)))
    return rows


def print_interfaces():
    rows = interface_rows()
    print("\nAvailable capture interfaces:")
    for idx, name, desc, ip, guid in rows:
        label = name or guid or "unknown"
        extra = " | ".join(x for x in [desc, f"IP={ip}" if ip and ip != "0.0.0.0" else ""] if x)
        print(f"  [{idx}] {label}" + (f" | {extra}" if extra else ""))
    print()


def resolve_iface(value):
    if value is None:
        # Prefer Scapy's routed interface for normal outbound traffic.
        try:
            routed = conf.route.route("8.8.8.8")[0]
            if routed:
                return routed
        except Exception:
            pass
        return conf.iface

    rows = interface_rows()
    if str(value).isdigit():
        idx = int(value)
        if 0 <= idx < len(rows):
            # conf.ifaces values are the most reliable objects on Windows.
            try:
                return list(conf.ifaces.values())[idx]
            except Exception:
                return rows[idx][1] or rows[idx][4]
        raise ValueError(f"Interface index {idx} is out of range")

    needle = str(value).lower()
    for idx, name, desc, ip, guid in rows:
        if needle in name.lower() or needle in desc.lower() or needle in guid.lower():
            try:
                return list(conf.ifaces.values())[idx]
            except Exception:
                return name or guid
    # Let Scapy try an exact supplied identifier as a final fallback.
    return value


scaler, pca, pca_scaler, c_model, q_model, C_THRESHOLD, Q_THRESHOLD = load_system()

class ConnectionTracker:
    WINDOW_SECONDS = 2.0

    def __init__(self):
        self.lock = threading.Lock()
        self.connections = {}
        self.packet_count_total = 0
        self.packet_count_window = 0
        self.byte_count_window = 0
        self.service_counts = collections.Counter()

    @staticmethod
    def _key(src, dst, sport, dport, proto):
        return (src, dst, sport, dport, proto)

    def process_packet(self, pkt):
        if IP not in pkt:
            return
        ts = time.time()
        ip = pkt[IP]
        if TCP in pkt:
            l4, proto, flags = pkt[TCP], "tcp", str(pkt[TCP].flags)
        elif UDP in pkt:
            l4, proto, flags = pkt[UDP], "udp", ""
        else:
            return

        sport, dport = int(l4.sport), int(l4.dport)
        key = self._key(ip.src, ip.dst, sport, dport, proto)
        pkt_len = len(pkt)

        with self.lock:
            self.packet_count_total += 1
            self.packet_count_window += 1
            self.byte_count_window += pkt_len
            self.service_counts[(proto, dport)] += 1
            rec = self.connections.setdefault(key, {
                "start": ts, "last": ts, "src_bytes": 0,
                "syn": False, "synack": False, "rst": False,
                "service": (proto, dport),
            })
            rec["last"] = ts
            rec["src_bytes"] += pkt_len
            if proto == "tcp":
                if "S" in flags and "A" not in flags:
                    rec["syn"] = True
                if "S" in flags and "A" in flags:
                    rec["synack"] = True
                if "R" in flags:
                    rec["rst"] = True

    def snapshot(self):
        with self.lock:
            records = list(self.connections.values())
            total_packets = self.packet_count_total
            window_packets = self.packet_count_window
            window_bytes = self.byte_count_window
            services = self.service_counts.copy()
            self.connections.clear()
            self.packet_count_window = 0
            self.byte_count_window = 0
            self.service_counts.clear()

        if not records:
            features = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0], dtype=np.float64)
            return features, total_packets, window_packets, window_bytes

        n = len(records)
        duration = float(np.mean([r["last"] - r["start"] for r in records]))
        src_bytes = float(sum(r["src_bytes"] for r in records))
        syn_errors = sum(r["syn"] and not r["synack"] for r in records)
        rst_errors = sum(r["rst"] for r in records)
        serror_rate = syn_errors / n
        rerror_rate = rst_errors / n

        _dominant_service, dominant_count = services.most_common(1)[0] if services else (("tcp", 0), n)
        srv_count = float(dominant_count)
        same_srv_rate = min(1.0, dominant_count / max(1, window_packets))
        diff_srv_rate = max(0.0, 1.0 - same_srv_rate)

        features = np.array([
            duration, src_bytes, 0.0, float(n), srv_count,
            serror_rate, serror_rate, rerror_rate, rerror_rate,
            same_srv_rate, diff_srv_rate,
        ], dtype=np.float64)
        return features, total_packets, window_packets, window_bytes

tracker = ConnectionTracker()


def infer(raw_features):
    raw_2d = raw_features.reshape(1, -1)
    scaled = scaler.transform(raw_2d)
    target = torch.tensor(scaled, dtype=torch.float32)

    with torch.no_grad():
        c_recon = c_model(target)
        c_error = torch.mean((c_recon - target) ** 2).item()

        pca4 = pca.transform(scaled)
        angles = np.clip(pca_scaler.transform(pca4), 0, np.pi)
        q_recon = q_model(torch.tensor(angles, dtype=torch.float32))
        q_error = torch.mean((q_recon - target) ** 2).item()

    c_attack = c_error > C_THRESHOLD
    q_attack = q_error > Q_THRESHOLD
    hybrid_attack = c_attack or q_attack
    return c_error, q_error, c_attack, q_attack, hybrid_attack


def write_status(payload):
    tmp = OUTPUT_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, OUTPUT_JSON)


def run_cycle(capture_ok=True, capture_error=None, iface_name=None):
    features, total_packets, window_packets, window_bytes = tracker.snapshot()
    c_err, q_err, c_attack, q_attack, attack = infer(features)
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "capture_ok": bool(capture_ok),
        "capture_error": capture_error,
        "capture_interface": str(iface_name or ""),
        "packets_captured": int(total_packets),
        "window_packets": int(window_packets),
        "window_bytes": int(window_bytes),
        "features": {name: round(float(v), 6) for name, v in zip(FEATURES, features)},
        "classical_error": round(c_err, 8),
        "classical_threshold": round(C_THRESHOLD, 8),
        "classical_status": "ATTACK" if c_attack else "NORMAL",
        "quantum_error": round(q_err, 8),
        "quantum_threshold": round(Q_THRESHOLD, 8),
        "quantum_status": "ATTACK" if q_attack else "NORMAL",
        "reconstruction_error": round(q_err, 8),
        "threshold": round(Q_THRESHOLD, 8),
        "is_anomaly": bool(attack),
        "status": "ATTACK" if attack else "NORMAL",
    }


def main():
    parser = argparse.ArgumentParser(description="Q-Harvest live packet sniffer")
    parser.add_argument("--list-ifaces", action="store_true", help="List Scapy capture interfaces and exit")
    parser.add_argument("--iface", help="Interface index, name, description, or GUID substring")
    args = parser.parse_args()

    if args.list_ifaces:
        print_interfaces()
        return

    print_interfaces()
    try:
        iface = resolve_iface(args.iface)
    except Exception as exc:
        print(f"[Q-Harvest] Interface selection error: {exc}")
        return

    print(f"[Q-Harvest] Selected capture interface: {iface}")
    print("[Q-Harvest] Starting live packet capture...")
    print("[Q-Harvest] If packet count stays at 0, run as Administrator and verify Npcap is installed.")

    sniffer = None
    capture_ok = True
    capture_error = None
    try:
        sniffer = AsyncSniffer(iface=iface, prn=tracker.process_packet, store=False)
        sniffer.start()
        time.sleep(1.0)
        # Accessing running is supported by Scapy's AsyncSniffer; capture errors on
        # Windows may surface either here or when stop() is called.
        if hasattr(sniffer, "running") and not sniffer.running:
            raise RuntimeError("Scapy sniffer did not start")
    except Exception as exc:
        capture_ok = False
        capture_error = f"{type(exc).__name__}: {exc}"
        print("\n[Q-Harvest] PACKET CAPTURE FAILED")
        print(f"Reason: {capture_error}")
        print("\nWindows fixes:")
        print("  1. Run Command Prompt/PowerShell as Administrator.")
        print("  2. Install/reinstall Npcap from https://npcap.com/ and enable WinPcap API-compatible mode.")
        print("  3. Run: python frontend\\live_sniffer.py --list-ifaces")
        print("  4. Then select the active adapter, e.g.: python frontend\\live_sniffer.py --iface 3")
        write_status(run_cycle(False, capture_error, iface))
        return

    try:
        zero_windows = 0
        while True:
            time.sleep(ConnectionTracker.WINDOW_SECONDS)
            try:
                status = run_cycle(capture_ok, capture_error, iface)
                write_status(status)
                if status["window_packets"] == 0:
                    zero_windows += 1
                else:
                    zero_windows = 0
                print(
                    f"[{status['timestamp']}] total={status['packets_captured']} "
                    f"window={status['window_packets']} | "
                    f"CAE={status['classical_error']:.6f} | QAE={status['quantum_error']:.6f} | {status['status']}"
                )
                if zero_windows == 5:
                    print("\n[Q-Harvest] WARNING: No TCP/UDP IPv4 packets captured for ~10 seconds.")
                    print("The selected interface may be wrong. Try --list-ifaces and choose Wi-Fi/Ethernet explicitly.\n")
            except Exception as exc:
                print(f"[Q-Harvest] Inference cycle error: {type(exc).__name__}: {exc}")
                traceback.print_exc()
    except KeyboardInterrupt:
        print("\n[Q-Harvest] Stopping sniffer...")
    finally:
        if sniffer is not None:
            try:
                sniffer.stop()
            except Exception:
                pass
        print("[Q-Harvest] Sniffer stopped.")

if __name__ == "__main__":
    main()
