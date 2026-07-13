"""Controlled Config Center read handlers."""

from __future__ import annotations

from typing import Any


def get_config_center_snapshot() -> dict[str, Any]:
    """Read the staff-only configuration summary through the formal SDK."""

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.config_center.get_snapshot()
    if not isinstance(result, dict):
        raise ValueError("config_center.read.snapshot returned an invalid payload")
    return dict(result)
