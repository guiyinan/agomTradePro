"""sentiment runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


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


def _sentiment_text_fingerprint(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _internal_handler_sentiment_execute_analysis(
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized = dict(payload or {})
    text = str(normalized.get("text") or "")
    if not text.strip():
        raise ValueError("Sentiment analysis text must not be empty")
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "text_length": len(text),
            "text_fingerprint": _sentiment_text_fingerprint(text),
            "use_cache": bool(normalized.get("use_cache", True)),
            "will_invoke_ai_provider": True,
            "will_write_analysis_log": True,
        }
    return _call_registered_tool("analyze_sentiment", {"payload": normalized})


def _internal_handler_sentiment_execute_batch_analysis(
    payload: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized = dict(payload or {})
    texts = [str(item) for item in normalized.get("texts") or []]
    if not texts or any(not text.strip() for text in texts):
        raise ValueError("Sentiment batch texts must contain non-empty strings")
    if len(texts) > 50:
        raise ValueError("Sentiment batch cannot exceed 50 texts")
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "text_count": len(texts),
            "text_fingerprints": [_sentiment_text_fingerprint(text) for text in texts],
            "will_invoke_ai_provider": True,
        }
    return _call_registered_tool("batch_analyze_sentiment", {"payload": normalized})


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_sentiment_index": _fallback_get_sentiment_index,
    "get_sentiment_recent": _fallback_get_sentiment_recent,
    "get_sentiment_health": _fallback_get_sentiment_health,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "sentiment_clear_cache": _internal_handler_sentiment_clear_cache,
    "sentiment_execute_analysis": _internal_handler_sentiment_execute_analysis,
    "sentiment_execute_batch_analysis": _internal_handler_sentiment_execute_batch_analysis,
}
