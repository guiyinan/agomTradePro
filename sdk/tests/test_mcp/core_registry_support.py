# ruff: noqa: F401, I001
"""Phase-1 tests for MCP core registry and unified tools."""

import asyncio

from datetime import date

from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

from agomtradepro_mcp.registry.manifest import (
    CapabilityManifest,
    CapabilityManifestValidationError,
)

from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES


def _capture_governed_audit_events(monkeypatch: pytest.MonkeyPatch, dispatcher) -> list[dict]:
    events: list[dict] = []

    def _log_governed_capability_event(**kwargs):
        events.append(dict(kwargs))
        return "audit-log-1"

    monkeypatch.setattr(
        dispatcher,
        "_audit_logger",
        SimpleNamespace(log_governed_capability_event=_log_governed_capability_event),
    )
    return events


__all__ = [name for name in globals() if not name.startswith("__")]
