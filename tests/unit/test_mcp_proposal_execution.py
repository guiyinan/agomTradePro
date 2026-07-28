"""Tests for durable Terminal MCP approval and execution."""

import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

from apps.agent_runtime.application.proposal_use_cases import ExecuteProposalUseCase
from apps.agent_runtime.domain.entities import (
    AgentProposal,
    ApprovalStatus,
    GuardrailDecision,
    ProposalStatus,
    RiskLevel,
)
from apps.agent_runtime.infrastructure.mcp_proposal_executor import (
    ApprovedMcpCapabilityExecutor,
)


def _approved_proposal() -> AgentProposal:
    """Return an approved Terminal MCP proposal."""

    return AgentProposal(
        id=9,
        request_id="apr_20260713_ABC123",
        proposal_type="terminal_mcp_capability",
        status=ProposalStatus.APPROVED,
        risk_level=RiskLevel.HIGH,
        approval_required=True,
        approval_status=ApprovalStatus.APPROVED,
        proposal_payload={
            "capability_key": "portfolio.write.rebalance",
            "arguments": {"account_id": 7},
            "session_id": "sess-1",
        },
        created_by=7,
    )


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_approved_executor_stages_and_resumes_through_core_mcp_tools(mock_call):
    """An approved proposal must execute through both governed MCP core calls."""

    mock_call.side_effect = [
        {
            "ok": False,
            "status": "confirmation_required",
            "capability_key": "portfolio.write.rebalance",
            "confirmation_token": "confirm-1",
        },
        {
            "ok": True,
            "status": "completed",
            "capability_key": "portfolio.write.rebalance",
            "result": {"rebalanced": True},
        },
    ]

    result = ApprovedMcpCapabilityExecutor().execute(
        proposal=_approved_proposal(),
        actor={"user_id": 1, "is_staff": True},
        context={},
    )

    assert result["ok"] is True
    assert mock_call.call_args_list == [
        call(
            "agom_capability_call",
            {
                "capability_key": "portfolio.write.rebalance",
                "arguments": {"account_id": 7},
                "context": {
                    "request_id": "apr_20260713_ABC123",
                    "user_id": 1,
                    "username": "terminal_approver",
                    "mcp_role": "admin",
                    "client_id": "terminal_approval",
                },
            },
        ),
        call(
            "agom_confirmation_resume",
            {"confirmation_token": "confirm-1", "approve": True},
        ),
    ]


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_approved_executor_rejects_mcp_failure_envelope(mock_call):
    """A failed MCP envelope must not be recorded as successful execution."""

    mock_call.return_value = {
        "ok": False,
        "status": "error",
        "error": {"code": "missing_required_arguments"},
    }

    executor = ApprovedMcpCapabilityExecutor()

    try:
        executor.execute(
            proposal=_approved_proposal(),
            actor={"user_id": 1, "is_staff": True},
            context={},
        )
    except RuntimeError as exc:
        assert "missing_required_arguments" in str(exc)
    else:
        raise AssertionError("Expected MCP execution failure")


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_approved_executor_uses_staff_role_only_during_mcp_execution(mock_call, monkeypatch):
    """The trusted approval actor role is scoped to the guarded MCP call."""

    observed_contexts = []

    def _call(_tool_name, _params):
        from agomtradepro.transport import get_request_transport
        from agomtradepro_mcp.audit import get_audit_sink

        observed_contexts.append(
            {
                "role": os.environ.get("AGOMTRADEPRO_MCP_ROLE"),
                "user_id": os.environ.get("AGOMTRADEPRO_INTERNAL_USER_ID"),
                "username": os.environ.get("AGOMTRADEPRO_INTERNAL_USERNAME"),
                "source": os.environ.get("AGOMTRADEPRO_INTERNAL_SOURCE"),
                "has_local_transport": get_request_transport() is not None,
                "has_local_audit_sink": get_audit_sink() is not None,
            }
        )
        return {"ok": True, "status": "completed", "result": {}}

    mock_call.side_effect = _call
    for key in (
        "AGOMTRADEPRO_MCP_ROLE",
        "AGOMTRADEPRO_INTERNAL_USER_ID",
        "AGOMTRADEPRO_INTERNAL_USERNAME",
        "AGOMTRADEPRO_INTERNAL_SOURCE",
    ):
        monkeypatch.delenv(key, raising=False)

    ApprovedMcpCapabilityExecutor().execute(
        proposal=_approved_proposal(),
        actor={"user_id": 1, "username": "approver", "is_staff": True},
        context={},
    )

    assert observed_contexts == [
        {
            "role": "admin",
            "user_id": "1",
            "username": "approver",
            "source": "terminal_approval",
            "has_local_transport": True,
            "has_local_audit_sink": True,
        }
    ]
    assert "AGOMTRADEPRO_MCP_ROLE" not in os.environ
    assert "AGOMTRADEPRO_INTERNAL_USER_ID" not in os.environ


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_executor_rejects_malformed_actor_before_mcp_io(mock_call):
    """Truthy strings and malformed identities must never grant an MCP role."""

    invalid_actors = [
        None,
        {"user_id": 0, "is_staff": True},
        {"user_id": True, "is_staff": True},
        {"user_id": 1, "is_staff": "false"},
        {"user_id": 1, "is_staff": True, "username": "admin\nINJECTED=true"},
    ]

    for actor in invalid_actors:
        with pytest.raises(RuntimeError, match="approved_mcp_actor"):
            ApprovedMcpCapabilityExecutor().execute(
                proposal=_approved_proposal(),
                actor=actor,
                context={},
            )

    mock_call.assert_not_called()


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_nonstaff_actor_cannot_inject_admin_role(mock_call):
    """Untrusted role claims cannot override the strict staff flag."""

    observed = {}

    def _call(_tool_name, params):
        observed["environment_role"] = os.environ.get("AGOMTRADEPRO_MCP_ROLE")
        observed["audit_role"] = params["context"]["mcp_role"]
        return {"ok": True, "status": "completed", "result": {}}

    mock_call.side_effect = _call

    ApprovedMcpCapabilityExecutor().execute(
        proposal=_approved_proposal(),
        actor={
            "user_id": 2,
            "username": "operator",
            "is_staff": False,
            "roles": ["admin"],
        },
        context={},
    )

    assert observed == {
        "environment_role": "read_only",
        "audit_role": "read_only",
    }


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_executor_rejects_malformed_proposal_payload_before_mcp_io(mock_call):
    """Capability keys, exact fields and JSON arguments are bounded pre-I/O."""

    invalid_payloads = [
        {
            "capability_key": "portfolio.write.rebalance",
            "arguments": {"account_id": 7},
            "unexpected": True,
        },
        {"capability_key": "../admin", "arguments": {"account_id": 7}},
        {"capability_key": "portfolio.write.rebalance", "arguments": []},
        {
            "capability_key": "portfolio.write.rebalance",
            "arguments": {"weight": float("nan")},
        },
        {
            "capability_key": "portfolio.write.rebalance",
            "arguments": {"payload": "x" * 262_145},
        },
        {
            "capability_key": "portfolio.write.rebalance",
            "arguments": {"account_id": 7},
            "session_id": "x" * 129,
        },
    ]

    for payload in invalid_payloads:
        proposal = replace(_approved_proposal(), proposal_payload=payload)
        with pytest.raises(RuntimeError, match="approved_mcp"):
            ApprovedMcpCapabilityExecutor().execute(
                proposal=proposal,
                actor={"user_id": 1, "is_staff": True},
                context={},
            )

    mock_call.assert_not_called()


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
@pytest.mark.parametrize(
    "token",
    ["", "bad token", "../confirmation", "x" * 4097],
)
def test_executor_rejects_invalid_confirmation_token(mock_call, token):
    """Unbounded or unsafe confirmation tokens never reach resume."""

    mock_call.return_value = {
        "ok": False,
        "status": "confirmation_required",
        "confirmation_token": token,
    }

    with pytest.raises(RuntimeError, match="mcp_confirmation_token_invalid"):
        ApprovedMcpCapabilityExecutor().execute(
            proposal=_approved_proposal(),
            actor={"user_id": 1, "is_staff": True},
            context={},
        )

    assert mock_call.call_count == 1


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_executor_redacts_mcp_error_message(mock_call):
    """Only a governed error code may escape a failed MCP envelope."""

    mock_call.return_value = {
        "ok": False,
        "status": "error",
        "error": {
            "code": "permission_denied",
            "message": "postgresql://admin:secret@internal/db",
        },
    }

    with pytest.raises(RuntimeError) as exc_info:
        ApprovedMcpCapabilityExecutor().execute(
            proposal=_approved_proposal(),
            actor={"user_id": 1, "is_staff": True},
            context={},
        )

    assert str(exc_info.value) == "permission_denied"
    assert "secret" not in str(exc_info.value)


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_executor_redacts_transport_exception_and_restores_environment(
    mock_call,
    monkeypatch,
):
    """Dynamic SDK exceptions are stable and scoped environment is restored."""

    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE", "preexisting")
    monkeypatch.setenv("AGOMTRADEPRO_INTERNAL_USER_ID", "99")
    mock_call.side_effect = RuntimeError("redis://admin:secret@internal/cache")

    with pytest.raises(RuntimeError) as exc_info:
        ApprovedMcpCapabilityExecutor().execute(
            proposal=_approved_proposal(),
            actor={"user_id": 1, "is_staff": True},
            context={},
        )

    assert str(exc_info.value) == "mcp_execution_transport_failed"
    assert "secret" not in str(exc_info.value)
    assert os.environ["AGOMTRADEPRO_MCP_ROLE"] == "preexisting"
    assert os.environ["AGOMTRADEPRO_INTERNAL_USER_ID"] == "99"


