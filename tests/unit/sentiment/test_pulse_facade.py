"""Tests for the decision-safe sentiment series exposed to Pulse."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from apps.sentiment.application import pulse_facade
from apps.sentiment.domain.entities import SentimentIndex


def _index(day: date, score: float, *, data_sufficient: bool = True) -> SentimentIndex:
    return SentimentIndex(
        index_date=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        composite_index=score,
        confidence_level=0.8,
        data_sufficient=data_sufficient,
        news_count=20,
    )


def test_sentiment_pulse_series_returns_history_when_latest_is_fresh(monkeypatch) -> None:
    rows = [
        _index(date(2026, 7, 29), -0.2),
        _index(date(2026, 7, 30), 0.4),
    ]
    repository = SimpleNamespace(get_range=lambda start_date, end_date: rows)
    monkeypatch.setattr(
        pulse_facade,
        "get_sentiment_index_repository",
        lambda: repository,
    )

    result = pulse_facade.get_sentiment_pulse_series(
        as_of_date=date(2026, 7, 30),
        lookback_days=365,
    )

    assert [point.value for point in result.points] == [-0.2, 0.4]
    assert result.observed_at == date(2026, 7, 30)
    assert result.must_not_use_for_decision is False
    assert result.blocked_reason == ""


def test_sentiment_pulse_series_fails_closed_when_latest_is_stale(monkeypatch) -> None:
    rows = [_index(date(2026, 7, 24), 0.4)]
    repository = SimpleNamespace(get_range=lambda start_date, end_date: rows)
    monkeypatch.setattr(
        pulse_facade,
        "get_sentiment_index_repository",
        lambda: repository,
    )

    result = pulse_facade.get_sentiment_pulse_series(
        as_of_date=date(2026, 7, 30),
        lookback_days=365,
    )

    assert result.points == ()
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "sentiment_index_stale"


def test_sentiment_pulse_series_fails_closed_when_latest_is_insufficient(monkeypatch) -> None:
    rows = [_index(date(2026, 7, 30), 0.0, data_sufficient=False)]
    repository = SimpleNamespace(get_range=lambda start_date, end_date: rows)
    monkeypatch.setattr(
        pulse_facade,
        "get_sentiment_index_repository",
        lambda: repository,
    )

    result = pulse_facade.get_sentiment_pulse_series(
        as_of_date=date(2026, 7, 30),
        lookback_days=365,
    )

    assert result.points == ()
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "sentiment_data_insufficient"
