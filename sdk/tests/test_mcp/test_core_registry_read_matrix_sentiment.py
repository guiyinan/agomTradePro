# ruff: noqa: F403, F405
"""Core-only read matrix for sentiment."""

from .core_registry_support import *


@pytest.mark.parametrize(
    (
        "capability_key",
        "executor_ref",
        "legacy_tool_names",
        "arguments",
        "payload",
        "expected",
    ),
    [
        (
            "sentiment.read.index",
            "get_sentiment_index",
            ("get_sentiment_index",),
            {"date": "2026-07-10"},
            {
                "date": "2026-07-10",
                "index": {"overall": 0.62},
                "level": "positive",
                "confidence": 0.84,
                "data_sufficient": True,
                "sector_sentiment": {"technology": 0.71},
                "sources": {"news": 18},
                "source": "core-only-fallback",
            },
            "technology",
        ),
        (
            "sentiment.read.recent",
            "get_sentiment_recent",
            ("get_sentiment_recent",),
            {"days": 7},
            {
                "indices": [
                    {
                        "date": "2026-07-10",
                        "index": {"overall": 0.62},
                        "level": "positive",
                    }
                ],
                "total": 1,
                "source": "core-only-fallback",
            },
            "2026-07-10",
        ),
        (
            "sentiment.read.health",
            "get_sentiment_health",
            ("get_sentiment_health",),
            {},
            {
                "status": "healthy",
                "ai_provider_available": True,
                "cache_count": 12,
                "latest_index_date": "2026-07-10",
                "source": "core-only-fallback",
            },
            "cache_count",
        ),
    ],
)
def test_agom_capability_call_reads_data_family_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    executor_ref,
    legacy_tool_names,
    arguments,
    payload,
    expected,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        executor_ref,
        lambda **kwargs: payload,
    )
    assert all(legacy_tool_names)

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": capability_key,
                "arguments": arguments,
            },
        )
    )

    rendered = str(result)
    assert capability_key in rendered
    assert expected in rendered
    assert "core-only-fallback" in rendered
