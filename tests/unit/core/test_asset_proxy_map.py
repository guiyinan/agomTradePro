from core.integration.asset_proxy_map import get_runtime_asset_proxy_map


def test_get_runtime_asset_proxy_map_uses_account_system_settings(monkeypatch):
    monkeypatch.setattr(
        "core.integration.asset_proxy_map.SystemSettingsModel.get_runtime_asset_proxy_map",
        classmethod(lambda cls: {"equity": "510300.SH"}),
    )

    assert get_runtime_asset_proxy_map() == {"equity": "510300.SH"}
