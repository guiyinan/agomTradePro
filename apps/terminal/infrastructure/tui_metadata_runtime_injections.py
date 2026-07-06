"""Compatibility exports for runtime-injected TUI metadata constants."""

from __future__ import annotations

from .tui_metadata_runtime_injection_advisor import (
    RUNTIME_ADVISOR_ACTION,
    RUNTIME_ADVISOR_SCREEN,
    RUNTIME_ADVISOR_SELECTOR_ACTION,
)
from .tui_metadata_runtime_injection_capability_router import (
    RUNTIME_CAPABILITY_ROUTER_ACTIONS,
    RUNTIME_CAPABILITY_ROUTER_MODULE,
    RUNTIME_CAPABILITY_ROUTER_SCREEN,
)
from .tui_metadata_runtime_injection_cli import (
    RUNTIME_CLI_CHAT_ACTION,
    RUNTIME_CLI_GROUP,
    RUNTIME_CLI_MODULE,
    RUNTIME_CLI_SCREEN,
)
from .tui_metadata_runtime_injection_config_center import RUNTIME_CONFIG_CENTER_ACTIONS
from .tui_metadata_runtime_injection_risk_center import (
    RUNTIME_RISK_CENTER_ACTIONS,
    RUNTIME_RISK_CENTER_MODULE,
    RUNTIME_RISK_CENTER_SCREEN,
)

__all__ = [
    "RUNTIME_ADVISOR_ACTION",
    "RUNTIME_ADVISOR_SCREEN",
    "RUNTIME_ADVISOR_SELECTOR_ACTION",
    "RUNTIME_CAPABILITY_ROUTER_ACTIONS",
    "RUNTIME_CAPABILITY_ROUTER_MODULE",
    "RUNTIME_CAPABILITY_ROUTER_SCREEN",
    "RUNTIME_CLI_CHAT_ACTION",
    "RUNTIME_CLI_GROUP",
    "RUNTIME_CLI_MODULE",
    "RUNTIME_CLI_SCREEN",
    "RUNTIME_CONFIG_CENTER_ACTIONS",
    "RUNTIME_RISK_CENTER_ACTIONS",
    "RUNTIME_RISK_CENTER_MODULE",
    "RUNTIME_RISK_CENTER_SCREEN",
]
