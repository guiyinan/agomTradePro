from core.integration.realtime_prices import fetch_latest_prices


class _FakePricePollingUseCase:
    def get_latest_prices(self, asset_codes: list[str]):
        return [{"asset_code": code, "price": 1.23} for code in asset_codes]


def test_fetch_latest_prices_bridge_uses_realtime_use_case(monkeypatch):
    monkeypatch.setattr(
        "core.integration.realtime_prices.PricePollingUseCase",
        lambda: _FakePricePollingUseCase(),
    )

    assert fetch_latest_prices(["000001.SZ"]) == [{"asset_code": "000001.SZ", "price": 1.23}]
