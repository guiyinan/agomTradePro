"""Application-facing helpers for sentiment interface views."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.ai_provider.application.client_provider import get_ai_provider_repository
from apps.sentiment.application.services import SentimentAnalyzer
from apps.sentiment.infrastructure.providers import (
    SentimentAnalysisLogRepository,
    SentimentCacheRepository,
    SentimentIndexRepository,
)


def analyze_sentiment_text(*, text: str, use_cache: bool = True) -> dict[str, Any]:
    """Analyze a single text item and return an API-ready payload."""

    cache_repository = SentimentCacheRepository()
    if use_cache:
        cached_result = cache_repository.get(text)
        if cached_result is not None:
            return cached_result.to_dict()

    analyzer = SentimentAnalyzer(provider_repository=get_ai_provider_repository())
    result = analyzer.analyze_text(text)

    if use_cache:
        cache_repository.set(text, result)

    SentimentAnalysisLogRepository().log(
        source_type="manual",
        input_text=text,
        result=result,
    )
    return result.to_dict()


def analyze_sentiment_batch(*, texts: list[str]) -> dict[str, Any]:
    """Analyze multiple texts and return an API-ready payload."""

    analyzer = SentimentAnalyzer(provider_repository=AIProviderRepository())
    results = analyzer.analyze_batch(texts)
    return {
        "results": [result.to_dict() for result in results],
        "total": len(results),
    }


def get_sentiment_index_payload(target_date: date | None = None) -> dict[str, Any] | None:
    """Return one sentiment index payload by date or the latest available."""

    repository = SentimentIndexRepository()
    index = (
        repository.get_by_date(target_date) if target_date is not None else repository.get_latest()
    )
    if index is None:
        return None
    return index.to_dict()


def get_sentiment_index_range_payload(*, start_date: date, end_date: date) -> dict[str, Any]:
    """Return sentiment index payloads for a date range."""

    indices = SentimentIndexRepository().get_range(start_date, end_date)
    return {
        "indices": [index.to_dict() for index in indices],
        "total": len(indices),
    }


def get_recent_sentiment_indices_payload(*, days: int = 30) -> dict[str, Any]:
    """Return recent sentiment index payloads."""

    indices = SentimentIndexRepository().get_recent(days=days)
    return {
        "indices": [index.to_dict() for index in indices],
        "total": len(indices),
    }


def get_sentiment_health_payload() -> dict[str, Any]:
    """Return the health payload used by the sentiment health endpoint."""

    provider_repository = AIProviderRepository()
    ai_available = len(provider_repository.get_active_providers()) > 0
    latest_index_date = SentimentIndexRepository().get_latest_index_date()
    return {
        "status": "healthy" if ai_available else "degraded",
        "ai_provider_available": ai_available,
        "cache_count": SentimentCacheRepository().count(),
        "latest_index_date": latest_index_date.isoformat() if latest_index_date else None,
    }


def clear_sentiment_cache_payload(*, text: str | None = None) -> dict[str, Any]:
    """Clear cached sentiment analysis results and return an API-ready payload."""

    count = SentimentCacheRepository().clear(text=text)
    return {
        "success": True,
        "message": f"已清除 {count} 条缓存记录",
    }


def get_sentiment_dashboard_context() -> dict[str, Any]:
    """Build the dashboard page context."""

    latest_index = SentimentIndexRepository().get_latest()
    recent_indices = SentimentIndexRepository().get_recent(days=30)
    ai_available = len(AIProviderRepository().get_active_providers()) > 0
    return {
        "latest_index": latest_index.to_dict() if latest_index else None,
        "recent_indices": [index.to_dict() for index in recent_indices],
        "ai_available": ai_available,
    }


def get_sentiment_analyze_page_context() -> dict[str, Any]:
    """Build the analyze page context."""

    ai_available = len(AIProviderRepository().get_active_providers()) > 0
    return {"ai_available": ai_available}
