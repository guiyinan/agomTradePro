"""Structured registry for runtime action patches."""

from __future__ import annotations

from .tui_metadata_runtime_action_patch_alpha_policy import RUNTIME_ACTION_PATCHES_ALPHA_POLICY
from .tui_metadata_runtime_action_patch_execution import RUNTIME_ACTION_PATCHES_EXECUTION
from .tui_metadata_runtime_action_patch_system_audit import RUNTIME_ACTION_PATCHES_SYSTEM_AUDIT

RUNTIME_ACTION_PATCHES = {
    **RUNTIME_ACTION_PATCHES_ALPHA_POLICY,
    **RUNTIME_ACTION_PATCHES_EXECUTION,
    **RUNTIME_ACTION_PATCHES_SYSTEM_AUDIT,
}
