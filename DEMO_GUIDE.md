# Q-Harvest Demo Guide

## Install once
```bash
python -m pip install -r requirements.txt
```

On Windows, install Npcap if Scapy cannot capture packets. Run the sniffer terminal as **Administrator**.

## Demo order
1. Start `run_sniffer_admin.bat` as Administrator.
2. Start `run_dashboard.bat` normally.
3. Open the Streamlit URL (usually http://localhost:8501).
4. Show NORMAL traffic and both reconstruction errors.
5. Run `run_attack_demo.bat` for a controlled traffic burst on your own local network.
6. Watch the Classical/Quantum errors and live status change.

## Viva-safe project claim
Q-Harvest is a hybrid quantum-classical anomaly-based NIDS. It learns normal traffic, reduces features with PCA for a 4-qubit PennyLane circuit, and flags samples whose reconstruction error exceeds a learned threshold. The quantum circuit is simulated on `default.qubit`; this prototype evaluates quantum ML as an alternative representation and does not claim proven real-hardware quantum speedup.

## Troubleshooting
- Packet count stuck at 0: run the sniffer as Administrator/root; on Windows install Npcap.
- `streamlit` not found: `python -m pip install -r requirements.txt`.
- Dashboard says waiting for detector: confirm `frontend/live_sniffer.py` is running and `frontend/live_status.json` is updating.
- The attack demo is for controlled lab/demo use against your own default gateway only.
