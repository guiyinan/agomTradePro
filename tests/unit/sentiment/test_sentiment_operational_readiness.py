"""Regression tests for the production sentiment refresh chain."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.data_center.application.dtos import SyncResult
from apps.sentiment.application.services import SentimentIndexCalculator
from apps.sentiment.application.tasks import (
    calculate_daily_sentiment_index,
    refresh_current_sentiment_index,
)


class _WeightConfig:
    """Stable calculator weights for isolated tests."""

    @staticmethod
    def get_news_weight(default: float) -> float:
        del default
        return 0.6

    @staticmethod
    def get_policy_weight(default: float) -> float:
        del default
        return 0.4


def test_calculator_preserves_explicit_observation_datetime() -> None:
    """A targeted/backfill run must not relabel its observation as runtime-now."""

    observed_at = datetime(2026, 7, 25, tzinfo=UTC)

    result = SentimentIndexCalculator(_WeightConfig()).calculate_index(
        news_scores=[1.0],
        policy_scores=[-0.5],
        index_date=observed_at,
    )

    assert result.index_date == observed_at


def test_refresh_task_syncs_market_news_before_calculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduled task owns the upstream-news-to-index orchestration."""

    events: list[tuple[str, object]] = []

    def _sync(*, limit: int) -> SyncResult:
        events.append(("sync", limit))
        return SyncResult(
            domain="news",
            provider_name="configured-news-provider",
            stored_count=12,
            status="success",
        )

    def _calculate(target_date: date) -> dict[str, object]:
        events.append(("calculate", target_date))
        return {
            "outcome": "success",
            "success": True,
            "status": "success",
            "date": target_date.isoformat(),
            "requested": 12,
            "succeeded": 12,
            "failed": 0,
            "stored": 1,
        }

    monkeypatch.setattr(
        "apps.data_center.application.interface_services.sync_market_news_for_sentiment",
        _sync,
    )
    monkeypatch.setattr(
        "apps.sentiment.application.tasks._calculate_daily_sentiment_index",
        _calculate,
    )

    result = refresh_current_sentiment_index.run(target_date="2026-07-25")

    assert events == [("sync", 100), ("calculate", date(2026, 7, 25))]
    assert result["news_sync"] == {
        "provider": "configured-news-provider",
        "stored": 12,
        "status": "success",
        "error_message": "",
    }


def test_refresh_task_rejects_invalid_date_before_external_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permanent boundary errors must not contact an external provider or retry."""

    monkeypatch.setattr(
        "apps.data_center.application.interface_services.sync_market_news_for_sentiment",
        lambda **_kwargs: pytest.fail("external sync must not run"),
    )
    monkeypatch.setattr(
        refresh_current_sentiment_index,
        "retry",
        lambda **_kwargs: pytest.fail("invalid input must not retry"),
    )

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        refresh_current_sentiment_index.run(target_date="2026/07/25")


def _patch_calculation_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    news: list[SimpleNamespace],
) -> None:
    """Install deterministic successful calculation dependencies."""

    monkeypatch.setattr(
        "apps.policy.application.repository_provider.get_current_policy_repository",
        lambda: SimpleNamespace(get_events_in_range=lambda _start, _end: []),
    )
    monkeypatch.setattr(
        "apps.ai_provider.application.repository_provider.get_ai_provider_repository",
        lambda: object(),
    )
    monkeypatch.setattr(
        "apps.sentiment.application.repository_provider.get_market_news_for_sentiment",
        lambda _target_date, limit: news,
    )
    monkeypatch.setattr(
        "apps.sentiment.application.repository_provider.get_sentiment_index_repository",
        lambda: SimpleNamespace(save=lambda _index: None),
    )


def test_calculation_task_reports_all_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully scored source set publishes the normalized success outcome."""

    _patch_calculation_sources(
        monkeypatch,
        news=[
            SimpleNamespace(
                title="market news",
                summary="",
                sentiment_score=0.5,
                external_id="n1",
                url="",
            )
        ],
    )

    result = calculate_daily_sentiment_index.run(target_date="2026-07-25")

    assert result["outcome"] == "success"
    assert result["success"] is True
    assert result["requested"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["stored"] == 1


def test_calculation_task_reports_blocked_zero_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted diagnostic zero-input row remains explicitly decision-blocked."""

    _patch_calculation_sources(monkeypatch, news=[])

    result = calculate_daily_sentiment_index.run(target_date="2026-07-25")

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["requested"] == 0
    assert result["succeeded"] == 0
    assert result["stored"] == 1
    assert result["blocked_reason"] == "sentiment_data_insufficient"


def test_refresh_task_preserves_blocked_zero_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upstream no-op plus empty calculation cannot be promoted to success."""

    monkeypatch.setattr(
        "apps.data_center.application.interface_services.sync_market_news_for_sentiment",
        lambda **_kwargs: SyncResult("news", "provider", 0, "success"),
    )
    monkeypatch.setattr(
        "apps.sentiment.application.tasks._calculate_daily_sentiment_index",
        lambda _target_date: {
            "outcome": "blocked",
            "success": False,
            "status": "blocked",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 1,
            "blocked_reason": "sentiment_data_insufficient",
        },
    )

    result = refresh_current_sentiment_index.run(target_date="2026-07-25")

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["news_sync"]["stored"] == 0
