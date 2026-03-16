"""
Application Use Cases for Agent Proposals.

WP-M3-01/03/06/07: Proposal lifecycle, execution records,
high-risk action migration, and audit enrichment.
"""

import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from uuid import uuid4

from django.utils import timezone

from apps.agent_runtime.domain.entities import (
    AgentProposal,
    ProposalStatus,
    ApprovalStatus,
    RiskLevel,
    EventSource,
    GuardrailDecision,
    TERMINAL_PROPOSAL_STATUSES,
)
from apps.agent_runtime.domain.guardrails import (
    GuardrailEngine,
    GuardrailCheckOutput,
    HIGH_RISK_PROPOSAL_TYPES,
    get_guardrail_engine,
)
from apps.agent_runtime.application.services import TimelineEventWriterService


logger = logging.getLogger(__name__)


def _generate_proposal_request_id() -> str:
    """Generate a unique request ID for proposals. Format: apr_YYYYMMDD_XXXXXX"""
    date_part = timezone.now().strftime("%Y%m%d")
    random_part = uuid4().hex[:6].upper()
    return f"apr_{date_part}_{random_part}"


# ── Proposal state transitions ──────────────────────────────

_PROPOSAL_TRANSITIONS: Dict[str, List[str]] = {
    ProposalStatus.DRAFT.value: [
        ProposalStatus.GENERATED.value,
        ProposalStatus.EXPIRED.value,
    ],
    ProposalStatus.GENERATED.value: [
        ProposalStatus.SUBMITTED.value,
        ProposalStatus.EXPIRED.value,
    ],
    ProposalStatus.SUBMITTED.value: [
        ProposalStatus.APPROVED.value,
        ProposalStatus.REJECTED.value,
        ProposalStatus.EXPIRED.value,
    ],
    ProposalStatus.APPROVED.value: [
        ProposalStatus.EXECUTED.value,
        ProposalStatus.EXECUTION_FAILED.value,
        ProposalStatus.EXPIRED.value,
    ],
    ProposalStatus.REJECTED.value: [
        ProposalStatus.DRAFT.value,  # retry path
    ],
    ProposalStatus.EXECUTED.value: [],
    ProposalStatus.EXECUTION_FAILED.value: [
        ProposalStatus.APPROVED.value,  # retry execution
    ],
    ProposalStatus.EXPIRED.value: [],
}


class InvalidProposalTransitionError(Exception):
    """Raised when an invalid proposal state transition is attempted."""

    def __init__(
        self,
        current_status: str,
        target_status: str,
        allowed: List[str],
        message: Optional[str] = None,
    ):
        self.current_status = current_status
        self.target_status = target_status
        self.allowed_transitions = allowed
        if message is None:
            message = (
                f"Invalid proposal transition from '{current_status}' to '{target_status}'. "
                f"Allowed: {', '.join(allowed) or 'none'}"
            )
        self.message = message
        super().__init__(message)


def _validate_proposal_transition(current: str, target: str) -> None:
    """Validate and raise on invalid proposal state transition."""
    allowed = _PROPOSAL_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidProposalTransitionError(current, target, allowed)


# ── DTOs ─────────────────────────────────────────────────────

@dataclass
class CreateProposalInput:
    task_id: Optional[int] = None
    proposal_type: str = ""
    risk_level: str = RiskLevel.MEDIUM.value
    approval_required: bool = True
    proposal_payload: Optional[Dict[str, Any]] = None
    approval_reason: Optional[str] = None
    created_by: Optional[int] = None


@dataclass
class CreateProposalOutput:
    proposal: AgentProposal
    request_id: str


@dataclass
class GetProposalOutput:
    proposal: AgentProposal
    request_id: str


@dataclass
class SubmitApprovalOutput:
    proposal: AgentProposal
    request_id: str
    guardrail_decision: Optional[Dict[str, Any]] = None


@dataclass
class ApproveRejectOutput:
    proposal: AgentProposal
    request_id: str


@dataclass
class ExecuteProposalOutput:
    proposal: AgentProposal
    request_id: str
    execution_record_id: Optional[int] = None
    guardrail_decision: Optional[Dict[str, Any]] = None


# ── Use Cases ────────────────────────────────────────────────

