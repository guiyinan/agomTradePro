from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from apps.asset_analysis.application.pool_service import (
    AssetPoolClassifier,
    AssetPoolManager,
)
from apps.asset_analysis.domain.entities import AssetScore, AssetType
from apps.asset_analysis.domain.pool import (
    PoolCategory,
    PoolConfig,
    PoolType,
)
from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.asset_analysis.infrastructure.repositories import (
    DjangoAssetPoolQueryRepository,
)


def _config(
    category: PoolCategory = PoolCategory.EQUITY,
    *,
    min_total_score: float = 60.0,
) -> PoolConfig:
    return PoolConfig(
        pool_type=PoolType.INVESTABLE,
        asset_category=category,
        min_total_score=min_total_score,
        min_regime_score=50.0,
        min_policy_score=50.0,
        max_total_score=30.0,
        max_regime_score=40.0,
        max_policy_score=40.0,
    )


def _context() -> ScoreContext:
    return ScoreContext(
        current_regime="Recovery",
        policy_level="P1",
        sentiment_index=0.0,
        active_signals=[],
        score_date=date(2026, 7, 24),
    )


def _score(
    asset_type: AssetType = AssetType.EQUITY,
    *,
    total_score: float = 80.0,
) -> AssetScore:
    return AssetScore(
        asset_type=asset_type,
        asset_code="600000.SH",
        asset_name="测试资产",
        total_score=total_score,
        regime_score=80.0,
        policy_score=80.0,
        sentiment_score=70.0,
        signal_score=70.0,
    )


def test_classifier_uses_injected_thresholds() -> None:
    strict_classifier = AssetPoolClassifier([_config(min_total_score=90.0)])
    permissive_classifier = AssetPoolClassifier([_config(min_total_score=60.0)])

    strict_entry = strict_classifier.classify(_score(), _context())
    permissive_entry = permissive_classifier.classify(_score(), _context())

    assert strict_entry.pool_type == PoolType.CANDIDATE
    assert permissive_entry.pool_type == PoolType.INVESTABLE


def test_classifier_rejects_missing_duplicate_and_unsupported_config() -> None:
    with pytest.raises(ValueError, match="Duplicate active pool config"):
        AssetPoolClassifier([_config(), _config()])

    classifier = AssetPoolClassifier([_config()])
    with pytest.raises(ValueError, match="Missing active pool config"):
        classifier.classify(_score(AssetType.FUND), _context())

    with pytest.raises(ValueError, match="Unsupported pool asset type"):
        classifier.classify(_score(AssetType.SECTOR), _context())


def test_classifier_rejects_non_finite_score_and_category_mismatch() -> None:
    classifier = AssetPoolClassifier([_config()])
    with pytest.raises(ValueError, match="total_score must be finite"):
        classifier.classify(_score(total_score=float("nan")), _context())

    manager = AssetPoolManager([_config()])
    with pytest.raises(ValueError, match="Asset category mismatch"):
        manager.create_pools(
            [_score()],
            _context(),
            PoolCategory.FUND,
        )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("min_total_score", float("nan")),
        ("watch_min_score", 60.0),
        ("max_pe_ratio", -1.0),
    ],
)
def test_pool_config_rejects_invalid_financial_thresholds(
    field_name: str,
    field_value: float,
) -> None:
    values = {
        "pool_type": PoolType.INVESTABLE,
        "asset_category": PoolCategory.EQUITY,
        field_name: field_value,
    }
    with pytest.raises(ValueError):
        PoolConfig(**values)


@pytest.mark.django_db
def test_repository_reads_seeded_pool_thresholds() -> None:
    configs = DjangoAssetPoolQueryRepository().list_active_pool_configs()

    configs_by_category = {config.asset_category: config for config in configs}
    assert configs_by_category[PoolCategory.EQUITY].min_total_score == 60.0
    assert configs_by_category[PoolCategory.FUND].min_total_score == 65.0
    assert configs_by_category[PoolCategory.BOND].min_policy_score == 60.0


