# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_sentiment."""

from .core_registry_support import *


def test_sentiment_core_only_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _Sentiment:
        def get_index(self, payload):
            calls.append(("get_index", payload))
            return {"date": "2026-07-10"}

        def index_recent(self, payload):
            calls.append(("index_recent", payload))
            return {"indices": [], "total": 0}

        def health(self):
            calls.append(("health", None))
            return {"status": "healthy"}

    class _Client:
        sentiment = _Sentiment()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_sentiment_index"]("2026-07-10") == {
        "date": "2026-07-10"
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_sentiment_recent"](7) == {
        "indices": [],
        "total": 0,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_sentiment_health"]() == {
        "status": "healthy"
    }
    assert calls == [
        ("get_index", {"date": "2026-07-10"}),
        ("index_recent", {"days": 7}),
        ("health", None),
    ]


def test_sentiment_clear_cache_capability_previews_count_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeSentimentModule:
        @staticmethod
        def health():
            calls.append(("health", {}))
            return {
                "status": "healthy",
                "ai_provider_available": True,
                "cache_count": 12,
                "latest_index_date": "2026-07-12",
            }

        @staticmethod
        def clear_cache():
            calls.append(("clear_cache", {}))
            return {
                "success": True,
                "message": "已清除 12 条缓存记录",
            }

    class _FakeClient:
        sentiment = _FakeSentimentModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["sentiment.clear.cache"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("clear_sentiment_cache",)

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="sentiment.clear.cache",
        arguments={
            "idempotency_key": "idem-sentiment-clear-cache",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"] == {
        "success": True,
        "preview_only": True,
        "cache_count": 12,
        "summary": {
            "current_cache_count": 12,
            "will_delete_all_cache_records": True,
        },
        "message": (
            "Preview generated. Confirm to permanently delete all persisted sentiment "
            "cache records."
        ),
    }
    assert calls == [("health", {})]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"] == {
        "success": True,
        "message": "已清除 12 条缓存记录",
    }
    assert calls == [("health", {}), ("clear_cache", {})]
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[0]["affected_objects"]["preview_summary"] == {
        "current_cache_count": 12,
        "will_delete_all_cache_records": True,
    }
    assert audit_events[1]["event_type"] == "confirmation_completed"
