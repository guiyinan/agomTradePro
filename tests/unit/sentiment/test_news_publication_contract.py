"""Publication-bound market-news inputs for sentiment calculations."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.sentiment.application import repository_provider


def _news_row() -> dict[str, object]:
    return {
        "asset_code": "",
        "title": "市场消息",
        "summary": "来源摘要",
        "published_at": "2026-08-03T01:00:00+00:00",
        "fetched_at": "2026-08-03T01:01:00+00:00",
        "url": "https://example.test/news/1",
        "source": "provider-a",
        "external_id": "news-1",
        "sentiment_score": 0.25,
        "extra": {"raw_hash": "sha256:news"},
    }


def test_current_sentiment_news_uses_publication_members(monkeypatch) -> None:
    """The default sentiment input must never fall back to unbound latest rows."""

    captured: dict[str, object] = {}

    def _published(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "rows": [_news_row()],
            "publication_id": "publication-1",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
        }

    monkeypatch.setattr(repository_provider, "get_published_market_news", _published)
    monkeypatch.setattr(
        repository_provider,
        "get_news_repository_port",
        lambda: pytest.fail("published sentiment must not read the legacy repository"),
    )

    rows = repository_provider.get_market_news_for_sentiment(
        date(2026, 8, 3),
        limit=7,
        publication_key="current",
    )

    assert captured == {
        "target_date": date(2026, 8, 3),
        "limit": 7,
        "publication_key": "current",
    }
    assert len(rows) == 1
    assert rows[0].published_at == datetime(2026, 8, 3, 1, 0, tzinfo=UTC)
    assert rows[0].fetched_at == datetime(2026, 8, 3, 1, 1, tzinfo=UTC)
    assert rows[0].extra == {"raw_hash": "sha256:news"}


def test_current_sentiment_news_blocks_without_publication(monkeypatch) -> None:
    """A blocked publication produces no news evidence for the calculator."""

    monkeypatch.setattr(
        repository_provider,
        "get_published_market_news",
        lambda **_kwargs: {
            "rows": [_news_row()],
            "publication_id": None,
            "freshness_status": "missing",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_missing",
        },
    )
    monkeypatch.setattr(
        repository_provider,
        "get_news_repository_port",
        lambda: pytest.fail("blocked published input must not read the legacy repository"),
    )

    assert repository_provider.get_market_news_for_sentiment(date(2026, 8, 3)) == []


def test_historical_sentiment_news_requires_explicit_legacy_mode(monkeypatch) -> None:
    """Historical calculations retain the date-bounded compatibility port."""

    expected = [SimpleNamespace(title="历史消息")]
    repository = SimpleNamespace(
        list_market_news_for_date=lambda target_date, limit: (
            expected if target_date == date(2025, 8, 3) and limit == 3 else []
        )
    )
    monkeypatch.setattr(repository_provider, "get_news_repository_port", lambda: repository)
    monkeypatch.setattr(
        repository_provider,
        "get_published_market_news",
        lambda **_kwargs: pytest.fail("historical mode must not use current publication"),
    )

    assert (
        repository_provider.get_market_news_for_sentiment(
            date(2025, 8, 3),
            limit=3,
            mode="historical",
        )
        == expected
    )


def test_sentiment_news_rejects_unknown_mode() -> None:
    """Callers must choose a declared current or historical semantic."""

    with pytest.raises(ValueError, match="published.*historical"):
        repository_provider.get_market_news_for_sentiment(
            date(2026, 8, 3),
            mode="latest",
        )
