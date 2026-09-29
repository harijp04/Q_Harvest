import streamlit as st
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import joblib
import os
import plotly.graph_objects as go
import json
import time
from datetime import datetime
from sklearn.preprocessing import MinMaxScaler
from sklearn.decomposition import PCA
import pennylane as qml

# --- PAGE CONFIG & CUSTOM CSS ---
st.set_page_config(page_title="Q-Harvest | Quantum IDS", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .alert-box { border-radius: 8px; padding: 12px; margin: 4px 0; font-weight: bold; font-size: 1rem; display: flex; justify-content: space-between; align-items: center; animation: fadeIn 0.5s; }
    .safe { background-color: rgba(0, 255, 128, 0.1); border: 1px solid #00ff80; color: #00ff80; }
    .danger { background-color: rgba(255, 0, 85, 0.15); border: 1px solid #ff0055; color: #ff0055; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; transform: translateY(0); } }
    .stButton>button { background: linear-gradient(90deg, #00d4ff, #0055ff); color: white; border: none; border-radius: 8px; padding: 10px 20px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- LIVE STATUS READER ---
def get_live_status():
    try:
        with open("live_status.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

# --- MODEL DEFINITIONS ---
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
        q_out = self.quantum_layer(x)
        return self.classical_output(q_out)

# --- LOAD MODELS ---
@st.cache_resource
def load_system():
    path = "../models"
    sys = {}
    if os.path.exists(f"{path}/scaler.pkl"): sys['scaler'] = joblib.load(f"{path}/scaler.pkl")
    if os.path.exists(f"{path}/classical_autoencoder.pth"):
        sys['c_model'] = ClassicalAutoencoder(11)
        sys['c_model'].load_state_dict(torch.load(f"{path}/classical_autoencoder.pth", map_location=torch.device('cpu'), weights_only=True))
        sys['c_model'].eval()
        sys['c_thresh'] = float(joblib.load(f"{path}/threshold.pkl"))
    if os.path.exists(f"{path}/quantum_autoencoder.pth"):
        sys['q_model'] = QuantumAutoencoder()
        sys['q_model'].load_state_dict(torch.load(f"{path}/quantum_autoencoder.pth", map_location=torch.device('cpu'), weights_only=True))
        sys['q_model'].eval()
        sys['pca'] = joblib.load(f"{path}/pca_transformer.pkl")
        sys['pca_angle_scaler'] = joblib.load(f"{path}/pca_angle_scaler.pkl")
        sys['q_thresh'] = float(joblib.load(f"{path}/quantum_threshold.pkl"))
    return sys

system = load_system()

# --- UI HEADER ---
st.title("🛡️ Q-HARVEST // Quantum Intrusion Detection System")
st.markdown("---")

# --- SIDEBAR ---
st.sidebar.header("⚙️ System Configuration")
auto_update = st.sidebar.checkbox("⚡ Auto-Update Live Feed (Refresh every 2s)", value=False)
model_mode = st.sidebar.selectbox("Detection Engine", ["Quantum Autoencoder (QAE)", "Classical Autoencoder (CAE)", "Hybrid Comparison"])

st.sidebar.markdown("---")
st.sidebar.subheader("System Status")
if 'c_model' in system: st.sidebar.success("✅ Classical Engine Online")
if 'q_model' in system: st.sidebar.success("✅ Quantum Engine Online")

# --- INITIALIZE HISTORY IN SESSION STATE ---
if 'alert_history' not in st.session_state:
    st.session_state.alert_history = []

# ==========================================
# SECTION 1: LIVE NETWORK MONITOR
# ==========================================
st.subheader("📡 Live Network Traffic Monitoring")

live_data = get_live_status()

if live_data:
    error = float(live_data.get('reconstruction_error', 0.0))
    status = str(live_data.get('status', 'UNKNOWN')).upper()
    packets = int(live_data.get('packets_captured', 0))
    q_thresh = float(system.get('q_thresh', 0.000414))
    is_attack = (error > q_thresh) or (status == "ATTACK")
    current_status_str = "ATTACK" if is_attack else "NORMAL"
    
    # 1. RECORD EVERY READING
    new_record = {
        'time': datetime.now().strftime('%H:%M:%S'),
        'status': current_status_str,
        'error': f"{error:.6f}",
        'packets': packets
    }
    st.session_state.alert_history.append(new_record)
    
    # Keep ONLY the last 6 records (FIFO)
    if len(st.session_state.alert_history) > 6:
        st.session_state.alert_history.pop(0)

    # 2. Display Current Big Metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("📦 Total Packets", f"{packets:,}")
    col2.metric("⚠️ Reconstruction Error", f"{error:.6f}")
    col3.metric("🎯 Current Status", "🚨 ATTACK" if is_attack else "✅ NORMAL")

    # 3. Display The History List (Last 6 Alerts)
    st.markdown("---")
    st.subheader(" Recent Alert History (Last 6 Events)")
    
    if len(st.session_state.alert_history) == 0:
        st.info("Waiting for data...")
    else:
        for record in reversed(st.session_state.alert_history):
            if record['status'] == "ATTACK":
                css_class = "danger"
                icon = "🚨 ATTACK DETECTED"
            else:
                css_class = "safe"
                icon = "✅ NORMAL TRAFFIC"
            
            st.markdown(
                f'<div class="alert-box {css_class}">'
                f'<span>{icon}</span>'
                f'<span style="font-size:0.85rem; opacity:0.9;">Time: {record["time"]} | Error: {record["error"]}</span>'
                f'</div>', 
                unsafe_allow_html=True
            )
    
    st.caption("💡 Tip: Enable 'Auto-Update' in sidebar for live refresh, or press F5 manually.")

else:
    st.warning("⏳ Waiting for live sniffer data... Make sure `live_sniffer.py` is running.")

st.markdown("---")

# ==========================================
# SECTION 2: OFFLINE ANALYSIS (Manual / CSV)
# ==========================================
st.subheader("📊 Offline Threat Analysis (Manual / CSV)")

col1, col2 = st.columns([1, 2])

with col1:
    st.markdown("**Network Traffic Input**")
    input_method = st.radio("Input Method", ["Manual Entry", "Upload CSV"])
    features = ['duration', 'src_bytes', 'dst_bytes', 'count', 'srv_count', 'serror_rate', 'srv_serror_rate', 'rerror_rate', 'srv_rerror_rate', 'same_srv_rate', 'diff_srv_rate']

    if input_method == "Manual Entry":
        with st.form("traffic_form"):
            c1, c2 = st.columns(2)
            duration = c1.number_input("Duration", value=0.0)
            count = c2.number_input("Connection Count", value=1)
            src_bytes = c1.number_input("Source Bytes", value=0)
            dst_bytes = c2.number_input("Dest Bytes", value=0)
            c3, c4 = st.columns(2)
            serror = c3.number_input("Serror Rate", value=0.0, min_value=0.0, max_value=1.0)
            same_srv = c4.number_input("Same Srv Rate", value=1.0, min_value=0.0, max_value=1.0)
            submitted = st.form_submit_button("🚀 ANALYZE TRAFFIC")
            if submitted:
                st.session_state['input_df'] = pd.DataFrame([{'duration': duration, 'src_bytes': src_bytes, 'dst_bytes': dst_bytes, 'count': count, 'srv_count': 0, 'serror_rate': serror, 'srv_serror_rate': 0, 'rerror_rate': 0, 'srv_rerror_rate': 0, 'same_srv_rate': same_srv, 'diff_srv_rate': 0}])
    else:
        uploaded = st.file_uploader("Upload CSV", type=['csv'])
        if uploaded:
            df = pd.read_csv(uploaded)
            if all(f in df.columns for f in features):
                st.session_state['input_df'] = df[features]
            else:
                st.error("CSV missing required columns!")

with col2:
    st.markdown("**Threat Analysis Results**")
    if 'input_df' in st.session_state:
        if 'scaler' not in system:
            st.error("Cannot run analysis: scaler.pkl not found.")
        else:
            data = st.session_state['input_df']
            scaled_data = system['scaler'].transform(data)
            results = {}

            if ("Classical" in model_mode or "Hybrid" in model_mode) and 'c_model' in system:
                with torch.no_grad():
                    recon = system['c_model'](torch.FloatTensor(scaled_data))
                    err = torch.mean((torch.FloatTensor(scaled_data) - recon) ** 2, dim=1).numpy()
                results['Classical'] = (err, system['c_thresh'])

            if ("Quantum" in model_mode or "Hybrid" in model_mode) and 'q_model' in system:
                with torch.no_grad():
                    pca_data = system['pca'].transform(scaled_data)
                    pca_angles = system['pca_angle_scaler'].transform(pca_data)
                    recon = system['q_model'](torch.FloatTensor(pca_angles))
                    err = torch.mean((torch.FloatTensor(scaled_data) - recon) ** 2, dim=1).numpy()
                results['Quantum'] = (err, system['q_thresh'])

            for model_name, (errors, thresh) in results.items():
                st.markdown(f"**{model_name} Engine**")
                for i, err in enumerate(errors):
                    is_attack = err > thresh
                    css_class = "danger" if is_attack else "safe"
                    icon = "🚨 ANOMALY DETECTED" if is_attack else "✅ NORMAL TRAFFIC"
                    st.markdown(f'<div class="alert-box {css_class}">Record {i+1}: {icon}<br><span style="font-size:0.9rem">Error: {err:.6f} | Threshold: {thresh:.6f}</span></div>', unsafe_allow_html=True)

            if results:
                fig = go.Figure()
                colors = {'Classical': '#00d4ff', 'Quantum': '#ff0055'}
                for model_name, (errors, thresh) in results.items():
                    fig.add_trace(go.Bar(name=f"{model_name} Error", x=[f"Record {i+1}" for i in range(len(errors))], y=errors, marker_color=colors[model_name]))
                    fig.add_hline(y=thresh, line_dash="dash", line_color="yellow", annotation_text=f"{model_name} Threshold")
                fig.update_layout(template="plotly_dark", title="Reconstruction Error vs Threshold", yaxis_title="Error Score", barmode="group")
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(" Enter network parameters or upload a CSV to begin analysis.")

st.markdown("---")
st.caption("Q-Harvest Project | Powered by PyTorch & PennyLane Quantum ML")

# ==========================================
# AUTO-UPDATE LOGIC (At the very end)
# ==========================================
if auto_update:
    time.sleep(2)
    st.rerun()