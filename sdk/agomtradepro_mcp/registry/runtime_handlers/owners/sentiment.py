"""sentiment runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_get_sentiment_index(date: str | None = None) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    params = {"date": date} if date else None
    return client.sentiment.get_index(params)


def _fallback_get_sentiment_recent(days: int = 30) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.sentiment.index_recent({"days": days})


def _fallback_get_sentiment_health() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.sentiment.health()


def _internal_handler_sentiment_clear_cache(
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    if preview_only:
        health = client.sentiment.health()
        if not isinstance(health, dict):
            raise ValueError("sentiment health response must be an object")
        cache_count = health.get("cache_count")
        if isinstance(cache_count, bool) or not isinstance(cache_count, int) or cache_count < 0:
            raise ValueError("sentiment health cache_count must be a non-negative integer")
        return {
            "success": True,
            "preview_only": True,
            "cache_count": cache_count,
            "summary": {
                "current_cache_count": cache_count,
                "will_delete_all_cache_records": True,
            },
            "message": (
                "Preview generated. Confirm to permanently delete all persisted sentiment "
                "cache records."
            ),
        }

    return client.sentiment.clear_cache()


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_sentiment_index": _fallback_get_sentiment_index,
    "get_sentiment_recent": _fallback_get_sentiment_recent,
    "get_sentiment_health": _fallback_get_sentiment_health,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "sentiment_clear_cache": _internal_handler_sentiment_clear_cache,
}
