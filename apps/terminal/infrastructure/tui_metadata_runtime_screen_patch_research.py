"""Runtime screen patches for research-oriented TUI surfaces."""

from __future__ import annotations

from typing import Any

RUNTIME_SCREEN_PATCHES_RESEARCH: dict[str, dict[str, Any]] = {}

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS_RESEARCH: dict[str, set[str]] = {
    "research.alpha-triggers": {"auto.api.get.api.alpha-triggers"},
    "research.signals": {
        "auto.api.get.api.filter",
        "auto.api.get.api.filter.indicators",
        "auto.api.get.api.filter.health",
        "param.api.get.api.filter.config.indicator_code",
        "param.api.get.api.filter.config.str.indicator_code",
    },
}
