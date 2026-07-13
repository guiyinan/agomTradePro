# ruff: noqa: F403, F405
"""Core-only read matrix for dashboard."""

from .core_registry_support import *


def test_dashboard_equity_curve_uses_canonical_sdk_through_core_registry(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls = []
    dashboard = SimpleNamespace(
        equity_curve_v1=lambda: calls.append("equity_curve_v1")
        or {
            "range": "ALL",
            "has_history": True,
            "series": [
                {
                    "date": "2026-07-12",
                    "portfolio_value": 1020000.0,
                    "return_pct": 2.0,
                }
            ],
        }
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(dashboard=dashboard),
    )

    manifest = CapabilityRegistryLoader().build_registry()["dashboard.read.equity_curve"]
    assert manifest.executor_ref in server_module.INTERNAL_LEGACY_TOOL_FALLBACKS
    assert manifest.legacy_tool_names == ("get_dashboard_equity_curve_v1",)

    response = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "dashboard.read.equity_curve",
                "arguments": {},
            },
        )
    )

    assert "completed" in str(response)
    assert "1020000.0" in str(response)
    assert calls == ["equity_curve_v1"]


def test_dashboard_asset_allocation_uses_canonical_sdk_through_core_registry(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls = []
    dashboard = SimpleNamespace(
        allocation=lambda: calls.append("allocation")
        or {
            "success": True,
            "data": {"equity": 700000.0, "bond": 300000.0},
        }
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(dashboard=dashboard),
    )

    manifest = CapabilityRegistryLoader().build_registry()[
        "dashboard.read.asset_allocation"
    ]
    assert manifest.executor_ref in server_module.INTERNAL_LEGACY_TOOL_FALLBACKS
    assert manifest.legacy_tool_names == ("get_dashboard_allocation",)

    response = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "dashboard.read.asset_allocation",
                "arguments": {},
            },
        )
    )

    assert "completed" in str(response)
    assert "1000000.0" in str(response)
    assert calls == ["allocation"]


def test_dashboard_position_catalog_uses_canonical_sdk_through_core_registry(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls = []
    dashboard = SimpleNamespace(
        positions=lambda: calls.append("positions")
        or {
            "success": True,
            "data": {
                "positions": [
                    {
                        "account_id": 17,
                        "asset_code": "510300.SH",
                        "market_value": 600000.0,
                    }
                ],
                "total_count": 1,
            },
        }
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(dashboard=dashboard),
    )

    manifest = CapabilityRegistryLoader().build_registry()[
        "dashboard.read.position_catalog"
    ]
    assert manifest.executor_ref in server_module.INTERNAL_LEGACY_TOOL_FALLBACKS
    assert manifest.legacy_tool_names == ("get_dashboard_positions",)

    response = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "dashboard.read.position_catalog",
                "arguments": {},
            },
        )
    )

    assert "completed" in str(response)
    assert "510300.SH" in str(response)
    assert calls == ["positions"]


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
            "dashboard.read.auto_advisor_console",
            "dashboard_read_auto_advisor_console",
            ("get_auto_advisor_console",),
            {"account_id": 135},
            {
                "status": "ok",
                "account": {"account_id": "135"},
                "today_tradeability": {"conclusion": "REVIEW"},
                "macro_regime": {"current": "Recovery"},
                "portfolio_risk": {"warning_count": 1},
                "today_advice": {"order_summary": {"total": 1}},
                "must_handle_alerts": [],
                "data_freshness": {"status": "ok"},
                "execution": {"requires_human_confirmation": True},
                "next_actions": [{"key": "review"}],
                "source": "core-only-fallback",
            },
            "Recovery",
        ),
        (
            "dashboard.query.auto_advisor",
            "dashboard_query_auto_advisor",
            ("ask_auto_advisor",),
            {"account_id": 135, "question": "最大风险是什么"},
            {
                "status": "ok",
                "account": {"account_id": "135"},
                "query": {
                    "question": "最大风险是什么",
                    "intent": "largest_risk",
                },
                "answer": "最大风险来自单一持仓集中度。",
                "highlights": [{"code": "top_position_weight"}],
                "evidence": {"risk_summary": {"top_position_weight": 0.32}},
                "source": "core-only-fallback",
            },
            "largest_risk",
        ),
        (
            "dashboard.read.auto_advisor_weekly_report",
            "dashboard_read_auto_advisor_weekly_report",
            ("get_auto_advisor_weekly_report",),
            {"account_id": 135, "as_of": "2026-07-11"},
            {
                "status": "ok",
                "account": {"account_id": "135"},
                "week": {"as_of": "2026-07-11"},
                "portfolio_change": {"status": "HISTORICAL"},
                "largest_risk_exposure": {"summary": "集中度风险"},
                "system_vs_actual": {"decision_count": 1},
                "unexecuted_recommendations": {"items": []},
                "invalidated_recommendations": {"items": []},
                "investment_diary": {"status": "DERIVED_FROM_ADVISOR_SHEET"},
                "next_week_watchlist": [],
                "evidence": {"today_conclusion": "REVIEW"},
                "source": "core-only-fallback",
            },
            "DERIVED_FROM_ADVISOR_SHEET",
        ),
        (
            "dashboard.read.auto_advisor_weekly_report_history",
            "dashboard_read_auto_advisor_weekly_report_history",
            ("list_auto_advisor_weekly_report_history",),
            {"account_id": 135, "limit": 5},
            {
                "status": "ok",
                "reports": [{"id": 9, "account_id": 135}],
                "total_count": 1,
                "query": {"account_id": "135", "limit": 5},
                "source": "core-only-fallback",
            },
            "reports",
        ),
        (
            "dashboard.read.auto_advisor_notifications",
            "dashboard_read_auto_advisor_notifications",
            ("list_auto_advisor_notifications",),
            {"account_id": 135, "limit": 5},
            {
                "status": "ok",
                "notifications": [{"id": 10, "account_id": 135}],
                "total_count": 1,
                "query": {"account_id": "135", "limit": 5},
                "source": "core-only-fallback",
            },
            "notifications",
        ),
        (
            "dashboard.read.equity_curve",
            "dashboard_read_equity_curve",
            ("get_dashboard_equity_curve_v1",),
            {},
            {
                "range": "ALL",
                "has_history": True,
                "series": [
                    {
                        "date": "2026-07-12",
                        "portfolio_value": 1020000.0,
                        "return_pct": 2.0,
                    }
                ],
                "source": "core-only-fallback",
            },
            "1020000.0",
        ),
        (
            "dashboard.read.asset_allocation",
            "dashboard_read_asset_allocation",
            ("get_dashboard_allocation",),
            {},
            {
                "allocation": {"equity": 700000.0, "bond": 300000.0},
                "total_market_value": 1000000.0,
                "source": "core-only-fallback",
            },
            "1000000.0",
        ),
        (
            "dashboard.read.position_catalog",
            "dashboard_read_position_catalog",
            ("get_dashboard_positions",),
            {},
            {
                "positions": [
                    {
                        "account_id": 17,
                        "asset_code": "510300.SH",
                        "market_value": 600000.0,
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "510300.SH",
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
