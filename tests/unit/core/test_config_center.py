from types import SimpleNamespace

from core.application.config_center import build_config_center_snapshot, list_config_capabilities


def test_list_config_capabilities_contains_core_items():
    capabilities = list_config_capabilities()
    keys = {item["key"] for item in capabilities}

    assert "system_settings" in keys
    assert "valuation_repair" in keys
    assert "beta_gate" in keys
    assert "ai_provider" in keys
    assert "trading_cost" in keys


def test_build_config_center_snapshot_filters_staff_items_for_normal_user(monkeypatch):
    monkeypatch.setattr(
        "core.application.config_center._SUMMARY_BUILDERS",
        {
            "system_settings": lambda: {"status": "configured", "summary": {"message": "ok"}},
            "macro_datasources": lambda: {"status": "configured", "summary": {"message": "ok"}},
            "market_data_providers": lambda: {"status": "configured", "summary": {"message": "ok"}},
            "beta_gate": lambda: {"status": "configured", "summary": {"message": "ok"}},
            "valuation_repair": lambda: {"status": "configured", "summary": {"message": "ok"}},
            "ai_provider": lambda: {"status": "configured", "summary": {"message": "ok"}},
            "trading_cost": lambda: {"status": "configured", "summary": {"message": "ok"}},
        },
    )

    snapshot = build_config_center_snapshot(SimpleNamespace(is_staff=False))
    item_keys = {
        item["key"]
        for section in snapshot["sections"]
        for item in section["items"]
    }

    assert "trading_cost" in item_keys
    assert "valuation_repair" not in item_keys
    assert "system_settings" not in item_keys
