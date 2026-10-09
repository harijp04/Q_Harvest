import os, json, time
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Q-Harvest", page_icon="🛡️", layout="wide")
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_status.json")

def read():
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return None

st.title("🛡️ Q-HARVEST: Quantum Slow-Leak Monitor")
st.caption("Live network counters of this machine -> 30 s window features -> trained classical and hybrid-quantum autoencoders")

s = read()
if s is None:
    st.warning("Waiting for monitor.py ... start it in another terminal.")
else:
    if s["state"] == "WARMUP":
        st.info(f"Warming up: collecting the first 30 s window ({s['warm']*100:.0f}%)")
    elif s["state"] == "ALERT":
        st.error("🚨 ANOMALY: sustained abnormal outbound traffic pattern (possible slow exfiltration)")
    else:
        st.success("✅ NORMAL: traffic matches the learned pattern")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outbound KB/s", f"{s['out_kbps']:.1f}")
    c2.metric("Inbound KB/s", f"{s['in_kbps']:.1f}")
    c3.metric("Quantum error / threshold", f"{s['q_err']:.4f} / {s['q_thr']:.4f}")
    c4.metric("Classical error / threshold", f"{s['c_err']:.4f} / {s['c_thr']:.4f}")

    h = pd.DataFrame(s["history"])
    if len(h):
        a, b = st.columns(2)
        for col, key, name, thr in [(a, "q", "Quantum autoencoder", s["q_thr"]),
                                    (b, "c", "Classical autoencoder", s["c_thr"])]:
            fig = go.Figure(go.Scatter(x=h["t"], y=h[key], mode="lines", name="error"))
            fig.add_hline(y=thr, line_dash="dash", line_color="orange", annotation_text="threshold")
            fig.update_layout(template="plotly_dark", height=280, title=name,
                              margin=dict(l=10, r=10, t=40, b=10))
            col.plotly_chart(fig, use_container_width=True)

    st.subheader("Event log")
    if s["events"]:
        st.dataframe(pd.DataFrame(s["events"]), hide_index=True, use_container_width=True)
    else:
        st.caption("No events yet.")

time.sleep(2)
st.rerun()
