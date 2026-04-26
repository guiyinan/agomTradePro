from core.integration.asset_analysis_market_sources import (
    get_market_asset_repository,
    screen_equity_assets_for_pool,
    screen_fund_assets_for_pool,
)


class _FakeEquityRepo:
    def get_assets_by_filter(self, *, asset_type, filters):
        assert asset_type == "equity"
        return [{"filters": filters}]


class _FakeEquityScorer:
    def __init__(self, repo):
        self.repo = repo

    def score_batch(self, assets, context):
        return [{"assets": assets, "context": context}]


class _FakeFundRepo:
    def get_assets_by_filter(self, *, asset_type, filters):
        assert asset_type == "fund"
        return [{"filters": filters}]


class _FakeFundScorer:
    def __init__(self, repo):
        self.repo = repo

    def score_batch(self, assets, context):
        return [{"assets": assets, "context": context}]


def test_screen_equity_assets_for_pool_uses_equity_module(monkeypatch):
    monkeypatch.setattr(
        "apps.equity.infrastructure.repositories.DjangoEquityAssetRepository",
        _FakeEquityRepo,
    )
    monkeypatch.setattr(
        "apps.equity.application.services.EquityMultiDimScorer",
        _FakeEquityScorer,
    )

    result = screen_equity_assets_for_pool(
        context={"regime": "Recovery"},
        filters={"sector": "bank", "max_pe": 20},
    )

    assert result == [
        {
            "assets": [{"filters": {"sector": "bank", "max_pe": 20}}],
            "context": {"regime": "Recovery"},
        }
    ]


def test_screen_fund_assets_for_pool_uses_fund_module(monkeypatch):
    monkeypatch.setattr(
        "apps.fund.infrastructure.repositories.DjangoFundAssetRepository",
        _FakeFundRepo,
    )
    monkeypatch.setattr(
        "apps.fund.application.services.FundMultiDimScorer",
        _FakeFundScorer,
    )

    result = screen_fund_assets_for_pool(
        context={"regime": "Recovery"},
        filters={"fund_type": "ETF", "min_scale": 1000000},
    )

    assert result == [
        {
            "assets": [{"filters": {"fund_type": "ETF", "min_scale": 1000000}}],
            "context": {"regime": "Recovery"},
        }
    ]


def test_get_market_asset_repository_uses_owning_modules(monkeypatch):
    monkeypatch.setattr(
        "apps.equity.infrastructure.repositories.DjangoEquityAssetRepository",
        _FakeEquityRepo,
    )
    monkeypatch.setattr(
        "apps.fund.infrastructure.repositories.DjangoFundAssetRepository",
        _FakeFundRepo,
    )

    assert isinstance(get_market_asset_repository("equity"), _FakeEquityRepo)
    assert isinstance(get_market_asset_repository("fund"), _FakeFundRepo)
