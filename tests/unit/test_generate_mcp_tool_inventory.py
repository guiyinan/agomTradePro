"""Tests for the MCP tool inventory generator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "generate_mcp_tool_inventory.py"
    spec = importlib.util.spec_from_file_location("generate_mcp_tool_inventory", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_inventory_returns_registered_tools():
    module = _load_module()

    payload = module.build_inventory()
    summary = payload["summary"]

    assert summary["total_tools"] > 0
    assert summary["registered_modules"] > 0
    assert summary["by_module"]["account"] > 0
    assert summary["by_module"]["regime"] > 0
    assert summary["by_operation"]["read"] > 0
    assert payload["server_path"] == "sdk/agomtradepro_mcp/server.py"
    assert summary["unsupported_legacy_contract_count"] == 0
    assert summary["legacy_disposition_count"] > 0
    assert summary["legacy_keep_task_count"] == 0

    unsupported = {
        contract["contract_key"]: contract for contract in payload["unsupported_legacy_contracts"]
    }
    assert "realtime.delete.price_alert" not in unsupported
    assert "realtime.price_subscription" not in unsupported
    assert "events.replay" not in unsupported

    tools = {tool["tool_name"]: tool for tool in payload["tools"]}
    assert (
        tools["delete_price_alert"]["disposition_hint"]
        == "candidate_aggregate_or_governed"
    )
    assert tools["delete_price_alert"]["legacy_disposition"] is None
    assert tools["delete_price_alert"]["disposition_rationale"] is None
    assert tools["delete_price_alert"]["recommended_capability_keys"] == ()
    assert tools["delete_price_alert"]["unsupported_contract_key"] is None
    assert tools["get_asset_info"]["legacy_disposition"] == "aggregate"
    assert tools["get_asset_info"]["recommended_capability_keys"] == (
        "rotation.read.asset_detail",
    )