class CreateProposalUseCase:
    """Create a new proposal, optionally linked to a task."""

    def __init__(
        self,
        timeline_service: Optional[TimelineEventWriterService] = None,
        audit_service: Optional[Any] = None,
    ):
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.audit_service = audit_service
        if self.audit_service is None:
            try:
                from apps.agent_runtime.application.services.audit_service import get_audit_service
                self.audit_service = get_audit_service()
            except Exception:
                self.audit_service = None

    def execute(self, inp: CreateProposalInput) -> CreateProposalOutput:
        from apps.agent_runtime.infrastructure.models import AgentProposalModel, AgentTaskModel

        request_id = _generate_proposal_request_id()

        # Validate risk_level
        try:
            risk = RiskLevel(inp.risk_level)
        except ValueError:
            raise ValueError(f"Invalid risk_level. Must be one of: {[r.value for r in RiskLevel]}")

        # Auto-detect approval_required for high-risk types
        approval_required = inp.approval_required
        if inp.proposal_type in HIGH_RISK_PROPOSAL_TYPES:
            approval_required = True

        # Validate task exists if task_id given
        if inp.task_id is not None:
            if not AgentTaskModel._default_manager.filter(pk=inp.task_id).exists():
                raise ValueError(f"Task {inp.task_id} not found")

        # Determine initial status
        initial_status = ProposalStatus.GENERATED

        model = AgentProposalModel._default_manager.create(
            request_id=request_id,
            schema_version="v1",
            task_id=inp.task_id,
            proposal_type=inp.proposal_type,
            status=initial_status.value,
            risk_level=risk.value,
            approval_required=approval_required,
            approval_status=ApprovalStatus.PENDING.value if approval_required else ApprovalStatus.NOT_REQUIRED.value,
            proposal_payload=inp.proposal_payload or {},
            approval_reason=inp.approval_reason,
            created_by_id=inp.created_by,
        )

        proposal = model.to_domain_entity()

        # Timeline event on linked task
        if inp.task_id is not None:
            self.timeline_service.write_state_changed_event(
                task=inp.task_id,
                old_status="context_ready",
                new_status="proposal_generated",
                event_source=EventSource.API,
                actor={"user_id": inp.created_by} if inp.created_by else None,
                reason=f"Proposal {request_id} created (type={inp.proposal_type})",
            )

        # Audit
        if self.audit_service:
            try:
                self.audit_service._log_operation(
                    request_id=request_id,
                    user_id=inp.created_by,
                    source="API",
                    operation_type="DATA_MODIFY",
                    module="agent_runtime",
                    action="CREATE",
                    resource_type="agent_proposal",
                    resource_id=str(model.id),
                    request_params={
                        "proposal_type": inp.proposal_type,
                        "risk_level": risk.value,
                        "task_id": inp.task_id,
                    },
                    response_payload={"proposal_id": model.id, "status": initial_status.value},
                    response_status=201,
                    response_message=f"Proposal {model.id} created",
                )
            except Exception as e:
                logger.warning(f"Failed to log audit: {e}")

        return CreateProposalOutput(proposal=proposal, request_id=request_id)


class GetProposalUseCase:
    """Retrieve a single proposal."""

    def execute(self, proposal_id: int) -> GetProposalOutput:
        from apps.agent_runtime.infrastructure.models import AgentProposalModel

        model = AgentProposalModel._default_manager.get(pk=proposal_id)
        return GetProposalOutput(
            proposal=model.to_domain_entity(),
            request_id=model.request_id,
        )


