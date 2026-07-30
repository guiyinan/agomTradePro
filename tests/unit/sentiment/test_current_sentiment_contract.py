"""Canonical current-sentiment freshness contract tests."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from apps.sentiment.application import current_sentiment
from apps.sentiment.domain.entities import SentimentIndex


def _index(index_date: date, *, data_sufficient: bool = True) -> SentimentIndex:
    return SentimentIndex(
        index_date=datetime.combine(index_date, datetime.min.time(), tzinfo=UTC),
        composite_index=-0.8,
        confidence_level=0.8,
        data_sufficient=data_sufficient,
        news_count=20,
    )


def test_current_sentiment_blocks_stale_latest_row(monkeypatch):
    repository = SimpleNamespace(get_latest=lambda: _index(date(2026, 6, 1)))
    monkeypatch.setattr(
        current_sentiment,
        "get_sentiment_index_repository",
        lambda: repository,
    )

    result = current_sentiment.resolve_current_sentiment(
        as_of_date=date(2026, 7, 30),
    )

    assert result.index is None
    assert result.observed_at == date(2026, 6, 1)
    assert result.freshness_status == "stale"
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason == "sentiment_index_stale"


def test_current_sentiment_blocks_insufficient_same_day_data(monkeypatch):
    repository = SimpleNamespace(
        get_latest=lambda: _index(date(2026, 7, 30), data_sufficient=False)
    )
    monkeypatch.setattr(
        current_sentiment,
        "get_sentiment_index_repository",
        lambda: repository,
    )

    result = current_sentiment.resolve_current_sentiment(
        as_of_date=date(2026, 7, 30),
    )

    assert result.index is None
    assert result.freshness_status == "insufficient"
    assert result.blocked_reason == "sentiment_data_insufficient"
