"""Application-facing helpers for sentiment interface views."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.ai_provider.application.repository_provider import get_ai_provider_repository
from apps.sentiment.application.current_sentiment import resolve_current_sentiment
from apps.sentiment.application.repository_provider import (
    get_sentiment_analysis_log_repository,
    get_sentiment_cache_repository,
    get_sentiment_index_repository,
)
from apps.sentiment.application.services import SentimentAnalyzer
from apps.sentiment.domain.entities import SentimentAnalysisResult
from core.exceptions import AIServiceError


def _require_successful_analysis(result: SentimentAnalysisResult) -> None:
    """Reject degraded AI results before they are cached or exposed as neutral data."""

    if result.error_message is not None:
        raise AIServiceError("舆情 AI 分析暂时不可用")


def analyze_sentiment_text(*, text: str, use_cache: bool = True) -> dict[str, Any]:
    """Analyze a single text item and return an API-ready payload."""

    cache_repository = get_sentiment_cache_repository()
    if use_cache:
        cached_result = cache_repository.get(text)
        if cached_result is not None:
            return cached_result.to_dict()

    analyzer = SentimentAnalyzer(provider_repository=get_ai_provider_repository())
    result = analyzer.analyze_text(text)

    get_sentiment_analysis_log_repository().log(
        source_type="manual",
        input_text=text,
        result=result,
    )
    _require_successful_analysis(result)

    if use_cache:
        cache_repository.set(text, result)

    return result.to_dict()


def analyze_sentiment_batch(*, texts: list[str]) -> dict[str, Any]:
    """Analyze multiple texts and return an API-ready payload."""

    analyzer = SentimentAnalyzer(provider_repository=get_ai_provider_repository())
    results = analyzer.analyze_batch(texts)
    for result in results:
        _require_successful_analysis(result)
    return {
        "results": [result.to_dict() for result in results],
        "total": len(results),
    }


def get_sentiment_index_payload(target_date: date | None = None) -> dict[str, Any] | None:
    """Return one sentiment index payload by date or the latest available."""

    repository = get_sentiment_index_repository()
    current = None
    if target_date is not None:
        index = repository.get_by_date(target_date)
    else:
        current = resolve_current_sentiment()
        index = current.diagnostic_index
    if index is None:
        return None
    payload = index.to_dict()
    if current is not None:
        payload.update(
            {
                "observed_at": (
                    current.observed_at.isoformat() if current.observed_at is not None else None
                ),
                "freshness_status": current.freshness_status,
                "staleness_days": current.staleness_days,
                "is_stale": current.freshness_status == "stale",
                "must_not_use_for_decision": current.must_not_use_for_decision,
                "blocked_reason": current.blocked_reason,
            }
        )
    return payload


def get_sentiment_index_range_payload(*, start_date: date, end_date: date) -> dict[str, Any]:
    """Return sentiment index payloads for a date range."""

    indices = get_sentiment_index_repository().get_range(start_date, end_date)
    return {
        "indices": [index.to_dict() for index in indices],
        "total": len(indices),
    }


def get_recent_sentiment_indices_payload(*, days: int = 30) -> dict[str, Any]:
    """Return recent sentiment index payloads."""

    indices = get_sentiment_index_repository().get_recent(days=days)
    return {
        "indices": [index.to_dict() for index in indices],
        "total": len(indices),
    }


def get_sentiment_health_payload() -> dict[str, Any]:
    """Return the health payload used by the sentiment health endpoint."""

    provider_repository = get_ai_provider_repository()
    ai_available = len(provider_repository.get_active_providers()) > 0
    current = resolve_current_sentiment()
    latest_index_date = current.observed_at
    return {
        "status": (
            "healthy" if ai_available and not current.must_not_use_for_decision else "degraded"
        ),
        "ai_provider_available": ai_available,
        "cache_count": get_sentiment_cache_repository().count(),
        "latest_index_date": latest_index_date.isoformat() if latest_index_date else None,
        "freshness_status": current.freshness_status,
        "must_not_use_for_decision": current.must_not_use_for_decision,
        "blocked_reason": current.blocked_reason,
    }


def clear_sentiment_cache_payload(*, text: str | None = None) -> dict[str, Any]:
    """Clear cached sentiment analysis results and return an API-ready payload."""

    count = get_sentiment_cache_repository().clear(text=text)
    return {
        "success": True,
        "message": f"已清除 {count} 条缓存记录",
    }


def get_sentiment_dashboard_context() -> dict[str, Any]:
    """Build the dashboard page context."""

    current = resolve_current_sentiment()
    latest_index = current.index
    recent_indices = get_sentiment_index_repository().get_recent(days=30)
    ai_available = len(get_ai_provider_repository().get_active_providers()) > 0
    return {
        "latest_index": latest_index.to_dict() if latest_index else None,
        "recent_indices": [index.to_dict() for index in recent_indices],
        "ai_available": ai_available,
        "sentiment_freshness": {
            "observed_at": current.observed_at,
            "freshness_status": current.freshness_status,
            "must_not_use_for_decision": current.must_not_use_for_decision,
            "blocked_reason": current.blocked_reason,
        },
    }


def get_sentiment_analyze_page_context() -> dict[str, Any]:
    """Build the analyze page context."""

    ai_available = len(get_ai_provider_repository().get_active_providers()) > 0
    return {"ai_available": ai_available}
