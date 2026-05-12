"""Shared Streamlit sidebar/session helpers."""

from __future__ import annotations

import streamlit as st

from streamlit_app.services.dashboard_api import DashboardApiClient


def get_api_client_from_sidebar() -> DashboardApiClient | None:
    """Render auth controls and return an initialized API client."""
    st.sidebar.header("API Config")
    base_url = st.sidebar.text_input(
        "Django Base URL",
        value=st.session_state.get("base_url", "http://127.0.0.1:8000"),
        help="Example: http://127.0.0.1:8000",
    )
    token = st.sidebar.text_input(
        "DRF Token",
        value=st.session_state.get("api_token", ""),
        type="password",
        help="Use Django REST Framework token value.",
    )

    st.session_state["base_url"] = base_url.strip()
    st.session_state["api_token"] = token.strip()

    if not token.strip():
        st.warning("Please provide a DRF token in the sidebar.")
        return None

    return DashboardApiClient(base_url=base_url.strip(), token=token.strip())
