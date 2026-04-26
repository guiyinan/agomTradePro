from core.integration.asset_names import resolve_asset_names_for_signals


def test_resolve_asset_names_for_signals_uses_asset_analysis_service(monkeypatch):
    monkeypatch.setattr(
        "core.integration.asset_names._resolve_asset_names",
        lambda asset_codes: {code: f"name:{code}" for code in asset_codes},
    )

    assert resolve_asset_names_for_signals(["000001.SZ"]) == {
        "000001.SZ": "name:000001.SZ"
    }
