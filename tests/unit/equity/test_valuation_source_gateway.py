from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import patch

from apps.data_center.domain.entities import ValuationFact
from apps.equity.application.query_services import _published_valuation_context
from apps.equity.infrastructure.fundamentals_repository import StockFundamentalsRepositoryMixin
from apps.equity.infrastructure.valuation_source_gateways import (
    ConfiguredValuationGateway,
)


def _fact(*, provider_name: str, pb: float) -> ValuationFact:
    return ValuationFact(
        asset_code="000001.SZ",
        val_date=date(2026, 7, 25),
        pe_ttm=10.0,
        pb=pb,
        market_cap=100_000_000.0,
        float_market_cap=80_000_000.0,
        source="public",
        observed_at=datetime(2026, 7, 25, 7, tzinfo=UTC),
        fetched_at=datetime(2026, 7, 25, 8, tzinfo=UTC),
        extra={
            "source_type": "public",
            "provider_name": provider_name,
        },
    )


def test_configured_gateway_filters_by_canonical_provider_metadata() -> None:
    gateway = ConfiguredValuationGateway("akshare-main")
    with patch.object(
        gateway._valuation_repo,
        "get_series",
        return_value=[
            _fact(provider_name="tushare-backup", pb=2.0),
            _fact(provider_name="akshare-main", pb=1.2),
        ],
    ):
        result = gateway.fetch(
            "000001.SZ",
            date(2026, 7, 25),
            date(2026, 7, 25),
        )

    assert result.source_provider == "akshare-main"
    assert len(result.records) == 1
    assert result.records[0].pb == 1.2
    assert result.records[0].source_provider == "akshare-main"
    assert result.records[0].source_updated_at == datetime(2026, 7, 25, 7, tzinfo=UTC)
    assert result.records[0].fetched_at == datetime(2026, 7, 25, 8, tzinfo=UTC)


def test_public_row_preserves_source_observation_and_unknown_when_missing() -> None:
    observed = datetime(2026, 7, 25, 7, tzinfo=UTC)
    fetched = datetime(2026, 7, 25, 8, tzinfo=UTC)
    parsed = StockFundamentalsRepositoryMixin._valuation_fact_from_public_row(
        {
            "asset_code": "000001.SZ",
            "val_date": "2026-07-25",
            "source": "public",
            "pe_ttm": 10.0,
            "pb": 1.2,
            "market_cap": 100_000_000.0,
            "observed_at": observed.isoformat(),
            "fetched_at": fetched.isoformat(),
        }
    )

    assert parsed is not None
    assert parsed.observed_at == observed
    metrics = StockFundamentalsRepositoryMixin()._dc_fact_to_valuation(parsed)
    assert metrics.source_updated_at == observed
    assert metrics.fetched_at == fetched

    missing = StockFundamentalsRepositoryMixin._valuation_fact_from_public_row(
        {
            "asset_code": "000001.SZ",
            "val_date": "2026-07-25",
            "source": "public",
            "pe_ttm": 10.0,
            "pb": 1.2,
            "market_cap": 100_000_000.0,
            "fetched_at": fetched.isoformat(),
        }
    )
    assert missing is not None
    assert (
        StockFundamentalsRepositoryMixin()._dc_fact_to_valuation(missing).source_updated_at is None
    )
    missing_metrics = StockFundamentalsRepositoryMixin()._dc_fact_to_valuation(missing)
    assert missing_metrics.fetched_at == fetched
    assert missing_metrics.is_valid is False
    assert missing_metrics.quality_flag == "missing_source_observation"
    assert missing_metrics.quality_notes == "missing source observation timestamp"


def test_configured_gateway_marks_missing_source_observation_unusable() -> None:
    row = replace(_fact(provider_name="akshare-main", pb=1.2), observed_at=None)
    gateway = ConfiguredValuationGateway("akshare-main")
    with patch.object(gateway._valuation_repo, "get_series", return_value=[row]):
        result = gateway.fetch(
            "000001.SZ",
            date(2026, 7, 25),
            date(2026, 7, 25),
        )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.source_updated_at is None
    assert record.fetched_at == datetime(2026, 7, 25, 8, tzinfo=UTC)
    assert record.is_valid is False
    assert record.quality_flag == "missing_source_observation"
    assert record.quality_notes == "missing source observation timestamp"


def test_published_context_exposes_distinct_valuation_times() -> None:
    observed = "2026-07-25T07:00:00+00:00"
    fetched = "2026-07-25T08:00:00+00:00"

    context = _published_valuation_context(
        {
            "rows": [
                {
                    "val_date": "2026-07-25",
                    "pe_ttm": 10.0,
                    "observed_at": observed,
                    "fetched_at": fetched,
                }
            ]
        }
    )

    assert context["valuation_source_updated_at"] == observed
    assert context["valuation_fetched_at"] == fetched
