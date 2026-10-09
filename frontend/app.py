
import json
import os
import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import joblib
import numpy as np
import pennylane as qml
import torch
import torch.nn as nn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MANUAL_STATUS = os.path.join(BASE_DIR, "manual_status.json")
MONITOR_STATUS = os.path.join(BASE_DIR, "monitor_status.json")
MODELS_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "models"))
OFFLINE_FEATURES = [
    "duration", "src_bytes", "dst_bytes", "count", "srv_count",
    "serror_rate", "srv_serror_rate", "rerror_rate", "srv_rerror_rate",
    "same_srv_rate", "diff_srv_rate",
]

st.set_page_config(
    page_title="Q-Harvest | Unified Quantum IDS",
    page_icon="🛡️",
    layout="wide"
)

st.markdown("""
<style>
.stApp { background-color:#0e1117; }
.status-box {
    border-radius:12px;
    padding:18px;
    margin:8px 0 18px 0;
    font-weight:800;
    font-size:1.25rem;
}
.safe {
    background:rgba(0,255,128,.08);
    border:1px solid #00ff80;
    color:#00ff80;
}
.danger {
    background:rgba(255,0,85,.13);
    border:1px solid #ff0055;
    color:#ff668f;
}
.warn {
    background:rgba(255,190,0,.10);
    border:1px solid #ffbf00;
    color:#ffd45c;
}
</style>
""", unsafe_allow_html=True)


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


manual = read_json(MANUAL_STATUS)
monitor = read_json(MONITOR_STATUS)

manual_state = manual.get("state", "NORMAL")
monitor_state = monitor.get("state", "NORMAL")

req_rate = float(manual.get("request_rate_rps", 0))
manual_upload = float(manual.get("upload_rate_kbps", 0))
upload_events = int(manual.get("upload_events_10s", 0))

c_err = float(monitor.get("c_err", 0))
q_err = float(monitor.get("q_err", 0))
c_thr = float(monitor.get("c_thr", 0))
q_thr = float(monitor.get("q_thr", 0))

# --------------------------------------------------------------
# UNIFIED DECISION
# Manual traffic determines the demo attack type.
# ML/QML values support the slow-leak decision but do not create
# a misleading slow-leak headline during an unrelated DoS demo.
# --------------------------------------------------------------
if manual_state == "SLOWLORIS_DETECTED":
    overall_state = "SLOWLORIS"
    status_text = "🚨 SLOWLORIS DoS ATTACK DETECTED"
    status_css = "danger"

elif manual_state == "DOS_DETECTED":
    overall_state = "DOS"
    status_text = "🚨 DoS ATTACK DETECTED"
    status_css = "danger"

elif manual_state == "SLOW_LEAK_DETECTED":
    overall_state = "SLOW_LEAK"
    status_text = "🚨 SLOW DATA EXFILTRATION DETECTED"
    status_css = "danger"

elif manual_state == "NORMAL":
    overall_state = "NORMAL"
    status_text = "✅ NORMAL TRAFFIC"
    status_css = "safe"

else:
    overall_state = "WARMUP"
    status_text = "⏳ Q-HARVEST MONITOR WARMING UP"
    status_css = "warn"


# --------------------------------------------------------------
# PERSISTENT STATE-CHANGE HISTORY IN THIS STREAMLIT SESSION
# --------------------------------------------------------------
if "detection_history" not in st.session_state:
    st.session_state.detection_history = []

if "last_overall_state" not in st.session_state:
    st.session_state.last_overall_state = None

if st.session_state.last_overall_state != overall_state:
    if overall_state == "SLOWLORIS":
        display_status = "SLOWLORIS DoS"
    elif overall_state == "DOS":
        display_status = "DoS ATTACK"
    elif overall_state == "SLOW_LEAK":
        display_status = "SLOW DATA EXFILTRATION"
    elif overall_state == "NORMAL":
        display_status = "NORMAL"
    else:
        display_status = "WARMUP"

    st.session_state.detection_history.append({
        "Time": datetime.now().strftime("%H:%M:%S"),
        "Detection": display_status,
        "Request Rate": round(req_rate, 2),
        "Upload Rate KB/s": round(manual_upload, 2),
        "Classical Error": round(c_err, 6),
        "Quantum Error": round(q_err, 6),
    })

    st.session_state.detection_history = st.session_state.detection_history[-30:]
    st.session_state.last_overall_state = overall_state


