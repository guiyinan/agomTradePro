"""Equity curve page."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from streamlit_app.services.session import get_api_client_from_sidebar

st.set_page_config(page_title="Equity Curve", page_icon="EC", layout="wide")
st.title("Equity Curve")

client = get_api_client_from_sidebar()
if not client:
    st.stop()

range_code = st.selectbox("Time Range", options=["1M", "3M", "6M", "1Y", "ALL"], index=4)

try:
    payload = client.get_equity_curve(range_code=range_code)
except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to load equity curve: {exc}")
    st.stop()

series = payload.get("series", [])
if not series:
    st.warning("No equity curve data available yet.")
    st.stop()

df = pd.DataFrame(series)
if "date" in df.columns:
    df["date"] = pd.to_datetime(df["date"])

if "portfolio_value" not in df.columns:
    if "return_pct" in df.columns:
        st.info("Historical portfolio value is not available. Displaying return percentage.")
        fig = px.line(df, x="date", y="return_pct", title="Portfolio Return %")
    else:
        st.warning("Unsupported series schema from backend.")
        st.stop()
else:
    fig = px.line(df, x="date", y="portfolio_value", title="Portfolio Value")

fig.update_layout(height=520, margin={"l": 20, "r": 20, "t": 40, "b": 20})
st.plotly_chart(fig, use_container_width=True)

st.caption(
    "If `has_history=false`, backend is using a fallback point until historical "
    "snapshot storage is implemented."
)
st.json({"range": payload.get("range"), "has_history": payload.get("has_history")})