@pytest.mark.parametrize(
    ("market_cap", "pe_ratio", "pb_ratio", "expected_market_cap"),
    [
        (None, None, None, None),
        (Decimal("123456789.25"), 8.5, 1.25, 123456789.25),
    ],
)
def test_equity_pool_screener_preserves_raw_valuation_metadata(
    monkeypatch: pytest.MonkeyPatch,
    market_cap: Decimal | None,
    pe_ratio: float | None,
    pb_ratio: float | None,
    expected_market_cap: float | None,
) -> None:
    from apps.equity.application.services import (
        EquityMultiDimScorer,
        screen_equity_assets_for_pool,
    )
    from apps.equity.domain.entities import EquityAssetScore

    stock = EquityAssetScore(
        stock_code="000001.SZ",
        stock_name="平安银行",
        sector="银行",
        market="SZ",
        list_date=None,
        pe_ratio=pe_ratio,
        pb_ratio=pb_ratio,
        market_cap=market_cap,
        total_score=82.0,
        regime_score=81.0,
        policy_score=80.0,
        sentiment_score=79.0,
        signal_score=78.0,
        technical_score=77.0,
        fundamental_score=76.0,
        valuation_score=75.0,
        rank=1,
        allocation_percent=15.0,
        risk_level="中低风险",
    )

    class _EquityRepo:
        def get_assets_by_filter(
            self,
            asset_type: str,
            filters: dict[str, object],
        ) -> list[EquityAssetScore]:
            assert asset_type == "equity"
            return [stock]

    monkeypatch.setattr(
        "apps.equity.application.services.get_equity_asset_repository",
        lambda: _EquityRepo(),
    )
    monkeypatch.setattr(
        EquityMultiDimScorer,
        "score_batch",
        lambda self, assets, context: [stock],
    )

    screened = screen_equity_assets_for_pool(_context(), {})

    assert len(screened) == 1
    asset = screened[0]
    assert isinstance(asset, AssetScore)
    assert asset.asset_type is AssetType.EQUITY
    assert asset.asset_code == "000001.SZ"
    assert asset.asset_name == "平安银行"
    assert asset.total_score == 82.0
    assert asset.regime_score == 81.0
    assert asset.policy_score == 80.0
    assert asset.sentiment_score == 79.0
    assert asset.signal_score == 78.0
    assert asset.rank == 1
    assert asset.allocation_percent == 15.0
    assert asset.risk_level == "中低风险"
    assert asset.score_date == stock.score_date
    assert asset.context == stock.context
    assert asset.custom_scores == {"technical": 77.0, "fundamental": 76.0, "valuation": 75.0}
    assert asset.market_cap == expected_market_cap
    assert asset.pe_ratio == pe_ratio
    assert asset.pb_ratio == pb_ratio
    assert "market_cap" not in asset.to_dict()
    assert "pe_ratio" not in asset.to_dict()
    assert "pb_ratio" not in asset.to_dict()

    pools = AssetPoolManager([_config()]).create_pools(
        screened,
        _context(),
        PoolCategory.EQUITY,
    )
    entry = pools[PoolType.INVESTABLE][0]
    assert entry.asset_code == "000001.SZ"
    assert entry.total_score == 82.0
    assert entry.market_cap == expected_market_cap
    assert entry.pe_ratio == pe_ratio
    assert entry.pb_ratio == pb_ratio


def test_equity_pool_adapter_rejects_unconvertible_nonmissing_market_cap() -> None:
    from apps.equity.application.services import EquityMultiDimScorer
    from apps.equity.domain.entities import EquityAssetScore

    stock = EquityAssetScore(
        stock_code="000001.SZ",
        stock_name="平安银行",
        sector="银行",
        market="SZ",
        list_date=None,
        market_cap=Decimal("NaN"),
    )
    with pytest.raises(ValueError, match="market_cap"):
        EquityMultiDimScorer._to_pool_asset_score(stock)


def test_fund_pool_screener_adapts_scored_domain_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.fund.application.services import FundMultiDimScorer
    from apps.fund.domain.entities import FundAssetScore

    fund = FundAssetScore(
        fund_code="110011.OF",
        fund_name="测试指数基金",
        fund_type="指数型",
        fund_scale=Decimal("987654321.00"),
        total_score=82.0,
        regime_score=81.0,
        policy_score=80.0,
        sentiment_score=79.0,
        signal_score=78.0,
        manager_score=77.0,
        fund_flow_score=76.0,
        fund_size_score=75.0,
        performance_score=74.0,
        rank=1,
        allocation_percent=20.0,
        risk_level="中高风险",
    )

    class _FundRepo:
        def get_assets_by_filter(
            self,
            asset_type: str,
            filters: dict[str, object],
        ) -> list[FundAssetScore]:
            assert asset_type == "fund"
            return [fund]

    from apps.fund.application import services as fund_services

    monkeypatch.setattr(fund_services, "get_fund_asset_repository", lambda: _FundRepo())
    monkeypatch.setattr(
        FundMultiDimScorer,
        "score_batch",
        lambda self, assets, context: [fund],
    )

    screened = fund_services.screen_fund_assets_for_pool(_context(), {})

    assert len(screened) == 1
    asset = screened[0]
    assert isinstance(asset, AssetScore)
    assert asset.asset_type is AssetType.FUND
    assert asset.asset_code == "110011.OF"
    assert asset.asset_name == "测试指数基金"
    assert asset.total_score == 82.0
    assert asset.custom_scores == {
        "manager": 77.0,
        "flow": 76.0,
        "size": 75.0,
        "performance": 74.0,
    }

    pools = AssetPoolManager([_config(PoolCategory.FUND)]).create_pools(
        screened,
        _context(),
        PoolCategory.FUND,
    )
    entry = pools[PoolType.INVESTABLE][0]
    assert entry.asset_code == "110011.OF"
    assert entry.total_score == 82.0
    assert entry.market_cap is None
    assert entry.pe_ratio is None
    assert entry.pb_ratio is None


def test_pool_classifier_rejects_raw_string_asset_type_without_attribute_error() -> None:
    with pytest.raises(ValueError, match="Unsupported pool asset type"):
        AssetPoolClassifier._get_category("equity")
