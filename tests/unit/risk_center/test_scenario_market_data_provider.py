"""Published market-data adapter tests for scenario runs."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.risk_center.domain.scenarios import (
    HistoricalWindowParameters,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
)
from apps.risk_center.infrastructure.scenario_market_data_provider import (
    PublishedScenarioMarketDataProvider,
    ScenarioMarketDataUnavailableError,
)


def _revision() -> ScenarioRevision:
    return ScenarioRevision(
        revision_id="revision-1",
        scenario_key="historical.test",
        version=1,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.HISTORICAL_WINDOW,
        parameters=HistoricalWindowParameters(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 3),
            source="published-price-bars",
            event_description="test",
        ),
        assumptions=("published bars",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="operator",
        change_reason="test",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_provider_preserves_bar_observation_and_publication_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.risk_center.infrastructure.scenario_market_data_provider.get_published_price_bar_series",
        lambda asset_code, **kwargs: {
            "publication_id": "publication-1",
            "published_at": "2026-08-01T01:00:00+00:00",
            "must_not_use_for_decision": False,
            "rows": [
                {"timestamp": "2020-01-01", "close": 100},
                {"timestamp": "2020-01-02", "close": 90},
                {"timestamp": "2020-01-03", "close": 99},
            ],
        },
    )

    result = PublishedScenarioMarketDataProvider().get_market_data(
        _revision(),
        asset_codes=("000001.SH",),
        as_of_time=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert result.observed_at == datetime(2020, 1, 3, tzinfo=UTC)
    assert result.published_at == datetime(2026, 8, 1, 1, tzinfo=UTC)
    assert result.evidence_ids == ("publication-1:000001.SH",)
    assert [point.value for point in result.return_series[0].points] == [
        Decimal("-0.1"),
        Decimal("0.1"),
    ]


def test_provider_fails_closed_on_stale_or_unpublished_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.risk_center.infrastructure.scenario_market_data_provider.get_published_price_bar_series",
        lambda asset_code, **kwargs: {
            "must_not_use_for_decision": True,
            "blocked_reason": "price_publication_stale",
            "rows": [],
        },
    )

    with pytest.raises(ScenarioMarketDataUnavailableError, match="stale"):
        PublishedScenarioMarketDataProvider().get_market_data(
            _revision(),
            asset_codes=("000001.SH",),
            as_of_time=datetime(2026, 8, 2, tzinfo=UTC),
        )
