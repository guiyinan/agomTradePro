# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_dashboard."""

from .core_registry_support import *


def test_dashboard_auto_advisor_read_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _DecisionRhythm:
        def advisor_sheet(self, *, account_id):
            calls.append(("advisor_sheet", account_id))
            return {
                "success": True,
                "data": {
                    "account": {"account_id": str(account_id)},
                    "today_conclusion": "REVIEW",
                    "holdings": [{"asset_code": "000001.SZ"}],
                },
            }

    class _Dashboard:
        def auto_advisor_console(self, *, account_id):
            calls.append(("auto_advisor_console", account_id))
            return {
                "success": True,
                "data": {
                    "status": "ok",
                    "account": {"account_id": str(account_id)},
                    "today_tradeability": {"conclusion": "REVIEW"},
                },
            }

        def auto_advisor_query(self, *, account_id, question):
            calls.append(("auto_advisor_query", (account_id, question)))
            return {
                "success": True,
                "data": {
                    "status": "ok",
                    "query": {"question": question, "intent": "largest_risk"},
                    "answer": "最大风险来自单一持仓集中度。",
                },
            }

        def auto_advisor_weekly_report(self, *, account_id, as_of):
            calls.append(("auto_advisor_weekly_report", (account_id, as_of)))
            return {
                "success": True,
                "data": {
                    "status": "ok",
                    "week": {"as_of": as_of},
                    "investment_diary": {
                        "status": "DERIVED_FROM_ADVISOR_SHEET",
                    },
                },
            }

        def auto_advisor_weekly_report_history(self, *, account_id, limit):
            calls.append(("auto_advisor_weekly_report_history", (account_id, limit)))
            return {
                "success": True,
                "data": {
                    "status": "ok",
                    "count": 1,
                    "reports": [{"id": 9, "account_id": 135}],
                },
            }

        def auto_advisor_notifications(self, *, account_id, limit):
            calls.append(("auto_advisor_notifications", (account_id, limit)))
            return {
                "success": True,
                "data": {
                    "status": "ok",
                    "count": 1,
                    "notifications": [{"id": 10, "account_id": 135}],
                },
            }

    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(
            decision_rhythm=_DecisionRhythm(),
            dashboard=_Dashboard(),
        ),
    )

    sheet = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["decision_read_advisor_sheet"](
        account_id=135
    )
    console = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["dashboard_read_auto_advisor_console"](
        account_id=135
    )
    query = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["dashboard_query_auto_advisor"](
        account_id=135,
        question="最大风险是什么",
    )
    report = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS[
        "dashboard_read_auto_advisor_weekly_report"
    ](
        account_id=135,
        as_of="2026-07-11",
    )
    history = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS[
        "dashboard_read_auto_advisor_weekly_report_history"
    ](
        account_id=135,
        limit=5,
    )
    notifications = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS[
        "dashboard_read_auto_advisor_notifications"
    ](
        account_id=135,
        limit=5,
    )

    assert sheet["holdings"][0]["asset_code"] == "000001.SZ"
    assert console["today_tradeability"]["conclusion"] == "REVIEW"
    assert query["query"]["intent"] == "largest_risk"
    assert report["investment_diary"]["status"] == "DERIVED_FROM_ADVISOR_SHEET"
    assert history["reports"][0]["id"] == 9
    assert history["query"] == {"account_id": "135", "limit": 5}
    assert notifications["notifications"][0]["id"] == 10
    assert notifications["query"] == {"account_id": "135", "limit": 5}
    assert calls == [
        ("advisor_sheet", 135),
        ("auto_advisor_console", 135),
        ("auto_advisor_query", (135, "最大风险是什么")),
        ("auto_advisor_weekly_report", (135, "2026-07-11")),
        ("auto_advisor_weekly_report_history", (135, 5)),
        ("auto_advisor_notifications", (135, 5)),
    ]


def test_agom_capability_call_reads_dashboard_alpha_history_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "dashboard_read_alpha_history",
        lambda **kwargs: {
            "runs": [
                {
                    "id": 7,
                    "portfolio_id": kwargs.get("portfolio_id"),
                    "trade_date": "2026-07-11",
                    "source": "core-only-fallback",
                }
            ],
            "total_count": 1,
            "query": kwargs,
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "dashboard.read.alpha_history",
                "arguments": {"portfolio_id": 135},
            },
        )
    )

    rendered = str(result)
    assert "dashboard.read.alpha_history" in rendered
    assert "get_dashboard_alpha_history" in (
        CapabilityRegistryLoader()
        .build_registry()["dashboard.read.alpha_history"]
        .legacy_tool_names
    )
    assert "core-only-fallback" in rendered
    assert "135" in rendered


