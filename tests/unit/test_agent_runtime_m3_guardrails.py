"""
Unit Tests for M3: Guardrail Engine and Proposal Use Cases.

Tests:
- Guardrail gate decisions (allow/block/needs_human/degraded)
- Proposal state transitions (valid and invalid)
- Execution record creation
- Audit payload enrichment
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from apps.agent_runtime.application.proposal_use_cases import (
    InvalidProposalTransitionError,
    _validate_proposal_transition,
)
from apps.agent_runtime.domain.entities import (
    AgentProposal,
    ApprovalStatus,
    GuardrailDecision,
    ProposalStatus,
    RiskLevel,
)
from apps.agent_runtime.domain.guardrails import (
    HIGH_RISK_PROPOSAL_TYPES,
    GuardrailEngine,
    GuardrailResult,
)


def _make_proposal(
    status: ProposalStatus = ProposalStatus.GENERATED,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    proposal_type: str = "signal_create",
    approval_required: bool = True,
) -> AgentProposal:
    """Helper to construct a test proposal."""
    return AgentProposal(
        id=1,
        request_id="apr_20260316_TEST01",
        task_id=10,
        proposal_type=proposal_type,
        status=status,
        risk_level=risk_level,
        approval_required=approval_required,
        approval_status=ApprovalStatus.PENDING,
        proposal_payload={"asset_code": "000001.SH"},
    )


# ── Guardrail Engine Tests ───────────────────────────────────


class TestRoleGate:
    """Test role_gate guardrail."""

    def setup_method(self):
        self.engine = GuardrailEngine()
        self.proposal = _make_proposal()

    def test_no_actor_needs_human(self):
        result = self.engine._role_gate(self.proposal, actor=None)
        assert result.decision == GuardrailDecision.NEEDS_HUMAN
        assert result.reason_code == "no_actor"

    def test_staff_user_allowed(self):
        actor = {"user_id": 1, "is_staff": True}
        result = self.engine._role_gate(self.proposal, actor)
        assert result.decision == GuardrailDecision.ALLOWED
        assert result.reason_code == "staff_user"

    def test_high_risk_type_insufficient_role(self):
        actor = {"user_id": 1, "is_staff": False, "roles": ["viewer"]}
        result = self.engine._role_gate(self.proposal, actor)
        assert result.decision == GuardrailDecision.NEEDS_HUMAN
        assert result.reason_code == "insufficient_role"

    def test_high_risk_type_with_operator_role(self):
        actor = {"user_id": 1, "is_staff": False, "roles": ["agent_operator"]}
        result = self.engine._role_gate(self.proposal, actor)
        assert result.decision == GuardrailDecision.ALLOWED

    def test_high_risk_type_with_operator_group_role(self):
        actor = {"user_id": 1, "is_staff": False, "roles": ["operator"]}
        result = self.engine._role_gate(self.proposal, actor)
        assert result.decision == GuardrailDecision.ALLOWED

    def test_non_high_risk_type_any_role(self):
        proposal = _make_proposal(proposal_type="custom_report")
        actor = {"user_id": 1, "is_staff": False, "roles": ["viewer"]}
        result = self.engine._role_gate(proposal, actor)
        assert result.decision == GuardrailDecision.ALLOWED


class TestRiskLevelGate:
    """Test risk_level_gate guardrail."""

    def setup_method(self):
        self.engine = GuardrailEngine()

    def test_critical_risk_needs_human(self):
        proposal = _make_proposal(risk_level=RiskLevel.CRITICAL)
        result = self.engine._risk_level_gate(proposal)
        assert result.decision == GuardrailDecision.NEEDS_HUMAN
        assert result.requires_human is True

    def test_high_risk_allowed(self):
        proposal = _make_proposal(risk_level=RiskLevel.HIGH)
        result = self.engine._risk_level_gate(proposal)
        assert result.decision == GuardrailDecision.ALLOWED
        assert result.reason_code == "high_risk_noted"

    def test_medium_risk_ok(self):
        proposal = _make_proposal(risk_level=RiskLevel.MEDIUM)
        result = self.engine._risk_level_gate(proposal)
        assert result.decision == GuardrailDecision.ALLOWED
        assert result.reason_code == "risk_ok"

    def test_low_risk_ok(self):
        proposal = _make_proposal(risk_level=RiskLevel.LOW)
        result = self.engine._risk_level_gate(proposal)
        assert result.decision == GuardrailDecision.ALLOWED


class TestApprovalRequiredGate:
    """Test approval_required_gate guardrail."""

    def setup_method(self):
        self.engine = GuardrailEngine()

    def test_approval_required_but_not_approved(self):
        proposal = _make_proposal(
            status=ProposalStatus.SUBMITTED,
            approval_required=True,
        )
        result = self.engine._approval_required_gate(proposal)
        assert result.decision == GuardrailDecision.BLOCKED
        assert result.reason_code == "approval_not_granted"

    def test_approval_required_and_approved(self):
        proposal = _make_proposal(
            status=ProposalStatus.APPROVED,
            approval_required=True,
        )
        result = self.engine._approval_required_gate(proposal)
        assert result.decision == GuardrailDecision.ALLOWED

    def test_approval_not_required(self):
        proposal = _make_proposal(
            status=ProposalStatus.GENERATED,
            approval_required=False,
        )
        result = self.engine._approval_required_gate(proposal)
        assert result.decision == GuardrailDecision.ALLOWED


class TestMarketReadinessGate:
    """Test market_readiness_gate guardrail."""

    def setup_method(self):
        self.engine = GuardrailEngine()

    def test_market_closed_blocks_trade(self):
        proposal = _make_proposal(proposal_type="trade_execute")
        result = self.engine._market_readiness_gate(proposal, {"market_open": False})
        assert result.decision == GuardrailDecision.BLOCKED

    def test_market_open_ok(self):
        proposal = _make_proposal(proposal_type="trade_execute")
        result = self.engine._market_readiness_gate(proposal, {"market_open": True})
        assert result.decision == GuardrailDecision.ALLOWED

    def test_market_closed_non_trade_ok(self):
        proposal = _make_proposal(proposal_type="custom_report")
        result = self.engine._market_readiness_gate(proposal, {"market_open": False})
        assert result.decision == GuardrailDecision.ALLOWED


class TestDataFreshnessGate:
    """Test data_freshness_gate guardrail."""

    def setup_method(self):
        self.engine = GuardrailEngine()

    def test_stale_data_degrades(self):
        proposal = _make_proposal()
        result = self.engine._data_freshness_gate(
            proposal, {"stale_data_sources": ["macro", "sentiment"]}
        )
        assert result.decision == GuardrailDecision.DEGRADED_MODE

    def test_fresh_data_ok(self):
        proposal = _make_proposal()
        result = self.engine._data_freshness_gate(proposal, {})
        assert result.decision == GuardrailDecision.ALLOWED


class TestDependencyHealthGate:
    """Test dependency_health_gate guardrail."""

    def setup_method(self):
        self.engine = GuardrailEngine()

    def test_unhealthy_deps_blocked(self):
        proposal = _make_proposal()
        result = self.engine._dependency_health_gate(
            proposal, {"unhealthy_dependencies": ["regime_api"]}
        )
        assert result.decision == GuardrailDecision.BLOCKED

    def test_healthy_deps_ok(self):
        proposal = _make_proposal()
        result = self.engine._dependency_health_gate(proposal, {})
        assert result.decision == GuardrailDecision.ALLOWED


class TestAggregation:
    """Test guardrail result aggregation."""

    def setup_method(self):
        self.engine = GuardrailEngine()

    def test_all_allowed(self):
        proposal = _make_proposal(proposal_type="custom_report", risk_level=RiskLevel.LOW)
        actor = {"user_id": 1, "is_staff": True}
        result = self.engine.check_pre_approval(proposal, actor, {})
        assert result.overall_decision == GuardrailDecision.ALLOWED

    def test_blocked_takes_priority(self):
        proposal = _make_proposal()
        actor = {"user_id": 1, "is_staff": True}
        result = self.engine.check_pre_approval(
            proposal, actor, {"unhealthy_dependencies": ["regime_api"]}
        )
        assert result.overall_decision == GuardrailDecision.BLOCKED

    def test_needs_human_if_no_block(self):
        proposal = _make_proposal(risk_level=RiskLevel.CRITICAL)
        actor = {"user_id": 1, "is_staff": True}
        result = self.engine.check_pre_approval(proposal, actor, {})
        assert result.overall_decision == GuardrailDecision.NEEDS_HUMAN

    def test_degraded_if_no_block_or_human(self):
        proposal = _make_proposal(proposal_type="custom_report", risk_level=RiskLevel.LOW)
        actor = {"user_id": 1, "is_staff": True}
        result = self.engine.check_pre_approval(
            proposal, actor, {"stale_data_sources": ["macro"]}
        )
        assert result.overall_decision == GuardrailDecision.DEGRADED_MODE


class TestPreExecutionGuardrails:
    """Test pre-execution guardrail pipeline."""

    def setup_method(self):
        self.engine = GuardrailEngine()

    def test_approved_proposal_passes(self):
        proposal = _make_proposal(
            status=ProposalStatus.APPROVED,
            risk_level=RiskLevel.MEDIUM,
            proposal_type="custom_report",
            approval_required=True,
        )
        actor = {"user_id": 1, "is_staff": True}
        result = self.engine.check_pre_execution(proposal, actor, {})
        assert result.overall_decision == GuardrailDecision.ALLOWED

    def test_operator_role_passes_high_risk_pre_execution(self):
        proposal = _make_proposal(
            status=ProposalStatus.APPROVED,
            risk_level=RiskLevel.MEDIUM,
            proposal_type="signal_create",
            approval_required=True,
        )
        actor = {"user_id": 1, "is_staff": False, "roles": ["operator"]}
        result = self.engine.check_pre_execution(proposal, actor, {})
        assert result.overall_decision == GuardrailDecision.ALLOWED

    def test_unapproved_blocks_execution(self):
        proposal = _make_proposal(
            status=ProposalStatus.SUBMITTED,
            approval_required=True,
        )
        result = self.engine.check_pre_execution(proposal)
        assert result.overall_decision == GuardrailDecision.BLOCKED
        assert result.reason_code == "approval_not_granted"


# ── Proposal State Transition Tests ──────────────────────────


class TestProposalTransitions:
    """Test proposal state transition validation."""

    def test_generated_to_submitted(self):
        _validate_proposal_transition("generated", "submitted")  # no exception

    def test_submitted_to_approved(self):
        _validate_proposal_transition("submitted", "approved")

    def test_submitted_to_rejected(self):
        _validate_proposal_transition("submitted", "rejected")

    def test_approved_to_executed(self):
        _validate_proposal_transition("approved", "executed")

    def test_approved_to_execution_failed(self):
        _validate_proposal_transition("approved", "execution_failed")

    def test_rejected_to_draft_retry(self):
        _validate_proposal_transition("rejected", "draft")

    def test_execution_failed_to_approved_retry(self):
        _validate_proposal_transition("execution_failed", "approved")

    def test_draft_to_approved_invalid(self):
        with pytest.raises(InvalidProposalTransitionError) as exc_info:
            _validate_proposal_transition("draft", "approved")
        assert exc_info.value.current_status == "draft"
        assert exc_info.value.target_status == "approved"

    def test_executed_is_terminal(self):
        with pytest.raises(InvalidProposalTransitionError):
            _validate_proposal_transition("executed", "draft")

    def test_expired_is_terminal(self):
        with pytest.raises(InvalidProposalTransitionError):
            _validate_proposal_transition("expired", "draft")

    def test_generated_to_approved_invalid(self):
        with pytest.raises(InvalidProposalTransitionError):
            _validate_proposal_transition("generated", "approved")


# ── High-Risk Proposal Types ─────────────────────────────────


class TestHighRiskTypes:
    """Test high-risk proposal type registry."""

    def test_signal_create_is_high_risk(self):
        assert "signal_create" in HIGH_RISK_PROPOSAL_TYPES

    def test_trade_execute_is_high_risk(self):
        assert "trade_execute" in HIGH_RISK_PROPOSAL_TYPES

    def test_strategy_bind_is_high_risk(self):
        assert "strategy_bind" in HIGH_RISK_PROPOSAL_TYPES

    def test_config_write_is_high_risk(self):
        assert "config_write" in HIGH_RISK_PROPOSAL_TYPES

    def test_custom_report_not_high_risk(self):
        assert "custom_report" not in HIGH_RISK_PROPOSAL_TYPES
