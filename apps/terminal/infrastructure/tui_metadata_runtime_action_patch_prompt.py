"""Runtime action routing patches for the Prompt workbench."""

from __future__ import annotations

from typing import Any

_PROMPT_READ_ACTION_KEYS: tuple[str, ...] = (
    "auto.api.get.api.prompt.templates.categories",
    "auto.api.get.api.prompt.chains.execution_modes",
    "auto.api.get.api.prompt.logs",
    "param.api.get.api.prompt.templates.pk",
    "param.api.get.api.prompt.chains.pk",
    "param.api.get.api.prompt.logs.pk",
)

RUNTIME_ACTION_PATCHES_PROMPT: dict[str, dict[str, Any]] = {
    action_key: {"screen_key": "prompt.workbench"}
    for action_key in _PROMPT_READ_ACTION_KEYS
}
