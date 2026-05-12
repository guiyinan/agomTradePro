"""Signal status page."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from streamlit_app.services.session import get_api_client_from_sidebar

st.set_page_config(page_title="Signals", page_icon="SG", layout="wide")
st.title("Signal Status")

client = get_api_client_from_sidebar()
if not client:
    st.stop()

limit = st.slider("Signal Rows", min_value=10, max_value=200, value=50, step=10)

try:
    payload = client.get_signal_status(limit=limit)
except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load signal status: {exc}")
    st.stop()

stats = payload.get("stats", {}) or {}
signals = payload.get("signals", []) or []

stats_df = pd.DataFrame(
    [{"status": key, "count": value} for key, value in stats.items() if isinstance(value, int)]
)

if not stats_df.empty:
    chart = px.bar(stats_df, x="status", y="count", title="Signal Status Breakdown")
    chart.update_layout(height=400, margin={"l": 20, "r": 20, "t": 40, "b": 20})
    st.plotly_chart(chart, use_container_width=True)
else:
    st.info("No signal stats returned.")

st.subheader("Recent Signals")
if not signals:
    st.warning("No recent signals available.")
else:
    signal_df = pd.DataFrame(signals)
    if "created_at" in signal_df.columns:
        signal_df = signal_df.sort_values("created_at", ascending=False)
    st.dataframe(signal_df, use_container_width=True, hide_index=True)
