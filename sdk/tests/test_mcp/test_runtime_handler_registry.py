from types import SimpleNamespace

import pytest

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.runtime_handlers import common
from agomtradepro_mcp.registry.runtime_handlers import registry as runtime_registry


def test_runtime_handler_registry_covers_every_manifest_executor():
    import agomtradepro_mcp.server as server_module

    missing = []
    for manifest in CapabilityRegistryLoader().load_manifests():
        handlers = (
            server_module.INTERNAL_GOVERNED_HANDLERS
            if manifest.executor_kind == "internal_handler"
            else server_module.INTERNAL_LEGACY_TOOL_FALLBACKS
        )
        if manifest.executor_ref not in handlers:
            missing.append((manifest.capability_key, manifest.executor_ref))

    assert missing == []


def test_runtime_handler_registry_rejects_duplicate_executor_keys(monkeypatch):
    first = SimpleNamespace(LEGACY_TOOL_FALLBACKS={"same": lambda: 1})
    second = SimpleNamespace(LEGACY_TOOL_FALLBACKS={"same": lambda: 2})
    monkeypatch.setattr(runtime_registry, "OWNER_HANDLER_MODULES", (first, second))

    with pytest.raises(RuntimeError, match="Duplicate runtime handlers"):
        runtime_registry._merge_registry("LEGACY_TOOL_FALLBACKS")


def test_runtime_legacy_tool_caller_fails_closed_before_composition(monkeypatch):
    monkeypatch.setattr(common, "_legacy_tool_caller", None)

    with pytest.raises(RuntimeError, match="Legacy tool caller is not configured"):
        common._call_registered_tool("legacy_tool", {})
