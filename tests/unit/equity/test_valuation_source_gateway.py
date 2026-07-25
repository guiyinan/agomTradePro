from datetime import UTC, date, datetime
from unittest.mock import patch

from apps.data_center.domain.entities import ValuationFact
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
        fetched_at=datetime(2026, 7, 25, tzinfo=UTC),
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
