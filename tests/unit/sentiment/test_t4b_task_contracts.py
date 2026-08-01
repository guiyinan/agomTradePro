"""Business-outcome and failure-isolation contracts for sentiment tasks."""

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from apps.sentiment.application.tasks import (
    _build_news_text,
    analyze_policy_event_sentiment,
    batch_analyze_texts,
    calculate_daily_sentiment_index,
    check_sentiment_data_freshness,
)
from apps.sentiment.domain.entities import SentimentCategory


class _Analyzer:
    def __init__(self, _repository: object) -> None:
        pass

    def analyze_text(self, text: str) -> SimpleNamespace:
        if "bad" in text:
            raise RuntimeError("analysis failed")
        return SimpleNamespace(
            sentiment_score=1.25,
            category=SentimentCategory.POSITIVE,
            confidence=0.8,
            keywords=["growth"],
            error_message=None,
        )


def _patch_analyzer_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    policy_repository: object,
) -> None:
    monkeypatch.setattr(
        "apps.policy.application.repository_provider.get_current_policy_repository",
        lambda: policy_repository,
    )
    monkeypatch.setattr(
        "apps.ai_provider.application.repository_provider.get_ai_provider_repository",
        lambda: object(),
    )
    monkeypatch.setattr(
        "apps.sentiment.application.services.SentimentAnalyzer",
        _Analyzer,
    )


def test_daily_task_isolates_item_failures_and_persists_combined_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_events = [
        SimpleNamespace(
            title="support growth",
            description="policy",
            event_date=date(2026, 7, 25),
        ),
        SimpleNamespace(
            title="neutral policy",
            description=None,
            event_date=date(2026, 7, 25),
        ),
    ]
    policy_repository = SimpleNamespace(get_events_in_range=lambda _start, _end: policy_events)
    _patch_analyzer_dependencies(
        monkeypatch,
        policy_repository=policy_repository,
    )
    news = [
        SimpleNamespace(
            title="stored",
            summary="score",
            sentiment_score=0.5,
            external_id="stored",
            url="",
        ),
        SimpleNamespace(
            title="fresh",
            summary="growth",
            sentiment_score=None,
            external_id="fresh",
            url="",
        ),
        SimpleNamespace(
            title="",
            summary="",
            sentiment_score=None,
            external_id="blank",
            url="",
        ),
        SimpleNamespace(
            title="stored negative",
            summary="",
            sentiment_score=-0.5,
            external_id="bad",
            url="",
        ),
    ]
    monkeypatch.setattr(
        "apps.sentiment.application.repository_provider.get_market_news_for_sentiment",
        lambda _target_date, limit: news,
    )
    saved: list[object] = []
    monkeypatch.setattr(
        "apps.sentiment.application.repository_provider.get_sentiment_index_repository",
        lambda: SimpleNamespace(save=saved.append),
    )

    result = calculate_daily_sentiment_index.run(target_date="2026-07-25")

    assert result["status"] == "partial"
    assert result["outcome"] == "partial"
    assert result["success"] is False
    assert result["requested"] == 6
    assert result["succeeded"] == 5
    assert result["failed"] == 1
    assert result["stored"] == 1
    assert result["date"] == "2026-07-25"
    assert result["news_count"] == 3
    assert result["policy_events"] == 2
    assert len(saved) == 1
    assert saved[0].news_count == 3
    assert saved[0].policy_events_count == 2


def test_daily_task_uses_today_and_reraises_boundary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_repository = SimpleNamespace(get_events_in_range=lambda _start, _end: [])
    _patch_analyzer_dependencies(
        monkeypatch,
        policy_repository=policy_repository,
    )
    monkeypatch.setattr(
        "apps.sentiment.application.repository_provider.get_market_news_for_sentiment",
        lambda _target_date, limit: [],
    )
    monkeypatch.setattr(
        "apps.sentiment.application.repository_provider.get_sentiment_index_repository",
        lambda: SimpleNamespace(save=lambda _index: None),
    )

    result = calculate_daily_sentiment_index.run()
    assert result["date"] == str(date.today())

    with pytest.raises(ValueError, match="target_date must use YYYY-MM-DD format"):
        calculate_daily_sentiment_index.run(target_date="2026/07/25")


def test_news_text_handles_missing_and_nullable_fields() -> None:
    assert _build_news_text(SimpleNamespace(title=None, summary="summary")) == "summary"


def test_policy_event_task_handles_missing_success_and_analyzer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SimpleNamespace(get_event_by_id=lambda event_id: None)
    _patch_analyzer_dependencies(monkeypatch, policy_repository=repository)
    assert analyze_policy_event_sentiment.run(event_id=404) == {
        "status": "error",
        "message": "政策事件 404 不存在",
    }

    event = SimpleNamespace(title="support growth", description=None)
    repository.get_event_by_id = lambda event_id: event
    result = analyze_policy_event_sentiment.run(event_id=7)
    assert result == {
        "event_id": 7,
        "sentiment_score": 1.25,
        "category": "POSITIVE",
        "confidence": 0.8,
        "keywords": ["growth"],
        "status": "success",
    }

    event.title = "bad policy"
    with pytest.raises(RuntimeError, match="analysis failed"):
        analyze_policy_event_sentiment.run(event_id=7)


def test_batch_task_truncates_text_and_keeps_per_item_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_analyzer_dependencies(
        monkeypatch,
        policy_repository=SimpleNamespace(),
    )
    long_text = "growth " * 30

    result = batch_analyze_texts.run(texts=[long_text, "bad input"])

    assert result[0]["text"].endswith("...")
    assert len(result[0]["text"]) == 103
    assert result[0]["score"] == 1.25
    assert result[1] == {"text": "bad input", "error": "analysis failed"}


@pytest.mark.parametrize(
    ("latest", "expected_status", "message_fragment"),
    [
        (None, "warning", "没有情绪指数数据"),
        (
            SimpleNamespace(
                index_date=datetime.combine(date.today(), time.min, tzinfo=UTC),
                composite_index=0.75,
            ),
            "ok",
            "今日数据已更新",
        ),
        (
            SimpleNamespace(
                index_date=datetime.combine(
                    date.today() - timedelta(days=7),
                    time.min,
                    tzinfo=UTC,
                ),
                composite_index=-0.25,
            ),
            "warning",
            "sentiment_index_stale",
        ),
    ],
)
def test_freshness_task_distinguishes_missing_current_and_stale(
    monkeypatch: pytest.MonkeyPatch,
    latest: object,
    expected_status: str,
    message_fragment: str,
) -> None:
    monkeypatch.setattr(
        "apps.sentiment.application.current_sentiment.get_sentiment_index_repository",
        lambda: SimpleNamespace(get_latest=lambda: latest),
    )
    if latest is not None and not hasattr(latest, "data_sufficient"):
        latest.data_sufficient = True

    result = check_sentiment_data_freshness.run()

    assert result["status"] == expected_status
    assert message_fragment in result["message"]


def test_freshness_task_reports_repository_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> None:
        raise RuntimeError("repository unavailable")

    monkeypatch.setattr(
        "apps.sentiment.application.current_sentiment.get_sentiment_index_repository",
        lambda: SimpleNamespace(get_latest=fail),
    )

    with pytest.raises(RuntimeError, match="repository unavailable"):
        check_sentiment_data_freshness.run()
