"""Runtime screen patch metadata for operations-only TUI cleanup rules."""

from __future__ import annotations

from typing import Any

RUNTIME_SCREEN_PATCHES_OPS: dict[str, dict[str, Any]] = {}

RUNTIME_REDUNDANT_SCREEN_ACTION_KEYS_OPS: dict[str, set[str]] = {
    "ai-ops.capabilities": {"param.api.get.api.ai-capability.capabilities.pk"}
}
