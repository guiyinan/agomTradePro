"""Runtime TUI action patches for the dedicated Qlib configuration task."""

from __future__ import annotations

from typing import Any

_QLIB_CENTER_ACTION_KEYS: tuple[str, ...] = (
    "config_center.qlib_runtime",
    "config_center.qlib_runtime_update",
    "config_center.training_profiles",
    "config_center.training_profile_save",
    "config_center.training_runs",
    "config_center.training_run_detail",
    "config_center.training_run_trigger",
)

RUNTIME_ACTION_PATCHES_CONFIG_CENTER: dict[str, dict[str, Any]] = {
    action_key: {"screen_key": "system.qlib-center"}
    for action_key in _QLIB_CENTER_ACTION_KEYS
}

for _confirmed_action_key in (
    "config_center.qlib_runtime_update",
    "config_center.training_profile_save",
    "config_center.training_run_trigger",
):
    RUNTIME_ACTION_PATCHES_CONFIG_CENTER[_confirmed_action_key].update(
        {
            "effect": "update",
            "confirmation_required": True,
        }
    )
