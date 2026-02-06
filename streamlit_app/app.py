"""Entry page for AgomSAAF Streamlit dashboard."""

import streamlit as st


st.set_page_config(
    page_title="AgomSAAF Dashboard",
    page_icon="AG",
    layout="wide",
)

st.title("AgomSAAF Streamlit Dashboard")
st.caption("Interactive dashboard for Regime, Equity Curve, and Signal Status.")

st.markdown(
    """
Use the pages in the left sidebar:
- `Regime` for quadrant visualization.
- `Equity Curve` for portfolio trend view.
- `Signals` for signal status monitoring.
"""
)

st.info(
    "Before using pages, set `Django Base URL` and `DRF Token` in sidebar "
    "on each page."
)
