from types import SimpleNamespace

from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES


def test_config_center_snapshot_uses_formal_sdk_through_core_only_registry(monkeypatch):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls = []
    snapshot = {"generated_at": "2026-07-12T00:00:00Z", "sections": [{"items": []}]}
    module = SimpleNamespace(
        get_snapshot=lambda: calls.append("get_snapshot") or snapshot,
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(config_center=module),
    )
    monkeypatch.setattr(
        server_module.CORE_DISPATCHER,
        "_role_provider",
        lambda: "staff",
    )

    manifest = CapabilityRegistryLoader().build_registry()["config_center.read.snapshot"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("get_config_center_snapshot",)
    assert "get_config_center_snapshot" in server_module.INTERNAL_LEGACY_TOOL_FALLBACKS

    result = server_module.CORE_DISPATCHER.call(
        capability_key="config_center.read.snapshot",
        arguments={},
    )

    assert "agom_capability_call" in CORE_TOOL_NAMES
    assert result["status"] == "completed"
    assert result["result"] == snapshot
    assert calls == ["get_snapshot"]
