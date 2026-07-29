"""Audience corrections for auto-discovered Data Center admin reads."""

from __future__ import annotations

from typing import Any

_ADMIN_DATA_CENTER_READS: tuple[str, ...] = (
    "auto.api.get.api.data-center.indicators",
)

RUNTIME_ACTION_PATCHES_DATA_CENTER: dict[str, dict[str, Any]] = {
    action_key: {
        "audience": "admin",
        "risk": "admin",
    }
    for action_key in _ADMIN_DATA_CENTER_READS
}
