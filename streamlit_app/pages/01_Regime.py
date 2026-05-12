"""Regime quadrant page."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from streamlit_app.services.session import get_api_client_from_sidebar

st.set_page_config(page_title="Regime", page_icon="RG", layout="wide")
st.title("Regime Quadrant")

client = get_api_client_from_sidebar()
if not client:
    st.stop()

try:
    payload = client.get_regime_quadrant()
except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load regime data: {exc}")
    st.stop()

distribution = payload.get("distribution", {})
current_regime = payload.get("current_regime", "Unknown")
confidence = float(payload.get("confidence", 0.0) or 0.0)
as_of_date = payload.get("as_of_date", "-")

summary_col1, summary_col2, summary_col3 = st.columns(3)
summary_col1.metric("Current Regime", current_regime)
summary_col2.metric("Confidence", f"{confidence:.2%}")
summary_col3.metric("As Of", as_of_date)

quadrants = {
    "Recovery": (1, 1),
    "Overheat": (1, -1),
    "Stagflation": (-1, -1),
    "Deflation": (-1, 1),
}

fig = go.Figure()
for name, (x, y) in quadrants.items():
    prob = float(distribution.get(name, 0.0) or 0.0)
    is_current = name == current_regime
    fig.add_trace(
        go.Scatter(
            x=[x],
            y=[y],
            mode="markers+text",
            text=[f"{name}<br>{prob:.2%}"],
            textposition="top center",
            marker={
                "size": 38 if is_current else 28,
                "color": "#D62828" if is_current else "#457B9D",
                "line": {"width": 2, "color": "#1D3557"},
            },
            name=name,
        )
    )

fig.update_layout(
    xaxis={"range": [-1.5, 1.5], "title": "Growth"},
    yaxis={"range": [-1.5, 1.5], "title": "Inflation"},
    height=560,
    showlegend=False,
    margin={"l": 20, "r": 20, "t": 20, "b": 20},
)
fig.add_hline(y=0, line_width=1, line_dash="dash")
fig.add_vline(x=0, line_width=1, line_dash="dash")

st.plotly_chart(fig, use_container_width=True)

st.subheader("Distribution")
st.json(distribution)
