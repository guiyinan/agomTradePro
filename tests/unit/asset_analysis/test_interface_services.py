from apps.asset_analysis.application import interface_services


class _StubRegistry:
    def __init__(self):
        self.calls: list[tuple[str, object, dict]] = []

    def get_pool_screener(self, asset_type: str):
        def _screen(context, filters):
            self.calls.append((asset_type, context, filters))
            return [{"asset_type": asset_type, "context": context, "filters": filters}]

        return _screen


def test_screen_equity_assets_uses_registered_equity_screener(monkeypatch):
    registry = _StubRegistry()
    monkeypatch.setattr(
        interface_services,
        "get_asset_analysis_market_registry",
        lambda: registry,
    )

    result = interface_services.screen_equity_assets(
        context={"regime": "Recovery"},
        filters={"sector": "bank"},
    )

    assert registry.calls == [("equity", {"regime": "Recovery"}, {"sector": "bank"})]
    assert result == [
        {
            "asset_type": "equity",
            "context": {"regime": "Recovery"},
            "filters": {"sector": "bank"},
        }
    ]


def test_screen_fund_assets_uses_registered_fund_screener(monkeypatch):
    registry = _StubRegistry()
    monkeypatch.setattr(
        interface_services,
        "get_asset_analysis_market_registry",
        lambda: registry,
    )

    result = interface_services.screen_fund_assets(
        context={"regime": "Recovery"},
        filters={"fund_type": "ETF"},
    )

    assert registry.calls == [("fund", {"regime": "Recovery"}, {"fund_type": "ETF"})]
    assert result == [
        {
            "asset_type": "fund",
            "context": {"regime": "Recovery"},
            "filters": {"fund_type": "ETF"},
        }
    ]