class SubmitProposalForApprovalUseCase:
    """Transition a generated proposal to submitted with pre-approval guardrails."""

    def __init__(
        self,
        guardrail_engine: Optional[GuardrailEngine] = None,
        timeline_service: Optional[TimelineEventWriterService] = None,
    ):
        self.guardrail_engine = guardrail_engine or get_guardrail_engine()
        self.timeline_service = timeline_service or TimelineEventWriterService()

    def execute(
        self,
        proposal_id: int,
        actor: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> SubmitApprovalOutput:
        from apps.agent_runtime.infrastructure.models import (
            AgentProposalModel,
            AgentGuardrailDecisionModel,
        )

        model = AgentProposalModel._default_manager.get(pk=proposal_id)
        proposal = model.to_domain_entity()

        _validate_proposal_transition(proposal.status.value, ProposalStatus.SUBMITTED.value)

        # Run pre-approval guardrails
        check = self.guardrail_engine.check_pre_approval(proposal, actor, context)

        # Persist guardrail decision
        gd_model = AgentGuardrailDecisionModel._default_manager.create(
            request_id=model.request_id,
            task_id=model.task_id,
            proposal_id=model.id,
            decision=check.overall_decision.value,
            reason_code=check.reason_code,
            message=check.message,
            evidence=check.evidence,
            requires_human=check.requires_human,
        )

        guardrail_dict = {
            "id": gd_model.id,
            "decision": check.overall_decision.value,
            "reason_code": check.reason_code,
            "message": check.message,
            "requires_human": check.requires_human,
        }

        if check.overall_decision == GuardrailDecision.BLOCKED:
            raise GuardrailBlockedError(
                decision=check.overall_decision.value,
                reason_code=check.reason_code,
                message=check.message,
                evidence=check.evidence,
            )

        # Transition
        model.status = ProposalStatus.SUBMITTED.value
        model.save(update_fields=["status", "updated_at"])

        proposal = model.to_domain_entity()

        # Timeline event
        if model.task_id:
            self.timeline_service.write_state_changed_event(
                task=model.task_id,
                old_status="proposal_generated",
                new_status="awaiting_approval",
                event_source=EventSource.API,
                actor=actor,
                reason=f"Proposal {model.request_id} submitted for approval",
            )

        return SubmitApprovalOutput(
            proposal=proposal,
            request_id=model.request_id,
            guardrail_decision=guardrail_dict,
        )


class ApproveProposalUseCase:
    """Approve a submitted proposal."""

    def __init__(
        self,
        timeline_service: Optional[TimelineEventWriterService] = None,
    ):
        self.timeline_service = timeline_service or TimelineEventWriterService()

    def execute(
        self,
        proposal_id: int,
        reason: Optional[str] = None,
        actor: Optional[Dict[str, Any]] = None,
    ) -> ApproveRejectOutput:
        from apps.agent_runtime.infrastructure.models import AgentProposalModel

        model = AgentProposalModel._default_manager.get(pk=proposal_id)
        proposal = model.to_domain_entity()

        _validate_proposal_transition(proposal.status.value, ProposalStatus.APPROVED.value)

        model.status = ProposalStatus.APPROVED.value
        model.approval_status = ApprovalStatus.APPROVED.value
        model.approval_reason = reason or "Approved"
        model.save(update_fields=["status", "approval_status", "approval_reason", "updated_at"])

        proposal = model.to_domain_entity()

        if model.task_id:
            self.timeline_service.write_state_changed_event(
                task=model.task_id,
                old_status="awaiting_approval",
                new_status="approved",
                event_source=EventSource.HUMAN,
                actor=actor,
                reason=reason or "Approved",
            )

        return ApproveRejectOutput(proposal=proposal, request_id=model.request_id)


class RejectProposalUseCase:
    """Reject a submitted proposal."""

    def __init__(
        self,
        timeline_service: Optional[TimelineEventWriterService] = None,
    ):
        self.timeline_service = timeline_service or TimelineEventWriterService()

    def execute(
        self,
        proposal_id: int,
        reason: Optional[str] = None,
        actor: Optional[Dict[str, Any]] = None,
    ) -> ApproveRejectOutput:
        from apps.agent_runtime.infrastructure.models import AgentProposalModel

        model = AgentProposalModel._default_manager.get(pk=proposal_id)
        proposal = model.to_domain_entity()

        _validate_proposal_transition(proposal.status.value, ProposalStatus.REJECTED.value)

        model.status = ProposalStatus.REJECTED.value
        model.approval_status = ApprovalStatus.REJECTED.value
        model.approval_reason = reason or "Rejected"
        model.save(update_fields=["status", "approval_status", "approval_reason", "updated_at"])

        proposal = model.to_domain_entity()

        if model.task_id:
            self.timeline_service.write_state_changed_event(
                task=model.task_id,
                old_status="awaiting_approval",
                new_status="rejected",
                event_source=EventSource.HUMAN,
                actor=actor,
                reason=reason or "Rejected",
            )

        return ApproveRejectOutput(proposal=proposal, request_id=model.request_id)


class ExecuteProposalUseCase:
    """
    Execute an approved proposal with pre-execution guardrails.

    WP-M3-03: Creates execution records and timeline events.
    """

    def __init__(
        self,
        guardrail_engine: Optional[GuardrailEngine] = None,
        timeline_service: Optional[TimelineEventWriterService] = None,
        audit_service: Optional[Any] = None,
    ):
        self.guardrail_engine = guardrail_engine or get_guardrail_engine()
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.audit_service = audit_service
        if self.audit_service is None:
            try:
                from apps.agent_runtime.application.services.audit_service import get_audit_service
                self.audit_service = get_audit_service()
            except Exception:
                self.audit_service = None

    def execute(
        self,
        proposal_id: int,
        actor: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecuteProposalOutput:
        from apps.agent_runtime.infrastructure.models import (
            AgentProposalModel,
            AgentExecutionRecordModel,
            AgentGuardrailDecisionModel,
        )

        model = AgentProposalModel._default_manager.get(pk=proposal_id)
        proposal = model.to_domain_entity()

        _validate_proposal_transition(proposal.status.value, ProposalStatus.EXECUTED.value)

        # Pre-execution guardrails
        check = self.guardrail_engine.check_pre_execution(proposal, actor, context)

        # Persist guardrail decision
        gd_model = AgentGuardrailDecisionModel._default_manager.create(
            request_id=model.request_id,
            task_id=model.task_id,
            proposal_id=model.id,
            decision=check.overall_decision.value,
            reason_code=check.reason_code,
            message=check.message,
            evidence=check.evidence,
            requires_human=check.requires_human,
        )

        guardrail_dict = {
            "id": gd_model.id,
            "decision": check.overall_decision.value,
            "reason_code": check.reason_code,
            "message": check.message,
            "requires_human": check.requires_human,
        }

        if check.overall_decision == GuardrailDecision.BLOCKED:
            raise GuardrailBlockedError(
                decision=check.overall_decision.value,
                reason_code=check.reason_code,
                message=check.message,
                evidence=check.evidence,
            )

        # Create execution record
        exec_started = timezone.now()
        exec_record = AgentExecutionRecordModel._default_manager.create(
            request_id=model.request_id,
            task_id=model.task_id or 0,
            proposal_id=model.id,
            execution_status="success",
            execution_output={
                "proposal_type": model.proposal_type,
                "payload": model.proposal_payload,
                "guardrail_decision": check.overall_decision.value,
            },
            started_at=exec_started,
            completed_at=timezone.now(),
        )

        # Transition proposal
        model.status = ProposalStatus.EXECUTED.value
        model.save(update_fields=["status", "updated_at"])
        proposal = model.to_domain_entity()

        # Timeline events
        if model.task_id:
            self.timeline_service.write_state_changed_event(
                task=model.task_id,
                old_status="approved",
                new_status="executing",
                event_source=EventSource.SYSTEM,
                actor=actor,
                reason=f"Executing proposal {model.request_id}",
            )
            self.timeline_service.write_step_completed_event(
                task=model.task_id,
                step_key="proposal_execution",
                event_source=EventSource.SYSTEM,
                output={
                    "execution_record_id": exec_record.id,
                    "execution_status": "success",
                },
            )

        # Audit enrichment (WP-M3-07)
        if self.audit_service:
            try:
                self.audit_service._log_operation(
                    request_id=model.request_id,
                    user_id=actor.get("user_id") if actor else None,
                    source="API",
                    operation_type="DATA_MODIFY",
                    module="agent_runtime",
                    action="UPDATE",
                    resource_type="agent_proposal",
                    resource_id=str(model.id),
                    request_params={
                        "proposal_id": model.id,
                        "task_id": model.task_id,
                        "guardrail_decision": check.overall_decision.value,
                        "approval_actor": actor,
                        "execution_result": "success",
                    },
                    response_payload={
                        "proposal_id": model.id,
                        "execution_record_id": exec_record.id,
                        "status": "executed",
                    },
                    response_status=200,
                    response_message=f"Proposal {model.id} executed successfully",
                )
            except Exception as e:
                logger.warning(f"Failed to log audit: {e}")

        return ExecuteProposalOutput(
            proposal=proposal,
            request_id=model.request_id,
            execution_record_id=exec_record.id,
            guardrail_decision=guardrail_dict,
        )


class GuardrailBlockedError(Exception):
    """Raised when a guardrail blocks an action."""

    def __init__(
        self,
        decision: str,
        reason_code: str,
        message: str,
        evidence: Optional[Dict[str, Any]] = None,
    ):
        self.decision = decision
        self.reason_code = reason_code
        self.guardrail_message = message
        self.evidence = evidence or {}
        super().__init__(message)
