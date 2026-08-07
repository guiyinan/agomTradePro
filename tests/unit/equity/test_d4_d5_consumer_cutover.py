"""D4/D5 canonical consumer cutover and lineage contracts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from django.contrib import admin

from apps.equity.domain.entities import FinancialData, ValuationMetrics
from apps.equity.infrastructure.fundamentals_repository import (
    StockFundamentalsRepositoryMixin,
)
from apps.equity.infrastructure.models import (
    FinancialDataModel,
    StockDailyModel,
    StockInfoModel,
    ValuationModel,
)
from apps.fund.infrastructure.models import FundNetValueModel
from apps.sector.infrastructure.models import SectorConstituentModel


def test_legacy_fact_models_are_not_exposed_as_admin_entrypoints() -> None:
    """All retained pre-M9 fact schemas must be absent from operational Admin."""

    import apps.equity.interface.admin  # noqa: F401
    import apps.fund.interface.admin  # noqa: F401
    import apps.sector.interface.admin  # noqa: F401

    for model in (
        StockInfoModel,
        StockDailyModel,
        FinancialDataModel,
        ValuationModel,
        FundNetValueModel,
        SectorConstituentModel,
    ):
        assert admin.site.is_registered(model) is False


def test_compatibility_financial_dto_writes_canonical_lineage() -> None:
    """Compatibility DTO names must not publish a fake legacy repository source."""

    observed_at = datetime(2026, 8, 7, 1, 0, tzinfo=UTC)
    financial = FinancialData(
        stock_code="002156.SZ",
        report_date=date(2026, 6, 30),
        revenue=Decimal("100"),
        net_profit=Decimal("10"),
        revenue_growth=5.0,
        net_profit_growth=6.0,
        total_assets=Decimal("200"),
        total_liabilities=Decimal("80"),
        equity=Decimal("120"),
        roe=8.0,
        roa=4.0,
        debt_ratio=40.0,
        source="equity_legacy_repo",
        fetched_at=observed_at,
    )

    facts = StockFundamentalsRepositoryMixin()._financial_entity_to_dc_facts(
        financial,
        "2Q",
    )

    assert facts
    assert {fact.source for fact in facts} == {"equity_application_port"}
    assert {fact.fetched_at for fact in facts} == {observed_at}
    assert {fact.extra.get("upstream_source") for fact in facts} == {"equity_legacy_repo"}


def test_unknown_valuation_dto_writes_canonical_lineage_and_aware_time() -> None:
    """Unknown compatibility provenance is retained as metadata, not owner identity."""

    source_updated_at = datetime(2026, 8, 7, 1, 5, tzinfo=UTC)
    valuation = ValuationMetrics(
        stock_code="002156.SZ",
        trade_date=date(2026, 8, 7),
        pe=20.0,
        pb=3.0,
        ps=2.0,
        total_mv=Decimal("1000000000"),
        circ_mv=Decimal("800000000"),
        dividend_yield=1.0,
        source_provider="unknown",
        source_updated_at=source_updated_at,
        fetched_at=datetime(2026, 8, 7, 1, 6),
    )

    fact = StockFundamentalsRepositoryMixin()._valuation_entity_to_dc_fact(valuation)

    assert fact.source == "equity_application_port"
    assert fact.extra == {"upstream_source": "unknown"}
    assert fact.available_at == source_updated_at
    assert fact.fetched_at.tzinfo is not None
    assert fact.fetched_at.utcoffset() is not None


def test_all_dataset_ownership_states_match_completed_consumer_cutover() -> None:
    """Machine ownership state must distinguish retained schemas from canonical-only."""

    root = Path(__file__).resolve().parents[3]
    payload = json.loads(
        (root / "governance" / "data_ownership_contracts.json").read_text(encoding="utf-8")
    )
    statuses = {item["dataset_key"]: item["migration_status"] for item in payload["datasets"]}

    for dataset_key in (
        "asset.master",
        "equity.price.bar",
        "fund.nav",
        "macro.fact",
        "equity.financial.fact",
        "equity.valuation.fact",
        "sector.membership",
    ):
        assert statuses[dataset_key] == "canonical_read_with_legacy_audit"
    for dataset_key in (
        "market.news",
        "market.capital_flow",
        "reference.publisher",
    ):
        assert statuses[dataset_key] == "canonical_only"
