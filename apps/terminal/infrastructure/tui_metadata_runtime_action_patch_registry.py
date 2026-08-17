"""Structured registry for runtime action patches."""

from __future__ import annotations

from .tui_metadata_runtime_action_patch_alpha_policy import RUNTIME_ACTION_PATCHES_ALPHA_POLICY
from .tui_metadata_runtime_action_patch_config_center import (
    RUNTIME_ACTION_PATCHES_CONFIG_CENTER,
)
from .tui_metadata_runtime_action_patch_data_center import (
    RUNTIME_ACTION_PATCHES_DATA_CENTER,
)
from .tui_metadata_runtime_action_patch_execution import RUNTIME_ACTION_PATCHES_EXECUTION
from .tui_metadata_runtime_action_patch_macro_data import RUNTIME_ACTION_PATCHES_MACRO_DATA
from .tui_metadata_runtime_action_patch_prompt import RUNTIME_ACTION_PATCHES_PROMPT
from .tui_metadata_runtime_action_patch_system_audit import RUNTIME_ACTION_PATCHES_SYSTEM_AUDIT

RUNTIME_ACTION_PATCHES = {
    **RUNTIME_ACTION_PATCHES_ALPHA_POLICY,
    **RUNTIME_ACTION_PATCHES_CONFIG_CENTER,
    **RUNTIME_ACTION_PATCHES_DATA_CENTER,
    **RUNTIME_ACTION_PATCHES_EXECUTION,
    **RUNTIME_ACTION_PATCHES_MACRO_DATA,
    **RUNTIME_ACTION_PATCHES_PROMPT,
    **RUNTIME_ACTION_PATCHES_SYSTEM_AUDIT,
}
