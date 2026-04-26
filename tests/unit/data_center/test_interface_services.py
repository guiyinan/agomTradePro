from apps.data_center.application.interface_services import fetch_latest_realtime_prices


def test_fetch_latest_realtime_prices_uses_core_bridge(monkeypatch):
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.fetch_latest_prices",
        lambda asset_codes: [{"asset_code": code, "price": 9.87} for code in asset_codes],
    )

    assert fetch_latest_realtime_prices(["510300.SH"]) == [
        {"asset_code": "510300.SH", "price": 9.87}
    ]
