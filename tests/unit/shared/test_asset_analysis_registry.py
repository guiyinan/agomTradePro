from shared.infrastructure.asset_analysis_registry import (
    AssetAnalysisMarketRegistry,
)


class _FakeRepo:
    def get_assets_by_filter(self, asset_type: str, filters: dict, max_count: int = 100):
        return [{"asset_type": asset_type, "filters": filters, "max_count": max_count}]

    def get_asset_by_code(self, asset_type: str, asset_code: str):
        return {"asset_type": asset_type, "asset_code": asset_code}


def test_registry_resolves_registered_asset_repository():
    registry = AssetAnalysisMarketRegistry()
    registry.register_asset_repository("equity", lambda: _FakeRepo())

    repo = registry.get_asset_repository("equity")

    assert isinstance(repo, _FakeRepo)


def test_registry_resolves_registered_pool_screener():
    registry = AssetAnalysisMarketRegistry()
    registry.register_pool_screener(
        "fund",
        lambda context, filters: [{"context": context, "filters": filters}],
    )

    result = registry.get_pool_screener("fund")(
        {"regime": "Recovery"},
        {"fund_type": "ETF"},
    )

    assert result == [{"context": {"regime": "Recovery"}, "filters": {"fund_type": "ETF"}}]


def test_registry_resolves_registered_name_resolver():
    registry = AssetAnalysisMarketRegistry()
    registry.register_name_resolver(
        "equity",
        lambda codes: {code: f"name:{code}" for code in codes},
    )

    result = registry.get_name_resolver("equity")(["000001.SZ"])

    assert result == {"000001.SZ": "name:000001.SZ"}
