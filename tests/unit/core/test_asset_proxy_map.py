from core.integration.asset_proxy_map import get_runtime_asset_proxy_map


def test_get_runtime_asset_proxy_map_uses_config_center_summary_service(monkeypatch):
    class _Service:
        @staticmethod
        def get_runtime_asset_proxy_map():
            return {"equity": "510300.SH"}

    monkeypatch.setattr(
        "core.integration.asset_proxy_map.get_config_center_summary_service",
        lambda: _Service(),
    )

    assert get_runtime_asset_proxy_map() == {"equity": "510300.SH"}
