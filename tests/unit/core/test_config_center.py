from types import SimpleNamespace

from core.application.config_center import build_config_center_snapshot, list_config_capabilities


def test_list_config_capabilities_contains_core_items():
    capabilities = list_config_capabilities()
    keys = {item["key"] for item in capabilities}

    assert "agent_runtime_operator" in keys
    assert "system_settings" in keys
    assert "valuation_repair" in keys
    assert "beta_gate" in keys
    assert "ai_provider" in keys
    assert "trading_cost" in keys
    assert "data_center_providers" in keys
    assert "data_center_runtime" in keys


def test_build_config_center_snapshot_filters_staff_items_for_normal_user(monkeypatch):
    monkeypatch.setattr(
        "core.application.config_center._SUMMARY_BUILDERS",
        {
            "account_settings": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "agent_runtime_operator": lambda user: {
                "status": "configured",
                "summary": {"message": "ok"},
            },
            "system_settings": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "data_center_providers": lambda user: {
                "status": "configured",
                "summary": {"message": "ok"},
            },
            "data_center_runtime": lambda user: {
                "status": "configured",
                "summary": {"message": "ok"},
            },
            "beta_gate": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "valuation_repair": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "ai_provider": lambda user: {"status": "configured", "summary": {"message": "ok"}},
            "trading_cost": lambda user: {"status": "configured", "summary": {"message": "ok"}},
        },
    )

    snapshot = build_config_center_snapshot(SimpleNamespace(is_staff=False))
    item_keys = {item["key"] for section in snapshot["sections"] for item in section["items"]}

    assert "trading_cost" in item_keys
    assert "agent_runtime_operator" not in item_keys
    assert "valuation_repair" not in item_keys
    assert "system_settings" not in item_keys
    assert "data_center_providers" not in item_keys
    assert "data_center_runtime" not in item_keys

    mcp_items = [
        item
        for section in snapshot["sections"]
        for item in section["items"]
        if item["key"] == "mcp_guide"
    ]
    assert len(mcp_items) == 1
    assert mcp_items[0]["status"] == "attention"
    assert "未配置" in mcp_items[0]["summary"]["message"]
