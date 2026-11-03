"""Published market-data adapter tests for scenario runs."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.risk_center.application.scenario_dtos import ScenarioMarketDataDTO
from apps.risk_center.domain.portfolio_risk_sources import SourceObservationPrecision
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


def test_existing_aware_constructor_defaults_to_timestamp_precision() -> None:
    """Existing typed callers keep their actual aware-timestamp constructor."""

    result = ScenarioMarketDataDTO(
        return_series=(),
        evidence_ids=("publication:asset",),
        observed_at=datetime(2026, 8, 1, 10, tzinfo=UTC),
        published_at=datetime(2026, 8, 1, 11, tzinfo=UTC),
    )

    assert result.observation_precision is SourceObservationPrecision.TIMESTAMP
    assert result.observed_on is None


def test_provider_preserves_bar_observation_and_publication_evidence(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def query(asset_code: str, **kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "publication_id": "publication-1",
            "published_at": "2026-08-01T01:00:00+00:00",
            "must_not_use_for_decision": False,
            "rows": [
                {"timestamp": "2020-01-01", "close": 100},
                {"timestamp": "2020-01-02", "close": 90},
                {"timestamp": "2020-01-03", "close": 99},
            ],
        }

    monkeypatch.setattr(
        "apps.risk_center.infrastructure.scenario_market_data_provider.get_published_price_bar_series",
        query,
    )

    as_of = datetime(2026, 8, 2, tzinfo=UTC)
    result = PublishedScenarioMarketDataProvider().get_market_data(
        _revision(),
        asset_codes=("000001.SH",),
        as_of_time=as_of,
    )

    assert result.observed_at is None
    assert result.observed_on == date(2020, 1, 3)
    assert result.observation_precision is SourceObservationPrecision.DATE
    assert result.published_at == datetime(2026, 8, 1, 1, tzinfo=UTC)
    assert result.evidence_ids == ("publication-1:000001.SH",)
    assert calls[0]["knowledge_cutoff"] == as_of
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


def test_provider_preserves_real_latest_bar_time_and_timezone(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.risk_center.infrastructure.scenario_market_data_provider.get_published_price_bar_series",
        lambda asset_code, **kwargs: {
            "publication_id": "publication-time",
            "published_at": "2020-01-03T08:00:00+00:00",
            "must_not_use_for_decision": False,
            "rows": [
                {"timestamp": "2020-01-01", "close": 100},
                {"timestamp": "2020-01-02", "close": 90},
                {"timestamp": "2020-01-03T15:00:00+08:00", "close": 99},
            ],
        },
    )

    result = PublishedScenarioMarketDataProvider().get_market_data(
        _revision(),
        asset_codes=("000001.SH",),
        as_of_time=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert result.observation_precision is SourceObservationPrecision.TIMESTAMP
    assert result.observed_at == datetime.fromisoformat("2020-01-03T15:00:00+08:00")
    assert result.observed_on is None


@pytest.mark.parametrize("row_date", ("2026-08-02", "2026-08-03"))
def test_provider_blocks_current_day_or_future_date_only_bar(
    monkeypatch,
    row_date: str,
) -> None:
    monkeypatch.setattr(
        "apps.risk_center.infrastructure.scenario_market_data_provider.get_published_price_bar_series",
        lambda asset_code, **kwargs: {
            "publication_id": "publication-date-bound",
            "published_at": "2026-08-01T01:00:00+00:00",
            "must_not_use_for_decision": False,
            "rows": [
                {"timestamp": "2020-01-01", "close": 100},
                {"timestamp": "2020-01-02", "close": 90},
                {"timestamp": row_date, "close": 99},
            ],
        },
    )

    with pytest.raises(ScenarioMarketDataUnavailableError, match="not_before_as_of_day"):
        PublishedScenarioMarketDataProvider().get_market_data(
            _revision(),
            asset_codes=("000001.SH",),
            as_of_time=datetime(2026, 8, 2, tzinfo=UTC),
        )


def test_provider_rejects_date_only_publication_clock(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.risk_center.infrastructure.scenario_market_data_provider.get_published_price_bar_series",
        lambda asset_code, **kwargs: {
            "publication_id": "publication-date-clock",
            "published_at": "2026-08-01",
            "must_not_use_for_decision": False,
            "rows": [
                {"timestamp": "2020-01-01", "close": 100},
                {"timestamp": "2020-01-02", "close": 90},
            ],
        },
    )

    with pytest.raises(ScenarioMarketDataUnavailableError, match="date_only_publication_time"):
        PublishedScenarioMarketDataProvider().get_market_data(
            _revision(),
            asset_codes=("000001.SH",),
            as_of_time=datetime(2026, 8, 2, tzinfo=UTC),
        )


def test_provider_rejects_naive_timestamp_bar(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.risk_center.infrastructure.scenario_market_data_provider.get_published_price_bar_series",
        lambda asset_code, **kwargs: {
            "publication_id": "publication-naive",
            "published_at": "2026-08-01T01:00:00+00:00",
            "must_not_use_for_decision": False,
            "rows": [
                {"timestamp": "2020-01-01", "close": 100},
                {"timestamp": "2020-01-02", "close": 90},
                {"timestamp": "2020-01-03T15:00:00", "close": 99},
            ],
        },
    )

    with pytest.raises(ScenarioMarketDataUnavailableError, match="naive_price_observation"):
        PublishedScenarioMarketDataProvider().get_market_data(
            _revision(),
            asset_codes=("000001.SH",),
            as_of_time=datetime(2026, 8, 2, tzinfo=UTC),
        )


def test_date_precision_does_not_relax_global_source_prohibition(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.risk_center.infrastructure.scenario_market_data_provider.get_published_price_bar_series",
        lambda asset_code, **kwargs: {
            "publication_id": "publication-prohibited",
            "published_at": "2026-08-01T01:00:00+00:00",
            "must_not_use_for_decision": True,
            "blocked_reason": "source_research_only",
            "rows": [
                {"timestamp": "2020-01-01", "close": 100},
                {"timestamp": "2020-01-02", "close": 90},
            ],
        },
    )

    with pytest.raises(ScenarioMarketDataUnavailableError, match="source_research_only"):
        PublishedScenarioMarketDataProvider().get_market_data(
            _revision(),
            asset_codes=("000001.SH",),
            as_of_time=datetime(2026, 8, 2, tzinfo=UTC),
        )
