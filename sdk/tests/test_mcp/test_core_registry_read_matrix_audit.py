# ruff: noqa: F403, F405
"""Core-only read matrix for audit."""

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
            "audit.read.summary",
            "get_audit_summary",
            ("get_audit_summary",),
            {"backtest_id": 17},
            {
                "success": True,
                "reports": [
                    {
                        "id": 8,
                        "backtest_id": 17,
                        "total_pnl": 0.12,
                    }
                ],
                "total_count": 1,
                "query": {"mode": "backtest", "backtest_id": 17},
                "error": None,
                "source": "core-only-fallback",
            },
            "total_pnl",
        ),
        (
            "audit.read.execution_links",
            "list_audit_execution_links",
            ("list_audit_execution_links",),
            {
                "account_id": "7",
                "transaction_source": "simulated_trade",
                "limit": 10,
            },
            {
                "success": True,
                "links": [
                    {
                        "recommendation_id": "rec-1",
                        "transaction_id": 9001,
                        "account_id": "7",
                        "transaction_source": "simulated_trade",
                    }
                ],
                "source": "core-only-fallback",
            },
            "rec-1",
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
