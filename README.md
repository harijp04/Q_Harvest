# Q-Harvest — Hybrid Quantum-Classical Intrusion Detection System

Q-Harvest is an anomaly-based Network Intrusion Detection System that compares a Classical Autoencoder with a 4-qubit PennyLane Quantum Autoencoder. The models are trained around normal traffic behavior and flag traffic whose reconstruction error exceeds a learned threshold.

## Demo architecture
Network traffic → Scapy capture → 11-feature window → scaling → Classical AE + PCA/4-qubit QAE → reconstruction error → threshold → NORMAL/ATTACK → Streamlit dashboard.

## Quick start (Windows)
1. Install Python 3.10–3.12.
2. `python -m pip install -r requirements.txt`
3. Install Npcap if Scapy packet capture is unavailable.
4. Run `run_sniffer_admin.bat` as Administrator.
5. Run `run_dashboard.bat`.
6. Optional controlled demo: run `run_attack_demo.bat` on your own lab/local network.

See `DEMO_GUIDE.md` for presentation instructions.

## Important research note
The quantum circuit uses PennyLane `default.qubit`, so it is a simulated quantum circuit. The project evaluates quantum ML as an alternative traffic representation; it does not claim a proven real-hardware quantum speedup.