@patch("apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool")
def test_executor_rejects_nonfinite_result_envelope(mock_call):
    """Non-standard JSON values cannot enter durable execution evidence."""

    mock_call.return_value = {
        "ok": True,
        "status": "completed",
        "result": {"score": float("inf")},
    }

    with pytest.raises(RuntimeError, match="mcp_stage_envelope_invalid"):
        ApprovedMcpCapabilityExecutor().execute(
            proposal=_approved_proposal(),
            actor={"user_id": 1, "is_staff": True},
            context={},
        )


def test_execute_use_case_records_real_mcp_result_before_marking_executed():
    """Proposal execution records the MCP envelope, not just the proposal payload."""

    proposal = _approved_proposal()
    executed_proposal = replace(proposal, status=ProposalStatus.EXECUTED)
    proposal_repo = Mock()
    proposal_repo.get_proposal.return_value = proposal
    proposal_repo.create_guardrail_decision.return_value = {"decision": "allowed"}
    proposal_repo.create_execution_record.return_value = 88
    proposal_repo.update_proposal_status.return_value = executed_proposal
    guardrails = Mock()
    guardrails.check_pre_execution.return_value = SimpleNamespace(
        overall_decision=GuardrailDecision.ALLOWED,
        reason_code="allowed",
        message="allowed",
        evidence={},
        requires_human=False,
    )
    executor = Mock()
    executor.execute.return_value = {
        "ok": True,
        "status": "completed",
        "result": {"rebalanced": True},
    }

    output = ExecuteProposalUseCase(
        guardrail_engine=guardrails,
        timeline_service=Mock(),
        audit_service=Mock(),
        proposal_repo=proposal_repo,
        approved_capability_executor=executor,
    ).execute(
        proposal_id=9,
        actor={"user_id": 1, "is_staff": True},
        context={},
    )

    assert output.execution_record_id == 88
    execution_output = proposal_repo.create_execution_record.call_args.kwargs["execution_output"]
    assert execution_output["mcp_result"]["result"]["rebalanced"] is True
    proposal_repo.update_proposal_status.assert_called_once_with(
        9,
        status=ProposalStatus.EXECUTED.value,
    )


