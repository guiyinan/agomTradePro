"""Audience and presentation corrections for existing Data Center reads."""

from __future__ import annotations

from typing import Any

from .tui_metadata_runtime_injection_operator import OPERATOR_MARKET_CONTEXT_COLUMNS

_ADMIN_DATA_CENTER_READS: tuple[str, ...] = ("auto.api.get.api.data-center.indicators",)

RUNTIME_ACTION_PATCHES_DATA_CENTER: dict[str, dict[str, Any]] = {
    action_key: {
        "audience": "admin",
        "risk": "admin",
    }
    for action_key in _ADMIN_DATA_CENTER_READS
}

RUNTIME_ACTION_PATCHES_DATA_CENTER["operator.home.market_context"] = {
    "view_model": {
        "columns": [dict(column) for column in OPERATOR_MARKET_CONTEXT_COLUMNS],
    },
}