st.title("🛡️ Q-HARVEST")
st.caption("Unified Hybrid Quantum–Classical Intrusion Detection System")

st.markdown(
    f'<div class="status-box {status_css}">{status_text}</div>',
    unsafe_allow_html=True
)

# --------------------------------------------------------------
# LIVE STATUS
# --------------------------------------------------------------
st.subheader("📡 Live Network Status")

row1 = st.columns(5)
row1[0].metric("Request Rate", f"{req_rate:.1f} req/s")
row1[1].metric("Upload Rate", f"{manual_upload:.2f} KB/s")
row1[2].metric("Outbound", f"{float(monitor.get('out_kbps', 0)):.2f} KB/s")
row1[3].metric("Inbound", f"{float(monitor.get('in_kbps', 0)):.2f} KB/s")
row1[4].metric("Connections", int(monitor.get("established", 0)))

row2 = st.columns(4)
row2[0].metric("Classical Error", f"{c_err:.6f}")
row2[1].metric("Classical Threshold", f"{c_thr:.6f}")
row2[2].metric("Quantum Error", f"{q_err:.6f}")
row2[3].metric("Quantum Threshold", f"{q_thr:.6f}")

# --------------------------------------------------------------
# DETECTION EXPLANATION
# --------------------------------------------------------------
st.subheader("🧠 Detection Result")

if overall_state == "SLOWLORIS":
    st.error(
        f"Slowloris-style connection exhaustion detected against the dummy cloud. "
        f"Active connections: {int(manual.get('active_connections', 0))}."
    )
elif overall_state == "DOS":
    st.error(
        f"High request-rate traffic detected against the dummy cloud "
        f"({req_rate:.1f} req/s). Q-Harvest classifies this as a DoS attack simulation."
    )
elif overall_state == "SLOW_LEAK":
    ml_note = ""
    if q_thr > 0:
        ml_note = f" Quantum reconstruction error: {q_err:.6f} (threshold {q_thr:.6f})."
    st.error(
        f"Sustained low-rate upload behavior detected "
        f"({manual_upload:.2f} KB/s, {upload_events} upload events/10s)."
        + ml_note
    )
elif overall_state == "NORMAL":
    st.success("Traffic is currently within the normal demo profile.")
else:
    warm = float(monitor.get("warm", 0))
    st.warning("The traffic analysis window is warming up.")
    st.progress(min(max(warm, 0.0), 1.0), text=f"Warm-up: {warm*100:.0f}%")

# --------------------------------------------------------------
# CLASSICAL / QUANTUM COMPARISON
# --------------------------------------------------------------
st.subheader("⚛️ Classical vs Quantum Reconstruction Error")

fig = go.Figure()
fig.add_trace(go.Bar(name="Classical Error", x=["Classical"], y=[c_err]))
fig.add_trace(go.Bar(name="Quantum Error", x=["Quantum"], y=[q_err]))
fig.add_trace(go.Scatter(
    name="Classical Threshold",
    x=["Classical"], y=[c_thr],
    mode="markers", marker_symbol="line-ew", marker_size=24
))
fig.add_trace(go.Scatter(
    name="Quantum Threshold",
    x=["Quantum"], y=[q_thr],
    mode="markers", marker_symbol="line-ew", marker_size=24
))
fig.update_layout(
    template="plotly_dark",
    height=330,
    yaxis_title="Reconstruction Error",
    showlegend=True
)
st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------
# CLEAN RECENT DETECTION HISTORY
# --------------------------------------------------------------
st.subheader("🧾 Recent Detection Activity")

