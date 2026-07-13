# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_agent_runtime."""

from .core_registry_support import *


def test_agent_proposal_create_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    def fake_create_agent_proposal(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "request_id": "req-proposal-1",
            "proposal": {
                "id": 42,
                "proposal_type": kwargs["proposal_type"],
                "risk_level": kwargs.get("risk_level", "medium"),
            },
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "create_agent_proposal",
        fake_create_agent_proposal,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="agent_proposal.create.proposal",
        arguments={
            "proposal_type": "trade_execute",
            "task_id": 8,
            "risk_level": "high",
            "approval_required": True,
            "proposal_payload": {"asset_code": "000001.SH", "direction": "long"},
            "approval_reason": "Need review before execution",
            "idempotency_key": "idem-agent-proposal",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["proposal_type"] == "trade_execute"
    assert preview_response["preview_result"]["proposal_payload_summary"]["field_count"] == 2
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["request_id"] == "req-proposal-1"
    assert captured_calls[0]["proposal_type"] == "trade_execute"
    assert "idempotency_key" not in captured_calls[0]
    assert "preview_only" not in captured_calls[0]
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[0]["affected_objects"]["proposal_type"] == "trade_execute"
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_agent_proposal_execute_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAgentProposalModule:
        @staticmethod
        def get_proposal(proposal_id):
            return {
                "id": proposal_id,
                "status": "approved",
                "risk_level": "high",
                "approval_required": True,
                "proposal_payload": {"asset_code": "000001.SH", "direction": "long"},
            }

    class _FakeClient:
        agent_proposal = _FakeAgentProposalModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_execute_agent_proposal(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "proposal": {"id": kwargs["proposal_id"], "status": "executed"},
            "execution_record_id": 501,
            "guardrail_decision": "allow",
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "execute_agent_proposal",
        fake_execute_agent_proposal,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="agent_proposal.execute.proposal",
        arguments={
            "proposal_id": 42,
            "idempotency_key": "idem-agent-execute",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["proposal_status"] == "approved"
    assert preview_response["preview_result"]["proposal_payload_summary"]["field_count"] == 2
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["execution_record_id"] == 501
    assert captured_calls[0]["proposal_id"] == 42
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["proposal_id"] == 42
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_agent_proposal_approve_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAgentProposalModule:
        @staticmethod
        def get_proposal(proposal_id):
            return {
                "id": proposal_id,
                "status": "submitted",
                "risk_level": "high",
                "approval_required": True,
                "proposal_payload": {"asset_code": "000001.SH", "direction": "long"},
            }

    class _FakeClient:
        agent_proposal = _FakeAgentProposalModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_approve_agent_proposal(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "proposal": {"id": kwargs["proposal_id"], "status": "approved"},
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "approve_agent_proposal",
        fake_approve_agent_proposal,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="agent_proposal.approve.proposal",
        arguments={
            "proposal_id": 42,
            "reason": "Guardrails satisfied",
            "idempotency_key": "idem-agent-approve",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["proposal_status"] == "submitted"
    assert preview_response["preview_result"]["target_status"] == "approved"
    assert preview_response["preview_result"]["reason"] == "Guardrails satisfied"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["proposal"]["status"] == "approved"
    assert captured_calls[0]["proposal_id"] == 42
    assert captured_calls[0]["reason"] == "Guardrails satisfied"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["proposal_id"] == 42
    assert audit_events[1]["event_type"] == "confirmation_completed"


def test_agent_proposal_reject_capability_runs_internal_preview_before_commit(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(monkeypatch, server_module.CORE_DISPATCHER)

    class _FakeAgentProposalModule:
        @staticmethod
        def get_proposal(proposal_id):
            return {
                "id": proposal_id,
                "status": "submitted",
                "risk_level": "medium",
                "approval_required": True,
                "proposal_payload": {"asset_code": "000001.SH", "direction": "long"},
            }

    class _FakeClient:
        agent_proposal = _FakeAgentProposalModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    def fake_reject_agent_proposal(**kwargs):
        captured_calls.append(dict(kwargs))
        return {
            "success": True,
            "proposal": {"id": kwargs["proposal_id"], "status": "rejected"},
        }

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        "reject_agent_proposal",
        fake_reject_agent_proposal,
    )

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="agent_proposal.reject.proposal",
        arguments={
            "proposal_id": 42,
            "reason": "Risk assumptions invalidated",
            "idempotency_key": "idem-agent-reject",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["proposal_status"] == "submitted"
    assert preview_response["preview_result"]["target_status"] == "rejected"
    assert preview_response["preview_result"]["reason"] == "Risk assumptions invalidated"
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["proposal"]["status"] == "rejected"
    assert captured_calls[0]["proposal_id"] == 42
    assert captured_calls[0]["reason"] == "Risk assumptions invalidated"
    assert "preview_only" not in captured_calls[0]
    assert "idempotency_key" not in captured_calls[0]
    assert audit_events[0]["affected_objects"]["proposal_id"] == 42
    assert audit_events[1]["event_type"] == "confirmation_completed"
