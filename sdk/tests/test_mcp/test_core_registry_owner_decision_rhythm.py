# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_decision_rhythm."""

from .core_registry_support import *


def test_decision_rhythm_core_only_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _DecisionRhythm:
        def list_quotas(self):
            calls.append(("list_quotas", None))
            return [{"quota_id": "quota-weekly"}]

        def list_requests(self):
            calls.append(("list_requests", None))
            return [{"request_id": "request-001"}]

        def get_request(self, request_id):
            calls.append(("get_request", request_id))
            return {
                "success": True,
                "result": {
                    "request_id": request_id,
                    "asset_code": "600519.SH",
                },
            }

        def summary(self):
            calls.append(("summary", None))
            return {
                "success": True,
                "result": {
                    "quota_status": {"weekly": "available"},
                    "pending_requests": 2,
                },
            }

    class _Client:
        decision_rhythm = _DecisionRhythm()
        decision_workflow = None

    class _DecisionWorkflow:
        def list_recommendations(self, **kwargs):
            calls.append(("list_recommendations", kwargs))
            return {
                "success": True,
                "data": {
                    "recommendations": [{"recommendation_id": "rec-001"}],
                    "total_count": 1,
                    "page": kwargs["page"],
                    "page_size": kwargs["page_size"],
                },
            }

        def get_transition_plan(self, plan_id):
            calls.append(("get_transition_plan", plan_id))
            return {
                "success": True,
                "data": {
                    "plan_id": plan_id,
                    "account_id": "acct-1",
                    "status": "READY_FOR_APPROVAL",
                    "orders": [],
                },
            }

    _Client.decision_workflow = _DecisionWorkflow()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["list_decision_quotas"]() == {
        "quotas": [{"quota_id": "quota-weekly"}],
        "total_count": 1,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["list_decision_requests"]() == {
        "requests": [{"request_id": "request-001"}],
        "total_count": 1,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_decision_request"]("request-001") == {
        "request_id": "request-001",
        "asset_code": "600519.SH",
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_decision_rhythm_summary"]() == {
        "quota_status": {"weekly": "available"},
        "pending_requests": 2,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["decision_workflow_list_recommendations"](
        account_id="acct-1",
        user_action="ADOPTED",
        page=2,
        page_size=10,
    ) == {
        "recommendations": [{"recommendation_id": "rec-001"}],
        "total_count": 1,
        "page": 2,
        "page_size": 10,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["decision_workflow_get_transition_plan"](
        "plan-001"
    ) == {
        "plan_id": "plan-001",
        "account_id": "acct-1",
        "status": "READY_FOR_APPROVAL",
        "orders": [],
    }
    assert calls == [
        ("list_quotas", None),
        ("list_requests", None),
        ("get_request", "request-001"),
        ("summary", None),
        (
            "list_recommendations",
            {
                "account_id": "acct-1",
                "status": None,
                "user_action": "ADOPTED",
                "security_code": None,
                "recommendation_id": None,
                "include_ignored": False,
                "page": 2,
                "page_size": 10,
            },
        ),
        ("get_transition_plan", "plan-001"),
    ]


def test_confirmed_write_capability_runs_preview_before_create(monkeypatch: pytest.MonkeyPatch):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_preview_execution(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "data": {
                "account_id": kwargs["account_id"],
                "plan_id": kwargs.get("plan_id"),
                "request_id": "req-1" if kwargs.get("create_request") else None,
                "create_request": kwargs.get("create_request", False),
            },
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "decision_workflow_preview_execution",
        fake_preview_execution,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="decision.create.execution_request",
        arguments={
            "account_id": "acct-1",
            "plan_id": "plan-1",
            "idempotency_key": "idem-preview",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["capability_key"] == "decision.create.execution_request"
    assert preview_response["preview_result"]["data"]["request_id"] is None
    assert captured_calls[0]["create_request"] is False

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["ok"] is True
    assert resume_response["status"] == "completed"
    assert resume_response["result"]["data"]["request_id"] == "req-1"
    assert captured_calls[1]["create_request"] is True
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[0]["confirmation_status"] == "pending"
    assert audit_events[0]["affected_objects"]["account_id"] == "acct-1"
    assert audit_events[1]["event_type"] == "confirmation_completed"
    assert audit_events[1]["confirmation_status"] == "completed"
    assert audit_events[1]["context"].request_id == audit_events[0]["context"].request_id


def test_confirmed_write_capability_requires_idempotency_key():
    import agomtradepro_mcp.server as server_module

    response = server_module.CORE_DISPATCHER.call(
        capability_key="decision.create.execution_request",
        arguments={
            "account_id": "acct-1",
            "plan_id": "plan-1",
        },
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "missing_idempotency_key"


def test_confirmed_write_capability_reuses_idempotency_key(monkeypatch: pytest.MonkeyPatch):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_preview_execution(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "data": {
                "request_id": "req-1" if kwargs.get("create_request") else None,
                "create_request": kwargs.get("create_request", False),
            },
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "decision_workflow_preview_execution",
        fake_preview_execution,
    )

    first = server_module.CORE_DISPATCHER.call(
        capability_key="decision.create.execution_request",
        arguments={
            "account_id": "acct-1",
            "plan_id": "plan-1",
            "idempotency_key": "idem-1",
        },
    )
    second = server_module.CORE_DISPATCHER.call(
        capability_key="decision.create.execution_request",
        arguments={
            "account_id": "acct-1",
            "plan_id": "plan-1",
            "idempotency_key": "idem-1",
        },
    )

    assert first["status"] == "confirmation_required"
    assert second["status"] == "confirmation_required"
    assert second["idempotency_reused"] is True
    assert second["confirmation_token"] == first["confirmation_token"]
    assert len(captured_calls) == 1

    completed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=first["confirmation_token"],
        approve=True,
    )
    replay = server_module.CORE_DISPATCHER.call(
        capability_key="decision.create.execution_request",
        arguments={
            "account_id": "acct-1",
            "plan_id": "plan-1",
            "idempotency_key": "idem-1",
        },
    )

    assert completed["status"] == "completed"
    assert replay["status"] == "idempotent_replay"
    assert replay["idempotency_reused"] is True
    assert replay["result"]["data"]["request_id"] == "req-1"
    assert len(captured_calls) == 2
    assert any(event["event_type"] == "confirmation_reused" for event in audit_events)
    assert any(event["event_type"] == "idempotent_replay" for event in audit_events)


def test_confirmed_write_capability_audits_idempotency_conflict(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_preview_execution(**kwargs):
        return {
            "success": True,
            "data": {
                "request_id": None,
                "create_request": kwargs.get("create_request", False),
            },
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "decision_workflow_preview_execution",
        fake_preview_execution,
    )

    server_module.CORE_DISPATCHER.call(
        capability_key="decision.create.execution_request",
        arguments={
            "account_id": "acct-1",
            "plan_id": "plan-1",
            "idempotency_key": "idem-conflict",
        },
    )
    conflict = server_module.CORE_DISPATCHER.call(
        capability_key="decision.create.execution_request",
        arguments={
            "account_id": "acct-1",
            "plan_id": "plan-2",
            "idempotency_key": "idem-conflict",
        },
    )

    assert conflict["ok"] is False
    assert conflict["error"]["code"] == "idempotency_key_conflict"
    assert any(event["event_type"] == "idempotency_conflict" for event in audit_events)


def test_confirmed_write_capability_audits_confirmation_cancelled(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_preview_execution(**kwargs):
        return {
            "success": True,
            "data": {
                "request_id": None,
                "create_request": kwargs.get("create_request", False),
            },
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "decision_workflow_preview_execution",
        fake_preview_execution,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="decision.create.execution_request",
        arguments={
            "account_id": "acct-cancel",
            "plan_id": "plan-cancel",
            "idempotency_key": "idem-cancel",
        },
    )

    cancelled = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=False,
    )

    assert cancelled["status"] == "cancelled"
    assert any(event["event_type"] == "confirmation_cancelled" for event in audit_events)


def test_decision_submit_request_batch_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_submit_batch_decision_request(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "requests": [
                {"request_id": "req-1", "asset_code": "000001.SH"},
                {"request_id": "req-2", "asset_code": "000002.SZ"},
            ],
            "summary": {"approved_count": 2, "rejected_count": 0},
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "submit_batch_decision_request",
        fake_submit_batch_decision_request,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="decision.submit.request_batch",
        arguments={
            "payload": {
                "quota_period": "weekly",
                "requests": [
                    {
                        "asset_code": "000001.SH",
                        "asset_class": "equity",
                        "direction": "BUY",
                        "priority": "high",
                    },
                    {
                        "asset_code": "000002.SZ",
                        "asset_class": "equity",
                        "direction": "SELL",
                        "priority": "medium",
                    },
                ],
            },
            "idempotency_key": "idem-decision-batch",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["summary"]["request_count"] == 2
    assert preview_response["preview_result"]["summary"]["direction_counts"]["BUY"] == 1
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["summary"]["approved_count"] == 2
    assert captured_calls[0]["payload"]["quota_period"] == "weekly"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["payload_request_count"] == 2
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_decision_submit_request_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_submit_decision_request(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "request": {"request_id": "req-100", "asset_code": "000001.SH"},
            "summary": {"status": "submitted"},
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "submit_decision_request",
        fake_submit_decision_request,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="decision.submit.request",
        arguments={
            "payload": {
                "asset_code": "000001.SH",
                "asset_class": "equity",
                "direction": "BUY",
                "priority": "high",
                "quota_period": "weekly",
            },
            "idempotency_key": "idem-decision-single",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["summary"]["request_count"] == 1
    assert preview_response["preview_result"]["summary"]["asset_code"] == "000001.SH"
    assert preview_response["preview_result"]["summary"]["direction"] == "BUY"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["request"]["request_id"] == "req-100"
    assert captured_calls[0]["payload"]["asset_code"] == "000001.SH"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["preview_summary"]["request_count"] == 1
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_decision_execute_request_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDecisionRhythmModule:
        @staticmethod
        def get_request(request_id):
            return {
                "request_id": request_id,
                "status": "approved",
                "execution_status": "PENDING",
            }

    class _FakeClient:
        decision_rhythm = _FakeDecisionRhythmModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_decision_execute_request(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "request_id": kwargs["request_id"],
            "execution_status": "EXECUTED",
            "execution_ref": {"trade_id": 901},
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "decision_execute_request",
        fake_decision_execute_request,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="decision.execute.request",
        arguments={
            "request_id": "req-exec-1",
            "payload": {
                "target": "SIMULATED",
                "sim_account_id": 1,
                "asset_code": "000001.SH",
                "action": "buy",
                "quantity": 1000,
                "reason": "Execute approved request",
            },
            "idempotency_key": "idem-decision-exec",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["request_status"] == "approved"
    assert preview_response["preview_result"]["execution_status"] == "PENDING"
    assert preview_response["preview_result"]["payload_summary"]["target"] == "SIMULATED"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["execution_status"] == "EXECUTED"
    assert captured_calls[0]["request_id"] == "req-exec-1"
    assert captured_calls[0]["payload"]["asset_code"] == "000001.SH"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["request_id"] == "req-exec-1"
    assert audit_events[0]["affected_objects"]["payload_target"] == "SIMULATED"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_decision_cancel_request_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeDecisionRhythmModule:
        @staticmethod
        def get_request(request_id):
            return {
                "request_id": request_id,
                "status": "approved",
                "execution_status": "PENDING",
                "candidate_status": "active",
            }

    class _FakeClient:
        decision_rhythm = _FakeDecisionRhythmModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_decision_cancel_request(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "request_id": kwargs["request_id"],
            "status": "cancelled",
            "candidate_status": "cancelled",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "decision_cancel_request",
        fake_decision_cancel_request,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="decision.cancel.request",
        arguments={
            "request_id": "req-cancel-1",
            "reason": "Operator cancelled stale request",
            "idempotency_key": "idem-decision-cancel",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["request_status"] == "approved"
    assert preview_response["preview_result"]["target_status"] == "cancelled"
    assert preview_response["preview_result"]["reason"] == "Operator cancelled stale request"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["status"] == "cancelled"
    assert captured_calls[0]["request_id"] == "req-cancel-1"
    assert captured_calls[0]["reason"] == "Operator cancelled stale request"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["request_id"] == "req-cancel-1"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_decision_reset_quota_capability_previews_before_staff_only_reset(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(
        monkeypatch,
        server_module.CORE_DISPATCHER,
    )

    class _FakeDecisionRhythmModule:
        @staticmethod
        def list_quotas(*, account_id=None, period=None):
            assert account_id == "acct-1"
            assert period == "weekly"
            return [
                {
                    "quota_id": "quota-acct-1-weekly",
                    "account_id": "acct-1",
                    "period": "weekly",
                    "used_decisions": 7,
                    "used_executions": 3,
                    "max_decisions": 10,
                    "max_execution_count": 5,
                }
            ]

        @staticmethod
        def reset_quota(payload):
            captured_calls.append(dict(payload))
            return {
                "success": True,
                "account_id": payload["account_id"],
                "reset_periods": [payload["period"]],
            }

    class _FakeClient:
        decision_rhythm = _FakeDecisionRhythmModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["decision.reset.quota"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("reset_decision_quota",)

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="decision.reset.quota",
        arguments={
            "account_id": "acct-1",
            "period": "weekly",
            "idempotency_key": "idem-decision-quota-reset",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["summary"] == {
        "account_id": "acct-1",
        "quota_count": 1,
        "periods": ["weekly"],
    }
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["reset_periods"] == ["weekly"]
    assert captured_calls == [{"account_id": "acct-1", "period": "weekly"}]
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[1]["event_type"] == "confirmation_completed"