def test_execute_use_case_marks_failed_when_mcp_execution_raises():
    """An MCP runtime failure persists failed state and does not become executed."""

    proposal = _approved_proposal()
    proposal_repo = Mock()
    proposal_repo.get_proposal.return_value = proposal
    proposal_repo.create_guardrail_decision.return_value = {"decision": "allowed"}
    proposal_repo.create_execution_record.return_value = 89
    guardrails = Mock()
    guardrails.check_pre_execution.return_value = SimpleNamespace(
        overall_decision=GuardrailDecision.ALLOWED,
        reason_code="allowed",
        message="allowed",
        evidence={},
        requires_human=False,
    )
    executor = Mock()
    executor.execute.side_effect = RuntimeError("downstream unavailable")

    try:
        ExecuteProposalUseCase(
            guardrail_engine=guardrails,
            timeline_service=Mock(),
            audit_service=Mock(),
            proposal_repo=proposal_repo,
            approved_capability_executor=executor,
        ).execute(
            proposal_id=9,
            actor={"user_id": 1, "is_staff": True},
            context={},
        )
    except Exception as exc:
        assert "downstream unavailable" in str(exc)
    else:
        raise AssertionError("Expected proposal execution failure")

    proposal_repo.update_proposal_status.assert_called_once_with(
        9,
        status=ProposalStatus.EXECUTION_FAILED.value,
    )


def test_execute_use_case_supports_a_standalone_persisted_proposal():
    """Execution records preserve the model's optional task relationship."""

    proposal = replace(_approved_proposal(), task_id=None)
    executed_proposal = replace(proposal, status=ProposalStatus.EXECUTED)
    proposal_repo = Mock()
    proposal_repo.get_proposal.return_value = proposal
    proposal_repo.create_guardrail_decision.return_value = {"decision": "allowed"}
    proposal_repo.create_execution_record.return_value = 90
    proposal_repo.update_proposal_status.return_value = executed_proposal
    guardrails = Mock()
    guardrails.check_pre_execution.return_value = SimpleNamespace(
        overall_decision=GuardrailDecision.ALLOWED,
        reason_code="allowed",
        message="allowed",
        evidence={},
        requires_human=False,
    )
    executor = Mock()
    executor.execute.return_value = {"ok": True, "status": "completed"}

    ExecuteProposalUseCase(
        guardrail_engine=guardrails,
        timeline_service=Mock(),
        audit_service=Mock(),
        proposal_repo=proposal_repo,
        approved_capability_executor=executor,
    ).execute(proposal_id=9)

    assert proposal_repo.create_execution_record.call_args.kwargs["task_id"] is None


def test_execute_use_case_rejects_an_unpersisted_proposal_before_writes():
    proposal_repo = Mock()
    proposal_repo.get_proposal.return_value = replace(_approved_proposal(), id=None)

    with pytest.raises(ValueError, match="AgentProposal must be persisted"):
        ExecuteProposalUseCase(
            guardrail_engine=Mock(),
            timeline_service=Mock(),
            audit_service=Mock(),
            proposal_repo=proposal_repo,
            approved_capability_executor=Mock(),
        ).execute(proposal_id=9)

    proposal_repo.create_guardrail_decision.assert_not_called()
    proposal_repo.create_execution_record.assert_not_called()
