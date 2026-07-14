"""Tests for durable Terminal MCP approval and execution."""

import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

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


@patch(
    "apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool"
)
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
                    "mcp_role": "",
                    "client_id": "terminal_approval",
                },
            },
        ),
        call(
            "agom_confirmation_resume",
            {"confirmation_token": "confirm-1", "approve": True},
        ),
    ]


@patch(
    "apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool"
)
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


@patch(
    "apps.agent_runtime.infrastructure.mcp_proposal_executor.call_sdk_mcp_tool"
)
def test_approved_executor_uses_staff_role_only_during_mcp_execution(mock_call):
    """The trusted approval actor role is scoped to the guarded MCP call."""

    observed_roles = []

    def _call(_tool_name, _params):
        observed_roles.append(os.environ.get("AGOMTRADEPRO_MCP_ROLE"))
        return {"ok": True, "status": "completed", "result": {}}

    mock_call.side_effect = _call
    previous = os.environ.pop("AGOMTRADEPRO_MCP_ROLE", None)
    try:
        ApprovedMcpCapabilityExecutor().execute(
            proposal=_approved_proposal(),
            actor={"user_id": 1, "is_staff": True},
            context={},
        )

        assert observed_roles == ["admin"]
        assert "AGOMTRADEPRO_MCP_ROLE" not in os.environ
    finally:
        if previous is not None:
            os.environ["AGOMTRADEPRO_MCP_ROLE"] = previous


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
    execution_output = proposal_repo.create_execution_record.call_args.kwargs[
        "execution_output"
    ]
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
