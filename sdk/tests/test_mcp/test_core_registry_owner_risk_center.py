# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_risk_center."""

from .core_registry_support import *


def test_agom_capability_call_reads_risk_center_floor_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_risk_floor",
        lambda **kwargs: {
            "max_total_position_pct": 0.75,
            "max_single_position_pct": 0.2,
            "min_cash_pct": 0.1,
            "force_stop_loss": True,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.floor",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.floor" in rendered
    assert "0.75" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_risk_center_template_catalog_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "list_risk_templates",
        lambda **kwargs: {
            "templates": [
                {
                    "key": "moderate",
                    "name": "Moderate",
                    "risk_profile": "moderate",
                    "max_total_position_pct": 0.7,
                    "is_active": True,
                }
            ],
            "total_count": 1,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.template_catalog",
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.template_catalog" in rendered
    assert "moderate" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_risk_center_effective_policy_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_effective_risk_policy",
        lambda **kwargs: {
            "account_id": kwargs["account_id"],
            "template_key": "moderate",
            "risk_profile": "moderate",
            "parameters": {"max_total_position_pct": 0.85, "min_cash_pct": 0.1},
            "sources": {"max_total_position_pct": "exception", "min_cash_pct": "global_floor"},
            "floor_applied": [{"field": "min_cash_pct", "requested": 0.02, "applied": 0.1}],
            "exceptions_applied": [
                {"field": "max_total_position_pct", "reason": "temporary rebalance"}
            ],
            "warnings": [],
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.effective_policy",
                "arguments": {"account_id": 7},
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.effective_policy" in rendered
    assert "temporary rebalance" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_risk_center_account_policy_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_account_risk_policy",
        lambda **kwargs: {
            "account_id": kwargs["account_id"],
            "risk_profile": "moderate",
            "max_total_position_pct": 0.72,
            "template_key": "moderate",
            "is_active": True,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.account_policy",
                "arguments": {"account_id": 7},
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.account_policy" in rendered
    assert "0.72" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_risk_center_exception_list_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "list_risk_exceptions",
        lambda **kwargs: {
            "exceptions": [
                {
                    "account_id": kwargs.get("account_id"),
                    "field_name": "max_total_position_pct",
                    "reason": "temporary rebalance",
                    "is_active": True,
                }
            ],
            "total_count": 1,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.exception_list",
                "arguments": {"account_id": 7},
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.exception_list" in rendered
    assert "temporary rebalance" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_risk_center_pre_trade_check_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "check_pre_trade_risk",
        lambda **kwargs: {
            "passed": False,
            "violations": ["max_total_position_pct exceeded"],
            "warnings": [],
            "metrics": {"order_value": 10000},
            "effective_policy": {"account_id": kwargs["account_id"]},
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.pre_trade_check",
                "arguments": {
                    "account_id": 7,
                    "symbol": "000001.SZ",
                    "side": "buy",
                    "quantity": 1000,
                    "price": 10,
                    "account_equity": 100000,
                    "total_position_value": 70000,
                    "cash_balance": 30000,
                },
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.pre_trade_check" in rendered
    assert "max_total_position_pct exceeded" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_risk_center_post_investment_check_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "check_post_investment_risk",
        lambda **kwargs: {
            "status": "breach",
            "passed": False,
            "violations": ["max_total_position_pct exceeded"],
            "warnings": [],
            "metrics": {"total_position_pct": 0.95},
            "position_alerts": [{"type": "hard_exclusion"}],
            "effective_policy": {"account_id": kwargs["account_id"]},
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.post_investment_check",
                "arguments": {
                    "account_id": 7,
                    "account_equity": 100000,
                    "cash_balance": 5000,
                    "total_position_value": 95000,
                    "daily_pnl_pct": -0.04,
                    "drawdown_pct": 0.12,
                    "positions": [
                        {"symbol": "000001.SZ", "market_value": 30000, "unrealized_pnl_pct": -0.09}
                    ],
                },
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.post_investment_check" in rendered
    assert "hard_exclusion" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_risk_center_daily_report_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "get_risk_center_daily_report",
        lambda **kwargs: {
            "account_id": kwargs["account_id"],
            "report_date": kwargs["report_date"],
            "risk_daily_report": {"status": "breach"},
            "position_daily_report": {"position_count": 2},
            "post_investment_check": {"effective_policy": {"account_id": kwargs["account_id"]}},
            "notes": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.daily_report",
                "arguments": {"account_id": 7, "report_date": "2026-06-28"},
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.daily_report" in rendered
    assert "2026-06-28" in rendered
    assert "core-only-fallback" in rendered


def test_agom_capability_call_reads_risk_center_daily_report_history_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "list_risk_center_daily_reports",
        lambda **kwargs: {
            "reports": [
                {
                    "account_id": kwargs.get("account_id"),
                    "report_date": "2026-06-28",
                    "risk_daily_report": {"status": "breach"},
                },
                {
                    "account_id": kwargs.get("account_id"),
                    "report_date": "2026-06-27",
                    "risk_daily_report": {"status": "ok"},
                },
            ],
            "total_count": 2,
            "source": "core-only-fallback",
        },
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "risk_center.read.daily_report_history",
                "arguments": {
                    "account_id": 7,
                    "start_date": "2026-06-27",
                    "end_date": "2026-06-28",
                    "limit": 10,
                },
            },
        )
    )

    rendered = str(result)
    assert "risk_center.read.daily_report_history" in rendered
    assert "2026-06-28" in rendered
    assert "core-only-fallback" in rendered


def test_risk_center_create_exception_previews_scope_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRiskCenterModule:
        @staticmethod
        def list_exceptions(*, account_id=None):
            calls.append(("list_exceptions", {"account_id": account_id}))
            return [
                {
                    "id": 5,
                    "account_id": account_id,
                    "field_name": "max_total_position_pct",
                    "allowed_value": 0.80,
                    "reason": "existing override",
                    "expires_at": "2026-07-13T08:00:00+08:00",
                    "is_active": True,
                },
                {
                    "id": 6,
                    "account_id": account_id,
                    "field_name": "min_cash_pct",
                    "allowed_value": 0.05,
                    "reason": "cash bridge",
                    "expires_at": "2026-07-13T08:00:00+08:00",
                    "is_active": True,
                },
            ]

        @staticmethod
        def create_exception(payload):
            calls.append(("create_exception", dict(payload)))
            return {
                "id": 11,
                "created_by": 3,
                "created_by_username": "risk_staff",
                **payload,
            }

    class _FakeClient:
        risk_center = _FakeRiskCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["risk_center.create.exception"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("create_risk_exception",)

    arguments = {
        "account_id": 7,
        "field_name": "max_total_position_pct",
        "allowed_value": 0.85,
        "reason": "temporary rebalance",
        "expires_at": "2026-07-13T09:00:00+08:00",
        "is_active": True,
        "idempotency_key": "idem-risk-center-create-exception",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="risk_center.create.exception",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["existing_scope_count"] == 2
    assert preview["same_field_exception_count"] == 1
    assert preview["summary"] == {
        "account_id": 7,
        "field_name": "max_total_position_pct",
        "existing_scope_count": 2,
        "same_field_exception_count": 1,
        "will_create_active_exception": True,
    }
    assert calls == [("list_exceptions", {"account_id": 7})]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 11
    assert calls[1][0] == "create_exception"
    committed_payload = calls[1][1]
    assert committed_payload == {
        "account_id": 7,
        "field_name": "max_total_position_pct",
        "allowed_value": 0.85,
        "reason": "temporary rebalance",
        "expires_at": "2026-07-13T09:00:00+08:00",
        "is_active": True,
    }
    assert "preview_only" not in committed_payload
    assert "idempotency_key" not in committed_payload
    assert audit_events[0]["affected_objects"]["account_id"] == 7
    assert audit_events[0]["affected_objects"]["field_name"] == "max_total_position_pct"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_risk_center_update_floor_previews_changes_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRiskCenterModule:
        @staticmethod
        def get_floor():
            calls.append(("get_floor", {}))
            return {
                "id": 4,
                "name": "Global Risk Floor",
                "max_total_position_pct": 0.95,
                "min_cash_pct": 0.03,
                "force_stop_loss": True,
                "hard_exclusions": [],
                "is_active": True,
                "updated_at": "2026-07-12T01:00:00+08:00",
            }

        @staticmethod
        def update_floor(payload):
            calls.append(("update_floor", dict(payload)))
            return {
                "id": 4,
                "is_active": True,
                **payload,
            }

    class _FakeClient:
        risk_center = _FakeRiskCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["risk_center.update.floor"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("update_risk_floor",)
    assert "is_active" not in manifest.input_schema["properties"]

    arguments = {
        "max_total_position_pct": 0.8,
        "min_cash_pct": 0.08,
        "hard_exclusions": ["ST", "suspended"],
        "reason": "tighten exposure before event risk",
        "idempotency_key": "idem-risk-center-update-floor",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="risk_center.update.floor",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["summary"] == {
        "floor_id": 4,
        "changed_field_count": 3,
        "changed_fields": [
            "hard_exclusions",
            "max_total_position_pct",
            "min_cash_pct",
        ],
        "will_persist_default_floor_if_missing": False,
    }
    assert calls == [("get_floor", {})]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[1] == (
        "update_floor",
        {
            "max_total_position_pct": 0.8,
            "min_cash_pct": 0.08,
            "hard_exclusions": ["ST", "suspended"],
            "reason": "tighten exposure before event risk",
        },
    )
    committed_payload = calls[1][1]
    assert "preview_only" not in committed_payload
    assert "idempotency_key" not in committed_payload
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_risk_center_update_account_policy_previews_owner_scoped_upsert(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRiskCenterModule:
        @staticmethod
        def list_account_policies():
            calls.append(("list_account_policies", {}))
            return [
                {
                    "id": 8,
                    "account_id": 7,
                    "template": 2,
                    "risk_profile": "moderate",
                    "max_total_position_pct": 0.72,
                    "min_cash_pct": 0.05,
                    "is_active": True,
                }
            ]

        @staticmethod
        def list_templates():
            calls.append(("list_templates", {}))
            return [
                {
                    "id": 3,
                    "key": "risk-event",
                    "name": "Risk Event",
                    "risk_profile": "conservative",
                    "is_active": True,
                }
            ]

        @staticmethod
        def upsert_account_policy(payload):
            calls.append(("upsert_account_policy", dict(payload)))
            return {
                "id": 8,
                **payload,
            }

    class _FakeClient:
        risk_center = _FakeRiskCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["risk_center.update.account_policy"]
    assert manifest.required_roles == ()
    assert manifest.legacy_tool_names == ("upsert_account_risk_policy",)

    arguments = {
        "account_id": 7,
        "template_id": 3,
        "risk_profile": "conservative",
        "max_total_position_pct": 0.65,
        "min_cash_pct": 0.12,
        "reason": "reduce account risk before event",
        "idempotency_key": "idem-risk-center-update-account-policy",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="risk_center.update.account_policy",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["operation"] == "update"
    assert preview["template"]["id"] == 3
    assert preview["summary"] == {
        "account_id": 7,
        "operation": "update",
        "policy_id": 8,
        "changed_field_count": 4,
        "changed_fields": [
            "max_total_position_pct",
            "min_cash_pct",
            "risk_profile",
            "template_id",
        ],
        "target_is_active": True,
    }
    assert calls == [
        ("list_account_policies", {}),
        ("list_templates", {}),
    ]

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[2] == (
        "upsert_account_policy",
        {
            "account_id": 7,
            "template_id": 3,
            "risk_profile": "conservative",
            "max_total_position_pct": 0.65,
            "min_cash_pct": 0.12,
            "reason": "reduce account risk before event",
        },
    )
    committed_payload = calls[2][1]
    assert "preview_only" not in committed_payload
    assert "idempotency_key" not in committed_payload
    assert audit_events[0]["affected_objects"]["account_id"] == 7
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_risk_center_generate_daily_report_previews_overwrite_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeRiskCenterModule:
        @staticmethod
        def check_post_investment(payload):
            calls.append(("check_post_investment", dict(payload)))
            return {
                "status": "breach",
                "passed": False,
                "violations": ["max_total_position_pct exceeded"],
                "warnings": [],
                "position_alerts": [],
                "metrics": {"position_ratio": 0.95},
                "effective_policy": {"account_id": 7},
            }

        @staticmethod
        def list_daily_reports(**kwargs):
            calls.append(("list_daily_reports", dict(kwargs)))
            return [
                {
                    "id": 12,
                    "account_id": 7,
                    "report_date": "2026-07-12",
                    "status": "ok",
                }
            ]

        @staticmethod
        def generate_daily_report(payload):
            calls.append(("generate_daily_report", dict(payload)))
            return {
                "report_id": 12,
                "account_id": 7,
                "report_date": "2026-07-12",
                "risk_daily_report": {"status": "breach"},
                "position_daily_report": {"position_count": 1},
                "post_investment_check": {"passed": False},
            }

    class _FakeClient:
        risk_center = _FakeRiskCenterModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["risk_center.generate.daily_report"]
    assert manifest.required_roles == ()
    assert manifest.legacy_tool_names == ("generate_risk_center_daily_report",)
    assert "report_date" in manifest.input_schema["required"]

    arguments = {
        "account_id": 7,
        "report_date": "2026-07-12",
        "account_equity": 100000,
        "cash_balance": 5000,
        "total_position_value": 95000,
        "daily_pnl_pct": -0.04,
        "positions": [
            {
                "symbol": "000001.SZ",
                "market_value": 95000,
                "unrealized_pnl_pct": -0.02,
            }
        ],
        "idempotency_key": "idem-risk-center-generate-daily-report",
    }
    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="risk_center.generate.daily_report",
        arguments=arguments,
    )

    assert preview_response["status"] == "confirmation_required"
    preview = preview_response["preview_result"]
    assert preview["preview_only"] is True
    assert preview["operation"] == "overwrite"
    assert preview["summary"] == {
        "account_id": 7,
        "report_date": "2026-07-12",
        "operation": "overwrite",
        "existing_report_id": 12,
        "existing_status": "ok",
        "projected_status": "breach",
        "projected_passed": False,
        "projected_violation_count": 1,
        "position_count": 1,
    }
    assert [name for name, _ in calls] == [
        "check_post_investment",
        "list_daily_reports",
    ]
    assert calls[1][1] == {
        "account_id": 7,
        "start_date": "2026-07-12",
        "end_date": "2026-07-12",
        "limit": 1,
    }

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert calls[2][0] == "generate_daily_report"
    committed_payload = calls[2][1]
    assert committed_payload["report_date"] == "2026-07-12"
    assert committed_payload["account_id"] == 7
    assert "preview_only" not in committed_payload
    assert "idempotency_key" not in committed_payload
    assert audit_events[0]["affected_objects"]["preview_summary"] == preview["summary"]
    assert audit_events[1]["event_type"] == "confirmation_completed"