def test_agom_capability_call_reads_dashboard_alpha_history_detail_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "dashboard_read_alpha_history_detail",
        lambda **kwargs: {
            "run": {
                "id": kwargs["run_id"],
                "snapshots": [
                    {
                        "code": "000001.SZ",
                        "stage": "actionable",
                        "source": "core-only-fallback",
                    }
                ],
            }
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "dashboard.read.alpha_history_detail",
                "arguments": {"run_id": 7},
            },
        )
    )

    rendered = str(result)
    assert "dashboard.read.alpha_history_detail" in rendered
    assert "get_dashboard_alpha_history_detail" in (
        CapabilityRegistryLoader()
        .build_registry()["dashboard.read.alpha_history_detail"]
        .legacy_tool_names
    )
    assert "core-only-fallback" in rendered
    assert "000001.SZ" in rendered


@pytest.mark.parametrize(
    ("history_reports", "expected_operation", "expected_existing_report_id"),
    (
        ([], "create", None),
        (
            [
                {
                    "id": 21,
                    "account_id": "7",
                    "report_date": "2026-07-12",
                }
            ],
            "overwrite",
            21,
        ),
    ),
)
def test_dashboard_create_auto_advisor_weekly_report_previews_before_commit(
    monkeypatch: pytest.MonkeyPatch,
    history_reports,
    expected_operation,
    expected_existing_report_id,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDashboardModule:
        @staticmethod
        def auto_advisor_weekly_report(**kwargs):
            calls.append(("auto_advisor_weekly_report", dict(kwargs)))
            return {
                "success": True,
                "data": {
                    "status": "ready",
                    "account": {
                        "account_id": "7",
                        "account_name": "Primary",
                    },
                    "week": {
                        "start": "2026-07-06",
                        "end": "2026-07-12",
                    },
                    "investment_diary": {
                        "summary": "Weekly decision review",
                    },
                },
            }

        @staticmethod
        def auto_advisor_weekly_report_history(**kwargs):
            calls.append(("auto_advisor_weekly_report_history", dict(kwargs)))
            return {
                "success": True,
                "data": {
                    "reports": history_reports,
                    "total_count": len(history_reports),
                },
            }

        @staticmethod
        def create_auto_advisor_weekly_report(**kwargs):
            calls.append(("create_auto_advisor_weekly_report", dict(kwargs)))
            return {
                "success": True,
                "data": {
                    "status": "persisted",
                    "account": {
                        "account_id": "7",
                        "account_name": "Primary",
                    },
                    "week": {
                        "start": "2026-07-06",
                        "end": "2026-07-12",
                    },
                    "investment_diary": {
                        "summary": "Weekly decision review",
                    },
                    "persisted": {
                        "report": {"id": 21},
                        "notification": {"id": 31},
                        "audit": {"id": 41},
                    },
                },
            }

    class _FakeClient:
        dashboard = _FakeDashboardModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()[
        "dashboard.create.auto_advisor_weekly_report"
    ]
    assert manifest.required_roles == ()
    assert manifest.legacy_tool_names == ("create_auto_advisor_weekly_report",)
    assert "as_of" in manifest.input_schema["required"]

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="dashboard.create.auto_advisor_weekly_report",
        arguments={
            "account_id": 7,
            "as_of": "2026-07-12",
            "idempotency_key": f"idem-dashboard-weekly-report-{expected_operation}",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["operation"] == expected_operation
    assert preview["summary"] == {
        "account_id": "7",
        "account_name": "Primary",
        "as_of": "2026-07-12",
        "week_start": "2026-07-06",
        "week_end": "2026-07-12",
        "operation": expected_operation,
        "existing_report_id": expected_existing_report_id,
        "will_upsert_report_snapshot": True,
        "will_create_notification": True,
        "will_write_audit_log": True,
        "will_execute_trade": False,
    }
    assert calls == [
        (
            "auto_advisor_weekly_report",
            {"account_id": "7", "as_of": "2026-07-12"},
        ),
        (
            "auto_advisor_weekly_report_history",
            {"account_id": "7", "limit": 20},
        ),
    ]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[2] == (
        "create_auto_advisor_weekly_report",
        {"account_id": "7", "as_of": "2026-07-12"},
    )
    assert "preview_only" not in calls[2][1]
    assert "idempotency_key" not in calls[2][1]
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"