history_df = pd.DataFrame(st.session_state.detection_history)
if not history_df.empty:
    st.dataframe(
        history_df.iloc[::-1],
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No state changes recorded yet.")

# Optional ML/QML event log, folded away so it is not a second demo.
events = monitor.get("events", [])
if events:
    with st.expander("Technical ML/QML event log"):
        st.dataframe(
            pd.DataFrame(events[::-1]),
            use_container_width=True,
            hide_index=True
        )


# --------------------------------------------------------------
# OFFLINE DATASET ANOMALY ANALYSIS
# --------------------------------------------------------------
st.divider()
st.subheader("📁 Offline Dataset Anomaly Analysis")
st.caption(
    "Upload a CSV containing the predefined Q-Harvest NSL-KDD feature columns. "
    "The Classical and Quantum Autoencoders will analyze every row and flag anomalies."
)

class OfflineClassicalAutoencoder(nn.Module):
    def __init__(self, input_dim=11):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 8),
            nn.ReLU(),
            nn.Linear(8, 4),
        )
        self.decoder = nn.Sequential(
            nn.Linear(4, 8),
            nn.ReLU(),
            nn.Linear(8, input_dim),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return self.decoder(self.encoder(x))


OFFLINE_N_QUBITS = 4
OFFLINE_N_LAYERS = 3
offline_qdev = qml.device("default.qubit", wires=OFFLINE_N_QUBITS)

@qml.qnode(offline_qdev, interface="torch")
def offline_quantum_circuit(inputs, weights):
    qml.AngleEmbedding(inputs, wires=range(OFFLINE_N_QUBITS))
    qml.BasicEntanglerLayers(weights, wires=range(OFFLINE_N_QUBITS))
    return [qml.expval(qml.PauliZ(i)) for i in range(OFFLINE_N_QUBITS)]


class OfflineQuantumAutoencoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.quantum_layer = qml.qnn.TorchLayer(
            offline_quantum_circuit,
            {"weights": (OFFLINE_N_LAYERS, OFFLINE_N_QUBITS)}
        )
        self.classical_output = nn.Linear(4, 11)

    def forward(self, x):
        return self.classical_output(self.quantum_layer(x))


@st.cache_resource
def load_offline_models():
    system = {}

    system["scaler"] = joblib.load(os.path.join(MODELS_DIR, "scaler.pkl"))
    system["pca"] = joblib.load(os.path.join(MODELS_DIR, "pca_transformer.pkl"))
    system["pca_angle_scaler"] = joblib.load(
        os.path.join(MODELS_DIR, "pca_angle_scaler.pkl")
    )

    system["c_threshold"] = float(
        joblib.load(os.path.join(MODELS_DIR, "threshold.pkl"))
    )
    system["q_threshold"] = float(
        joblib.load(os.path.join(MODELS_DIR, "quantum_threshold.pkl"))
    )

    c_model = OfflineClassicalAutoencoder()
    c_model.load_state_dict(
        torch.load(
            os.path.join(MODELS_DIR, "classical_autoencoder.pth"),
            map_location="cpu",
            weights_only=True,
        )
    )
    c_model.eval()

    q_model = OfflineQuantumAutoencoder()
    q_model.load_state_dict(
        torch.load(
            os.path.join(MODELS_DIR, "quantum_autoencoder.pth"),
            map_location="cpu",
            weights_only=True,
        )
    )
    q_model.eval()

    system["c_model"] = c_model
    system["q_model"] = q_model
    return system


try:
    offline_system = load_offline_models()
    offline_ready = True
except Exception as exc:
    offline_ready = False
    st.error(f"Offline analyzer model loading failed: {exc}")


uploaded_csv = st.file_uploader(
    "Upload predefined network dataset CSV",
    type=["csv"],
    key="offline_dataset_uploader",
)

if uploaded_csv is not None and offline_ready:
    try:
        uploaded_df = pd.read_csv(uploaded_csv)

        missing = [
            feature for feature in OFFLINE_FEATURES
            if feature not in uploaded_df.columns
        ]

        if missing:
            st.error(
                "The uploaded CSV is missing these required columns: "
                + ", ".join(missing)
            )
        else:
            input_df = uploaded_df[OFFLINE_FEATURES].copy()

            if input_df.isnull().any().any():
                st.error("The uploaded feature columns contain missing/NaN values.")
            else:
                scaled = offline_system["scaler"].transform(input_df)
                target = torch.tensor(scaled, dtype=torch.float32)

                with torch.no_grad():
                    c_recon = offline_system["c_model"](target)
                    c_errors = torch.mean(
                        (c_recon - target) ** 2,
                        dim=1
                    ).cpu().numpy()

                    pca4 = offline_system["pca"].transform(scaled)
                    angles = np.clip(
                        offline_system["pca_angle_scaler"].transform(pca4),
                        0,
                        np.pi,
                    )

                    q_recon = offline_system["q_model"](
                        torch.tensor(angles, dtype=torch.float32)
                    )
                    q_errors = torch.mean(
                        (q_recon - target) ** 2,
                        dim=1
                    ).cpu().numpy()

                c_threshold = offline_system["c_threshold"]
                q_threshold = offline_system["q_threshold"]

                c_attack = c_errors > c_threshold
                q_attack = q_errors > q_threshold

                # Hybrid result: either detector may flag the record.
                hybrid_attack = np.logical_or(c_attack, q_attack)

                results = uploaded_df.copy()
                results["Classical_Error"] = c_errors
                results["Classical_Result"] = np.where(
                    c_attack, "ANOMALY", "NORMAL"
                )
                results["Quantum_Error"] = q_errors
                results["Quantum_Result"] = np.where(
                    q_attack, "ANOMALY", "NORMAL"
                )
                results["Final_Result"] = np.where(
                    hybrid_attack, "ANOMALY", "NORMAL"
                )

                total_rows = len(results)
                anomaly_rows = int(hybrid_attack.sum())
                normal_rows = total_rows - anomaly_rows
                anomaly_pct = (
                    (anomaly_rows / total_rows) * 100
                    if total_rows else 0.0
                )

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Records Analyzed", total_rows)
                m2.metric("Normal Records", normal_rows)
                m3.metric("Anomalies Detected", anomaly_rows)
                m4.metric("Anomaly Rate", f"{anomaly_pct:.1f}%")

                st.markdown(
                    f"**Classical threshold:** `{c_threshold:.6f}` &nbsp;&nbsp; "
                    f"**Quantum threshold:** `{q_threshold:.6f}`"
                )

                result_filter = st.selectbox(
                    "Show records",
                    ["All", "Anomaly Only", "Normal Only"],
                    key="offline_result_filter",
                )

                if result_filter == "Anomaly Only":
                    displayed = results[
                        results["Final_Result"] == "ANOMALY"
                    ]
                elif result_filter == "Normal Only":
                    displayed = results[
                        results["Final_Result"] == "NORMAL"
                    ]
                else:
                    displayed = results

                display_columns = [
                    "Classical_Error",
                    "Classical_Result",
                    "Quantum_Error",
                    "Quantum_Result",
                    "Final_Result",
                ]

                st.dataframe(
                    displayed[display_columns],
                    use_container_width=True,
                    hide_index=False,
                )

                chart = go.Figure()
                chart.add_trace(
                    go.Bar(
                        x=["Normal", "Anomaly"],
                        y=[normal_rows, anomaly_rows],
                        name="Dataset Result",
                    )
                )
                chart.update_layout(
                    template="plotly_dark",
                    height=300,
                    title="Uploaded Dataset Analysis Summary",
                    yaxis_title="Number of Records",
                )
                st.plotly_chart(chart, use_container_width=True)

                st.download_button(
                    "⬇️ Download Analysis Results",
                    data=results.to_csv(index=False).encode("utf-8"),
                    file_name="q_harvest_anomaly_results.csv",
                    mime="text/csv",
                )

    except Exception as exc:
        st.error(f"Unable to analyze uploaded dataset: {exc}")

with st.expander("Presentation controls"):
    st.markdown("""
`py frontend\\manual_attack_tool.py`

- **1** → DoS Attack Simulation
- **2** → Slow Data Leak Simulation
- **3** → Normal Traffic
- **4** → Exit

The dashboard records only **state changes**, so the activity table remains clean.
""")

st.caption("Q-Harvest • Unified Hybrid Quantum–Classical Intrusion Detection Prototype")

time.sleep(2)
st.rerun()
