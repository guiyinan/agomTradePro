"""T3A validation and serialization contracts for Data Center value objects."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest

from apps.data_center.domain.entities import (
    AssetAlias,
    AssetMaster,
    CapitalFlowFact,
    FinancialFact,
    FundNavFact,
    IndicatorCatalog,
    IndicatorUnitRule,
    MacroFact,
    MarketThermometerConfig,
    MarketThermometerThresholds,
    NewsFact,
    PriceBar,
    ProductionCoverageUniverseConfig,
    PublisherCatalog,
    QuoteSnapshot,
    RawAudit,
    SectorMembershipFact,
    ValuationFact,
)
from apps.data_center.domain.enums import (
    AssetType,
    FinancialPeriodType,
    MarketExchange,
)

TODAY = date(2026, 7, 25)
NOW = datetime(2026, 7, 25, tzinfo=UTC)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProductionCoverageUniverseConfig(universe_id=""),
        lambda: ProductionCoverageUniverseConfig(asset_type=""),
        lambda: ProductionCoverageUniverseConfig(exchanges=[]),
        lambda: ProductionCoverageUniverseConfig(min_active_asset_count=-1),
        lambda: AssetMaster("", "Asset", "", AssetType.STOCK, MarketExchange.SSE),
        lambda: AssetMaster("000001.SZ", "", "", AssetType.STOCK, MarketExchange.SZSE),
        lambda: AssetAlias("", "provider", "alias"),
        lambda: PublisherCatalog("", "Publisher", "government"),
        lambda: IndicatorCatalog("", "Indicator"),
        lambda: IndicatorUnitRule(None, "", dimension_key="other"),
        lambda: IndicatorUnitRule(None, "CN_CPI", dimension_key=""),
        lambda: IndicatorUnitRule(None, "CN_CPI", dimension_key="rate", multiplier_to_storage=0),
        lambda: MacroFact("", TODAY, 1.0, "%", "fixture"),
        lambda: PriceBar("", TODAY, 1, 1, 1, 1),
        lambda: PriceBar("000001.SZ", TODAY, 1, 1, 1, -1),
        lambda: QuoteSnapshot("", NOW, 1, "fixture"),
        lambda: QuoteSnapshot("000001.SZ", NOW, -1, "fixture"),
        lambda: FundNavFact("", TODAY, 1),
        lambda: FinancialFact(
            "",
            TODAY,
            FinancialPeriodType.ANNUAL,
            "revenue",
            1,
        ),
        lambda: ValuationFact("", TODAY),
        lambda: SectorMembershipFact("", "", TODAY),
        lambda: NewsFact("000001.SZ", "", NOW),
        lambda: CapitalFlowFact("", TODAY),
        lambda: MarketThermometerThresholds(
            warm_threshold=80,
            hot_threshold=60,
        ),
        lambda: MarketThermometerConfig(short_window=0),
        lambda: MarketThermometerConfig(component_weights={}),
    ],
)
def test_invalid_value_objects_fail_closed(factory: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        factory()


def test_fact_value_objects_serialize_canonical_fields() -> None:
    objects = [
        AssetMaster(
            "000001.SZ",
            "Asset",
            "A",
            AssetType.STOCK,
            MarketExchange.SZSE,
        ),
        PublisherCatalog("PBOC", "人民银行", "central_bank"),
        IndicatorCatalog("CN_CPI", "居民消费价格"),
        IndicatorUnitRule(None, "CN_CPI", dimension_key="rate"),
        MacroFact("CN_CPI", TODAY, 1.0, "%", "fixture"),
        PriceBar("000001.SZ", TODAY, 1, 2, 0.5, 1.5),
        QuoteSnapshot("000001.SZ", NOW, 1.5, "fixture"),
        FundNavFact("510300.SH", TODAY, 4.5),
        FinancialFact(
            "000001.SZ",
            TODAY,
            FinancialPeriodType.ANNUAL,
            "revenue",
            100,
        ),
        ValuationFact("000001.SZ", TODAY, pe_ttm=10),
        SectorMembershipFact("000001.SZ", "bank", TODAY),
        NewsFact("000001.SZ", "Title", NOW),
        CapitalFlowFact("000001.SZ", TODAY, main_net=1),
        RawAudit("fixture", "macro", {"code": "CN_CPI"}, "success"),
    ]

    payloads = [item.to_dict() for item in objects]

    assert payloads[0]["code"] == "000001.SZ"
    assert payloads[4]["reporting_period"] == TODAY.isoformat()
    assert payloads[-1]["status"] == "success"
