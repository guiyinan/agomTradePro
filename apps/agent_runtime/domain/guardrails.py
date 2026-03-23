"""
Domain Guardrail Engine for Agent Runtime.

WP-M3-02: Guardrail checks before approval and execution.

Guardrail gates:
- role_gate: checks requester has permission for proposal_type
- risk_level_gate: blocks critical-risk without explicit approval
- approval_required_gate: ensures approval workflow was followed
- market_readiness_gate: checks market hours / regime status
- data_freshness_gate: checks upstream data freshness
- dependency_health_gate: checks dependent service health
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from apps.agent_runtime.domain.entities import (
    AgentProposal,
    GuardrailDecision,
    ProposalStatus,
    RiskLevel,
)


@dataclass(frozen=True)
class GuardrailResult:
    """Result of a single guardrail check."""

    gate_name: str
    decision: GuardrailDecision
    reason_code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    requires_human: bool = False


@dataclass(frozen=True)
class GuardrailCheckOutput:
    """Aggregate result of all guardrail checks."""

    overall_decision: GuardrailDecision
    reason_code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    requires_human: bool = False
    gate_results: list[GuardrailResult] = field(default_factory=list)


# Proposal types that always require human approval
HIGH_RISK_PROPOSAL_TYPES = frozenset({
    "signal_create",
    "signal_update",
    "signal_invalidate",
    "strategy_bind",
    "strategy_unbind",
    "trade_execute",
    "policy_event_create",
    "config_write",
})


class GuardrailEngine:
    """
    Guardrail engine that runs a pipeline of checks.

    Each gate returns a GuardrailResult. The engine aggregates
    them into a single GuardrailCheckOutput. Any BLOCKED gate
    blocks the overall decision; any NEEDS_HUMAN gate escalates.
    """

    def check_pre_approval(
        self,
        proposal: AgentProposal,
        actor: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> GuardrailCheckOutput:
        """
        Run guardrail checks before submitting for approval.

        Args:
            proposal: The proposal to check
            actor: Actor information (user_id, roles, etc.)
            context: Additional context (market state, data freshness)

        Returns:
            Aggregate guardrail decision
        """
        ctx = context or {}
        results: list[GuardrailResult] = [
            self._role_gate(proposal, actor),
            self._risk_level_gate(proposal),
            self._data_freshness_gate(proposal, ctx),
            self._dependency_health_gate(proposal, ctx),
        ]
        return self._aggregate(results)

    def check_pre_execution(
        self,
        proposal: AgentProposal,
        actor: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> GuardrailCheckOutput:
        """
        Run guardrail checks before executing an approved proposal.

        Args:
            proposal: The proposal to execute
            actor: Actor information
            context: Additional context

        Returns:
            Aggregate guardrail decision
        """
        ctx = context or {}
        results: list[GuardrailResult] = [
            self._role_gate(proposal, actor),
            self._approval_required_gate(proposal),
            self._risk_level_gate(proposal),
            self._market_readiness_gate(proposal, ctx),
            self._data_freshness_gate(proposal, ctx),
            self._dependency_health_gate(proposal, ctx),
        ]
        return self._aggregate(results)

    # ── Gates ─────────────────────────────────────────────────

    def _role_gate(
        self,
        proposal: AgentProposal,
        actor: dict[str, Any] | None,
    ) -> GuardrailResult:
        """Check that the actor has permission for this proposal type."""
        if actor is None:
            return GuardrailResult(
                gate_name="role_gate",
                decision=GuardrailDecision.NEEDS_HUMAN,
                reason_code="no_actor",
                message="No actor information provided; human review required",
                requires_human=True,
            )

        # Staff users pass
        if actor.get("is_staff"):
            return GuardrailResult(
                gate_name="role_gate",
                decision=GuardrailDecision.ALLOWED,
                reason_code="staff_user",
                message="Staff user has full access",
                evidence={"user_id": actor.get("user_id")},
            )

        # For high-risk types, require explicit operator/admin role.
        # Accept both legacy and current group names to avoid RBAC drift.
        if proposal.proposal_type in HIGH_RISK_PROPOSAL_TYPES:
            allowed_roles = actor.get("roles", [])
            permitted_roles = {"agent_operator", "operator", "admin"}
            if not permitted_roles.intersection(allowed_roles):
                return GuardrailResult(
                    gate_name="role_gate",
                    decision=GuardrailDecision.NEEDS_HUMAN,
                    reason_code="insufficient_role",
                    message=f"Proposal type '{proposal.proposal_type}' requires operator or admin role",
                    evidence={"proposal_type": proposal.proposal_type, "user_roles": allowed_roles},
                    requires_human=True,
                )

        return GuardrailResult(
            gate_name="role_gate",
            decision=GuardrailDecision.ALLOWED,
            reason_code="role_ok",
            message="Actor role is sufficient",
        )

    def _risk_level_gate(self, proposal: AgentProposal) -> GuardrailResult:
        """Block critical-risk proposals without explicit approval."""
        if proposal.risk_level == RiskLevel.CRITICAL:
            return GuardrailResult(
                gate_name="risk_level_gate",
                decision=GuardrailDecision.NEEDS_HUMAN,
                reason_code="critical_risk",
                message="Critical-risk proposal requires explicit human approval",
                evidence={"risk_level": proposal.risk_level.value},
                requires_human=True,
            )

        if proposal.risk_level == RiskLevel.HIGH:
            return GuardrailResult(
                gate_name="risk_level_gate",
                decision=GuardrailDecision.ALLOWED,
                reason_code="high_risk_noted",
                message="High-risk proposal noted; approval workflow will enforce review",
                evidence={"risk_level": proposal.risk_level.value},
            )

        return GuardrailResult(
            gate_name="risk_level_gate",
            decision=GuardrailDecision.ALLOWED,
            reason_code="risk_ok",
            message="Risk level acceptable",
            evidence={"risk_level": proposal.risk_level.value},
        )

    def _approval_required_gate(self, proposal: AgentProposal) -> GuardrailResult:
        """Ensure approval workflow was followed before execution."""
        if proposal.approval_required and proposal.status != ProposalStatus.APPROVED:
            return GuardrailResult(
                gate_name="approval_required_gate",
                decision=GuardrailDecision.BLOCKED,
                reason_code="approval_not_granted",
                message="Proposal requires approval before execution",
                evidence={
                    "approval_required": True,
                    "current_status": proposal.status.value,
                },
            )

        return GuardrailResult(
            gate_name="approval_required_gate",
            decision=GuardrailDecision.ALLOWED,
            reason_code="approval_ok",
            message="Approval requirement satisfied",
        )

    def _market_readiness_gate(
        self,
        proposal: AgentProposal,
        context: dict[str, Any],
    ) -> GuardrailResult:
        """Check market readiness from context."""
        market_open = context.get("market_open", True)
        if not market_open and proposal.proposal_type in (
            "trade_execute",
            "strategy_bind",
        ):
            return GuardrailResult(
                gate_name="market_readiness_gate",
                decision=GuardrailDecision.BLOCKED,
                reason_code="market_closed",
                message="Market is closed; trade-related proposals are blocked",
                evidence={"market_open": False, "proposal_type": proposal.proposal_type},
            )

        return GuardrailResult(
            gate_name="market_readiness_gate",
            decision=GuardrailDecision.ALLOWED,
            reason_code="market_ok",
            message="Market readiness check passed",
        )

    def _data_freshness_gate(
        self,
        proposal: AgentProposal,
        context: dict[str, Any],
    ) -> GuardrailResult:
        """Check upstream data freshness."""
        stale_sources = context.get("stale_data_sources", [])
        if stale_sources:
            return GuardrailResult(
                gate_name="data_freshness_gate",
                decision=GuardrailDecision.DEGRADED_MODE,
                reason_code="stale_data",
                message=f"Stale data sources detected: {', '.join(stale_sources)}",
                evidence={"stale_sources": stale_sources},
            )

        return GuardrailResult(
            gate_name="data_freshness_gate",
            decision=GuardrailDecision.ALLOWED,
            reason_code="data_fresh",
            message="All data sources are fresh",
        )

    def _dependency_health_gate(
        self,
        proposal: AgentProposal,
        context: dict[str, Any],
    ) -> GuardrailResult:
        """Check dependent service health."""
        unhealthy_deps = context.get("unhealthy_dependencies", [])
        if unhealthy_deps:
            return GuardrailResult(
                gate_name="dependency_health_gate",
                decision=GuardrailDecision.BLOCKED,
                reason_code="dependency_unhealthy",
                message=f"Unhealthy dependencies: {', '.join(unhealthy_deps)}",
                evidence={"unhealthy_dependencies": unhealthy_deps},
            )

        return GuardrailResult(
            gate_name="dependency_health_gate",
            decision=GuardrailDecision.ALLOWED,
            reason_code="deps_ok",
            message="All dependencies are healthy",
        )

    # ── Aggregation ───────────────────────────────────────────

    def _aggregate(self, results: list[GuardrailResult]) -> GuardrailCheckOutput:
        """Aggregate gate results into a single decision."""
        blocked = [r for r in results if r.decision == GuardrailDecision.BLOCKED]
        needs_human = [r for r in results if r.decision == GuardrailDecision.NEEDS_HUMAN]
        degraded = [r for r in results if r.decision == GuardrailDecision.DEGRADED_MODE]

        if blocked:
            first = blocked[0]
            return GuardrailCheckOutput(
                overall_decision=GuardrailDecision.BLOCKED,
                reason_code=first.reason_code,
                message=first.message,
                evidence={"blocked_gates": [r.gate_name for r in blocked]},
                requires_human=False,
                gate_results=results,
            )

        if needs_human:
            first = needs_human[0]
            return GuardrailCheckOutput(
                overall_decision=GuardrailDecision.NEEDS_HUMAN,
                reason_code=first.reason_code,
                message=first.message,
                evidence={"escalated_gates": [r.gate_name for r in needs_human]},
                requires_human=True,
                gate_results=results,
            )

        if degraded:
            first = degraded[0]
            return GuardrailCheckOutput(
                overall_decision=GuardrailDecision.DEGRADED_MODE,
                reason_code=first.reason_code,
                message=first.message,
                evidence={"degraded_gates": [r.gate_name for r in degraded]},
                requires_human=False,
                gate_results=results,
            )

        return GuardrailCheckOutput(
            overall_decision=GuardrailDecision.ALLOWED,
            reason_code="all_gates_passed",
            message="All guardrail checks passed",
            gate_results=results,
        )


# Singleton
_guardrail_engine: GuardrailEngine | None = None


def get_guardrail_engine() -> GuardrailEngine:
    """Get the singleton GuardrailEngine instance."""
    global _guardrail_engine
    if _guardrail_engine is None:
        _guardrail_engine = GuardrailEngine()
    return _guardrail_engine
