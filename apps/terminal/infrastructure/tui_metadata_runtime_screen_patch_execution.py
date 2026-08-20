"""Runtime screen patches for execution and risk-control TUI surfaces."""

from __future__ import annotations

from typing import Any

RUNTIME_SCREEN_PATCHES_EXECUTION: dict[str, dict[str, Any]] = {}

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS_EXECUTION: dict[str, set[str]] = {
    "broker-execution.qmt-setup": {"auto.api.get.api.broker-execution.qmt-onboarding"},
    "execution.accounts": {"auto.api.get.api.account.positions"},
    "execution.events": {"auto.api.get.api.events"},
    "execution.share": {"auto.api.get.api.share"},
}
