"""Bridge Risk retirement facts to the canonical Audit application capability."""

from __future__ import annotations

from uuid import UUID

from apps.audit.application.execution_rule_retirement_audit import (
    AppendExecutionRuleRetirementAuditUseCase,
    ExecutionRuleRetirementAuditConflict,
    ExecutionRuleRetirementAuditCorruption,
    ExecutionRuleRetirementAuditObservation,
    ExecutionRuleRetirementAuditUnavailable,
    build_execution_rule_retirement_audit_event,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.risk_center.application.ashare_execution_rule_lifecycle import (
    AShareExecutionRuleRetirementAuditReceipt,
    ExecutionRuleRetirementConflict,
    ExecutionRuleRetirementCorruption,
    ExecutionRuleRetirementUnavailable,
)
from apps.risk_center.domain.ashare_execution_rule_retirement import (
    AShareExecutionRuleRetirementAuthorization,
    AShareExecutionRuleRetirementEvidence,
    AShareExecutionRuleRetirementIntent,
)


class CoreRiskExecutionRuleRetirementAuditBridge:
    """Adapt Risk-owned lifecycle inputs to the exact canonical Audit writer."""

    def __init__(self, audit: AppendExecutionRuleRetirementAuditUseCase) -> None:
        """Require an explicitly composed Audit application capability."""

        if audit is None:
            raise ValueError("execution-rule retirement Audit capability is required")
        self._audit = audit

    @property
    def database_alias(self) -> str:
        """Return the alias used by the underlying Audit transaction coordinator."""

        alias = self._audit.database_alias
        if type(alias) is not str or not alias:
            raise ExecutionRuleRetirementUnavailable("Audit returned an invalid database alias")
        return alias

    def execute_retirement_in_caller_transaction(
        self,
        *,
        intent: AShareExecutionRuleRetirementIntent,
        authorization: AShareExecutionRuleRetirementAuthorization,
        evidence: AShareExecutionRuleRetirementEvidence,
        exact_replay: bool,
    ) -> AShareExecutionRuleRetirementAuditReceipt:
        """Write or verify the exact event/outbox pair and return a Risk receipt."""

        observation = _build_observation(
            intent=intent,
            authorization=authorization,
            evidence=evidence,
        )
        if type(exact_replay) is not bool:
            raise ExecutionRuleRetirementCorruption("replay selector must be boolean")
        try:
            commit = self._audit.execute_in_caller_transaction(
                observation,
                exact_replay=exact_replay,
            )
        except ExecutionRuleRetirementAuditConflict as error:
            raise ExecutionRuleRetirementConflict(str(error)) from error
        except ExecutionRuleRetirementAuditCorruption as error:
            raise ExecutionRuleRetirementCorruption(str(error)) from error
        except ExecutionRuleRetirementAuditUnavailable as error:
            raise ExecutionRuleRetirementUnavailable(str(error)) from error
        event = _validate_commit(commit=commit, observation=observation)
        assert evidence.retirement_request_id is not None
        assert evidence.retirement_request_hash is not None
        return AShareExecutionRuleRetirementAuditReceipt(
            request_id=evidence.retirement_request_id,
            request_hash=evidence.retirement_request_hash,
            event_content_hash=event.content_hash,
            outbox_id=commit.outbox_id,
        )


def _build_observation(
    *,
    intent: AShareExecutionRuleRetirementIntent,
    authorization: AShareExecutionRuleRetirementAuthorization,
    evidence: AShareExecutionRuleRetirementEvidence,
) -> ExecutionRuleRetirementAuditObservation:
    """Bind typed Risk facts into the Audit-owned canonical observation."""

    if (
        type(intent) is not AShareExecutionRuleRetirementIntent
        or type(authorization) is not AShareExecutionRuleRetirementAuthorization
        or type(evidence) is not AShareExecutionRuleRetirementEvidence
    ):
        raise ExecutionRuleRetirementCorruption("Risk supplied an invalid retirement value")
    try:
        AShareExecutionRuleRetirementIntent.__post_init__(intent)
        AShareExecutionRuleRetirementAuthorization.__post_init__(authorization)
        AShareExecutionRuleRetirementEvidence.__post_init__(evidence)
    except (TypeError, ValueError) as error:
        raise ExecutionRuleRetirementCorruption(
            "Risk retirement values failed validation"
        ) from error
    if (
        evidence.is_empty
        or evidence.retirement_effective_at != intent.effective_at
        or evidence.retirement_request_id != intent.request_id
        or evidence.retirement_actor_type != authorization.actor_type
        or evidence.retirement_actor_id != authorization.actor_id
        or evidence.retirement_recorded_at is None
        or evidence.retirement_request_hash is None
    ):
        raise ExecutionRuleRetirementCorruption(
            "Risk retirement evidence does not bind its intent and authorized actor"
        )
    try:
        return ExecutionRuleRetirementAuditObservation(
            security_id=intent.security_id,
            rule_id=intent.rule_id,
            rule_version=intent.rule_version,
            content_hash=intent.expected_content_hash,
            request_id=intent.request_id,
            request_hash=evidence.retirement_request_hash,
            reason_code=intent.reason_code,
            effective_at=intent.effective_at,
            recorded_at=evidence.retirement_recorded_at,
            actor_type=authorization.actor_type,
            actor_id=authorization.actor_id,
            scope_tenant_id=authorization.scope_tenant_id,
            scope_owner_id=authorization.scope_owner_id,
        )
    except (TypeError, ValueError) as error:
        raise ExecutionRuleRetirementCorruption(
            "Risk retirement facts cannot form a canonical Audit observation"
        ) from error


def _validate_commit(
    *,
    commit: SystemAuditEventOutboxCommit,
    observation: ExecutionRuleRetirementAuditObservation,
) -> SystemAuditEvent:
    """Rebuild and compare the complete canonical event and commit identity."""

    if type(commit) is not SystemAuditEventOutboxCommit:
        raise ExecutionRuleRetirementCorruption("Audit returned an invalid commit type")
    if type(commit.event) is not SystemAuditEvent:
        raise ExecutionRuleRetirementCorruption("Audit commit has an invalid event type")
    if type(commit.outbox_id) is not UUID:
        raise ExecutionRuleRetirementCorruption("Audit commit has an invalid outbox identity")
    try:
        SystemAuditEventOutboxCommit.__post_init__(commit)
        commit.event.validate_hashes()
        expected = build_execution_rule_retirement_audit_event(
            observation,
            sequence_no=commit.event.sequence_no,
            predecessor_hash=commit.event.predecessor_hash,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise ExecutionRuleRetirementCorruption(
            "Audit commit failed canonical event validation"
        ) from error
    if commit.event != expected:
        raise ExecutionRuleRetirementCorruption(
            "Audit commit differs from the rebuilt retirement event"
        )
    return expected


__all__ = ["CoreRiskExecutionRuleRetirementAuditBridge"]
