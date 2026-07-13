# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_audit."""

from .core_registry_support import *


def test_audit_core_only_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _Audit:
        def get_summary(self, **kwargs):
            calls.append(("get_summary", kwargs))
            return [{"id": 8, "backtest_id": kwargs.get("backtest_id")}]

        def list_execution_links(self, **kwargs):
            calls.append(("list_execution_links", kwargs))
            return {"success": True, "links": []}

    class _Client:
        audit = _Audit()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    summary = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_audit_summary"](backtest_id=17)
    assert summary["success"] is True
    assert summary["total_count"] == 1
    assert summary["query"] == {"mode": "backtest", "backtest_id": 17}
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_audit_summary"](
        start_date="2026-07-01"
    ) == {
        "success": False,
        "reports": [],
        "total_count": 0,
        "query": {},
        "error": "start_date and end_date must be provided together",
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["list_audit_execution_links"](
        account_id="7",
        transaction_source="simulated_trade",
        limit=10,
    ) == {"success": True, "links": []}
    assert calls == [
        ("get_summary", {"backtest_id": 17}),
        (
            "list_execution_links",
            {
                "account_id": "7",
                "recommendation_id": None,
                "transaction_source": "simulated_trade",
                "limit": 10,
            },
        ),
    ]


def test_audit_threshold_validation_capability_previews_before_staff_only_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(
        monkeypatch,
        server_module.CORE_DISPATCHER,
    )

    class _FakeAuditModule:
        @staticmethod
        def preview_validation(payload):
            calls.append(("preview_validation", dict(payload)))
            return {
                "success": True,
                "preview": {
                    **payload,
                    "active_indicator_count": 2,
                    "indicator_codes": ["CN_PMI", "CN_CPI"],
                    "writes": [
                        "validation_summary",
                        "indicator_performance_reports",
                    ],
                },
            }

        @staticmethod
        def run_validation(payload):
            calls.append(("run_validation", dict(payload)))
            return {
                "success": True,
                "validation_run_id": "validation_governed",
                "report": None,
            }

    class _FakeClient:
        audit = _FakeAuditModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())
    manifest = CapabilityRegistryLoader().build_registry()["audit.start.threshold_validation"]
    assert manifest.required_roles == ("staff",)
    assert manifest.idempotency == "required"
    assert manifest.legacy_tool_names == (
        "run_audit_validation",
        "validate_all_indicators",
    )

    arguments = {
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "idempotency_key": "idem-audit-validation",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="audit.start.threshold_validation",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "active_indicator_count": 2,
        "writes": ["validation_summary", "indicator_performance_reports"],
        "synchronous_execution": True,
        "partial_indicator_failure_possible": True,
    }
    assert calls == [
        (
            "preview_validation",
            {"start_date": "2025-01-01", "end_date": "2025-12-31"},
        )
    ]

    resumed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )
    assert resumed["status"] == "completed"
    assert resumed["result"]["validation_run_id"] == "validation_governed"
    assert calls[1] == (
        "run_validation",
        {"start_date": "2025-01-01", "end_date": "2025-12-31"},
    )

    replay = server_module.CORE_DISPATCHER.call(
        capability_key="audit.start.threshold_validation",
        arguments=arguments,
    )
    assert replay["status"] == "idempotent_replay"
    assert len(calls) == 2
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"
