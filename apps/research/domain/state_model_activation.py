"""Fail-closed R6 activation, retirement, and exact rollback contracts.

This is deliberately separate from the internal qualification lifecycle.  An
activation event selects a Research-approved state-model artifact in an
auditable stack, but this module never publishes ``current``, replaces Regime,
authorizes a decision, or executes a trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from apps.research.domain.state_model_qualification_contracts import _canonical_hash
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_reasons(reason_codes: object, field_name: str) -> None:
    if not isinstance(reason_codes, tuple) or not reason_codes:
        raise ValueError(f"{field_name} must contain unique reason codes")
    for reason in reason_codes:
        _require_token(reason, f"{field_name}.reason", maximum=96)
    if len(reason_codes) != len(set(reason_codes)):
        raise ValueError(f"{field_name} must contain unique reason codes")


def _require_safe_flags(
    *,
    research_only: object,
    must_not_use_for_decision: object,
    must_not_replace_regime: object,
    must_not_publish_current: object,
    must_not_execute: object,
    field_name: str,
) -> None:
    if not (
        research_only is True
        and must_not_use_for_decision is True
        and must_not_replace_regime is True
        and must_not_publish_current is True
        and must_not_execute is True
    ):
        raise ValueError(f"{field_name} cannot authorize a production consumer")


def _require_qualification_ref(value: object, field_name: str) -> R6QualificationRef:
    if not isinstance(value, R6QualificationRef):
        raise ValueError(f"{field_name} has an invalid type")
    value.__post_init__()
    return value


class R6ActivationAction(str, Enum):
    """Manual actions for the separate activation stack."""

    ACTIVATE = "activate"
    RETIRE = "retire"
    ROLLBACK = "rollback"


class R6ActivationApprovalOutcome(str, Enum):
    """Canonical Research owner outcome for an activation review."""

    APPROVED = "approved"
    REJECTED = "rejected"


class R6MonitoringActivationStatus(str, Enum):
    """Monitoring states admitted at the activation owner boundary."""

    HEALTHY = "healthy"
    BREACHED = "breached"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class R6ActivationScopeRef:
    """Exact content-bound identity of one activation stream scope."""

    scope_id: str
    scope_version: str
    scope_hash: str

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R6ActivationScopeRef.scope_id")
        _require_token(self.scope_version, "R6ActivationScopeRef.scope_version")
        _require_hash(self.scope_hash, "R6ActivationScopeRef.scope_hash")

    @classmethod
    def from_scope(cls, scope: R6ActivationScope) -> R6ActivationScopeRef:
        """Create the exact reference for a validated scope."""

        validate_r6_activation_scope(scope)
        return cls(scope.scope_id, scope.scope_version, scope.content_hash)


@dataclass(frozen=True)
class R6MonitoringActivationRef:
    """Exact identity of one persisted R6 monitoring assessment."""

    assessment_id: str
    assessment_hash: str

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "R6MonitoringActivationRef.assessment_id")
        _require_hash(self.assessment_hash, "R6MonitoringActivationRef.assessment_hash")


@dataclass(frozen=True)
class R6ActivationApprovalRef:
    """Exact identity of a canonical activation approval."""

    approval_id: str
    approval_version: str
    approval_hash: str

    def __post_init__(self) -> None:
        _require_token(self.approval_id, "R6ActivationApprovalRef.approval_id")
        _require_token(self.approval_version, "R6ActivationApprovalRef.approval_version")
        _require_hash(self.approval_hash, "R6ActivationApprovalRef.approval_hash")


@dataclass(frozen=True, init=False)
class R6ActivationScope:
    """Versioned owner-defined scope that remains disconnected from consumers."""

    scope_id: str
    scope_version: str
    purpose: str
    label_protocol_version: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    must_not_publish_current: bool
    must_not_execute: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        scope_id: str,
        scope_version: str,
        purpose: str,
        label_protocol_version: str,
        research_only: bool = True,
        must_not_use_for_decision: bool = True,
        must_not_replace_regime: bool = True,
        must_not_publish_current: bool = True,
        must_not_execute: bool = True,
    ) -> None:
        values = {
            "scope_id": scope_id,
            "scope_version": scope_version,
            "purpose": purpose,
            "label_protocol_version": label_protocol_version,
            "research_only": research_only,
            "must_not_use_for_decision": must_not_use_for_decision,
            "must_not_replace_regime": must_not_replace_regime,
            "must_not_publish_current": must_not_publish_current,
            "must_not_execute": must_not_execute,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        for name in ("scope_id", "scope_version", "purpose", "label_protocol_version"):
            _require_token(getattr(self, name), f"R6ActivationScope.{name}")
        _require_safe_flags(
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_replace_regime=self.must_not_replace_regime,
            must_not_publish_current=self.must_not_publish_current,
            must_not_execute=self.must_not_execute,
            field_name="R6 activation scope",
        )
        _require_hash(self.content_hash, "R6ActivationScope.content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R6 activation scope content hash mismatch")

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical scope seal."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


def validate_r6_activation_scope(scope: R6ActivationScope) -> None:
    """Revalidate an owner-returned scope, including its live content seal."""

    if not isinstance(scope, R6ActivationScope):
        raise ValueError("R6 activation scope has an invalid type")
    scope.__post_init__()


@dataclass(frozen=True, init=False)
class R6MonitoringActivationEvidence:
    """Content-sealed owner projection of one persisted monitoring assessment."""

    assessment_id: str
    assessment_hash: str
    qualification_ref: R6QualificationRef
    policy_id: str
    policy_version: str
    policy_hash: str
    label_protocol_version: str
    label_set_hash: str
    status: R6MonitoringActivationStatus
    evaluated_at: datetime
    recorded_at: datetime
    valid_until: datetime
    owner: str
    evidence_ref: str
    retirement_review_required: bool
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    must_not_publish_current: bool
    must_not_execute: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        assessment_id: str,
        assessment_hash: str,
        qualification_ref: R6QualificationRef,
        policy_id: str,
        policy_version: str,
        policy_hash: str,
        label_protocol_version: str,
        label_set_hash: str,
        status: R6MonitoringActivationStatus,
        evaluated_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        owner: str,
        evidence_ref: str,
        retirement_review_required: bool = False,
        research_only: bool = True,
        must_not_use_for_decision: bool = True,
        must_not_replace_regime: bool = True,
        must_not_publish_current: bool = True,
        must_not_execute: bool = True,
    ) -> None:
        values = {
            "assessment_id": assessment_id,
            "assessment_hash": assessment_hash,
            "qualification_ref": qualification_ref,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "policy_hash": policy_hash,
            "label_protocol_version": label_protocol_version,
            "label_set_hash": label_set_hash,
            "status": status,
            "evaluated_at": evaluated_at,
            "recorded_at": recorded_at,
            "valid_until": valid_until,
            "owner": owner,
            "evidence_ref": evidence_ref,
            "retirement_review_required": retirement_review_required,
            "research_only": research_only,
            "must_not_use_for_decision": must_not_use_for_decision,
            "must_not_replace_regime": must_not_replace_regime,
            "must_not_publish_current": must_not_publish_current,
            "must_not_execute": must_not_execute,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        _require_token(self.assessment_id, "R6MonitoringActivationEvidence.assessment_id")
        _require_hash(self.assessment_hash, "R6MonitoringActivationEvidence.assessment_hash")
        _require_qualification_ref(
            self.qualification_ref,
            "R6MonitoringActivationEvidence.qualification_ref",
        )
        _require_hash(
            self.qualification_ref.assessment_hash,
            "R6MonitoringActivationEvidence.qualification_ref.assessment_hash",
        )
        for name in ("policy_id", "policy_version", "label_protocol_version", "owner"):
            _require_token(getattr(self, name), f"R6MonitoringActivationEvidence.{name}")
        if self.owner != "research":
            raise ValueError("R6 monitoring activation evidence owner must be research")
        _require_hash(self.policy_hash, "R6MonitoringActivationEvidence.policy_hash")
        _require_hash(self.label_set_hash, "R6MonitoringActivationEvidence.label_set_hash")
        if not isinstance(self.status, R6MonitoringActivationStatus):
            raise ValueError("R6 monitoring activation evidence status is invalid")
        for name in ("evaluated_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, name), f"R6MonitoringActivationEvidence.{name}")
        if not self.evaluated_at <= self.recorded_at < self.valid_until:
            raise ValueError("R6 monitoring activation evidence clocks are invalid")
        _require_token(
            self.evidence_ref,
            "R6MonitoringActivationEvidence.evidence_ref",
            maximum=300,
        )
        if self.retirement_review_required != (
            self.status is R6MonitoringActivationStatus.RETIREMENT_REVIEW_REQUIRED
        ):
            raise ValueError("R6 monitoring retirement-review status/flag differs")
        _require_safe_flags(
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_replace_regime=self.must_not_replace_regime,
            must_not_publish_current=self.must_not_publish_current,
            must_not_execute=self.must_not_execute,
            field_name="R6 monitoring activation evidence",
        )
        _require_hash(self.content_hash, "R6MonitoringActivationEvidence.content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R6 monitoring activation evidence content hash mismatch")

    @property
    def ref(self) -> R6MonitoringActivationRef:
        """Return the exact underlying monitoring assessment reference."""

        return R6MonitoringActivationRef(self.assessment_id, self.assessment_hash)

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical owner projection seal."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this projection was known and unexpired at ``as_of``."""

        _require_aware(as_of, "R6 monitoring activation evidence as_of")
        return self.recorded_at <= as_of < self.valid_until


def validate_r6_monitoring_activation_evidence(
    evidence: R6MonitoringActivationEvidence,
) -> None:
    """Revalidate an owner-returned monitoring projection and live seal."""

    if not isinstance(evidence, R6MonitoringActivationEvidence):
        raise ValueError("R6 monitoring activation evidence has an invalid type")
    evidence.__post_init__()


@dataclass(frozen=True, init=False)
class R6ActivationApproval:
    """Canonical owner decision required before entering the activation stack."""

    approval_id: str
    approval_version: str
    scope: R6ActivationScope
    qualification_ref: R6QualificationRef
    active_qualification_hash: str
    candidate_id: str
    candidate_version: str
    monitoring_ref: R6MonitoringActivationRef
    monitoring_evidence_hash: str
    required_monitoring_policy_id: str
    required_monitoring_policy_version: str
    required_monitoring_policy_hash: str
    required_label_protocol_version: str
    required_label_set_hash: str
    maximum_monitoring_age_seconds: int
    outcome: R6ActivationApprovalOutcome
    owner: str
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime
    reason_codes: tuple[str, ...]
    evidence_ref: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    must_not_publish_current: bool
    must_not_execute: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        approval_id: str,
        approval_version: str,
        scope: R6ActivationScope,
        qualification_ref: R6QualificationRef,
        active_qualification_hash: str,
        candidate_id: str,
        candidate_version: str,
        monitoring_ref: R6MonitoringActivationRef,
        monitoring_evidence_hash: str,
        required_monitoring_policy_id: str,
        required_monitoring_policy_version: str,
        required_monitoring_policy_hash: str,
        required_label_protocol_version: str,
        required_label_set_hash: str,
        maximum_monitoring_age_seconds: int,
        outcome: R6ActivationApprovalOutcome,
        owner: str,
        decided_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        reason_codes: tuple[str, ...],
        evidence_ref: str,
        research_only: bool = True,
        must_not_use_for_decision: bool = True,
        must_not_replace_regime: bool = True,
        must_not_publish_current: bool = True,
        must_not_execute: bool = True,
    ) -> None:
        values = locals().copy()
        values.pop("self")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        _require_token(self.approval_id, "R6ActivationApproval.approval_id")
        _require_token(self.approval_version, "R6ActivationApproval.approval_version")
        validate_r6_activation_scope(self.scope)
        _require_qualification_ref(
            self.qualification_ref,
            "R6ActivationApproval.qualification_ref",
        )
        _require_hash(
            self.qualification_ref.assessment_hash,
            "R6ActivationApproval.qualification_ref.assessment_hash",
        )
        _require_hash(
            self.active_qualification_hash,
            "R6ActivationApproval.active_qualification_hash",
        )
        for name in (
            "candidate_id",
            "candidate_version",
            "required_monitoring_policy_id",
            "required_monitoring_policy_version",
            "required_label_protocol_version",
            "owner",
        ):
            _require_token(getattr(self, name), f"R6ActivationApproval.{name}")
        if self.owner != "research":
            raise ValueError("R6 activation approval owner must be research")
        _require_hash(
            self.monitoring_evidence_hash,
            "R6ActivationApproval.monitoring_evidence_hash",
        )
        if not isinstance(self.monitoring_ref, R6MonitoringActivationRef):
            raise ValueError("R6ActivationApproval.monitoring_ref has an invalid type")
        self.monitoring_ref.__post_init__()
        _require_hash(
            self.required_monitoring_policy_hash,
            "R6ActivationApproval.required_monitoring_policy_hash",
        )
        _require_hash(
            self.required_label_set_hash,
            "R6ActivationApproval.required_label_set_hash",
        )
        if self.required_label_protocol_version != self.scope.label_protocol_version:
            raise ValueError("R6 activation approval label protocol differs from scope")
        if (
            isinstance(self.maximum_monitoring_age_seconds, bool)
            or not isinstance(self.maximum_monitoring_age_seconds, int)
            or self.maximum_monitoring_age_seconds <= 0
        ):
            raise ValueError("R6 activation maximum monitoring age must be injected")
        if not isinstance(self.outcome, R6ActivationApprovalOutcome):
            raise ValueError("R6 activation approval outcome is invalid")
        for name in ("decided_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, name), f"R6ActivationApproval.{name}")
        if not self.decided_at <= self.recorded_at < self.valid_until:
            raise ValueError("R6 activation approval clocks are invalid")
        _require_reasons(self.reason_codes, "R6ActivationApproval.reason_codes")
        _require_token(self.evidence_ref, "R6ActivationApproval.evidence_ref", maximum=300)
        _require_safe_flags(
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_replace_regime=self.must_not_replace_regime,
            must_not_publish_current=self.must_not_publish_current,
            must_not_execute=self.must_not_execute,
            field_name="R6 activation approval",
        )
        _require_hash(self.content_hash, "R6ActivationApproval.content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R6 activation approval content hash mismatch")

    @property
    def ref(self) -> R6ActivationApprovalRef:
        """Return this approval's exact identity and seal."""

        return R6ActivationApprovalRef(
            self.approval_id,
            self.approval_version,
            self.content_hash,
        )

    @property
    def scope_ref(self) -> R6ActivationScopeRef:
        """Return the exact activation stream scope."""

        return R6ActivationScopeRef.from_scope(self.scope)

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical activation approval seal."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the approval is known and valid at ``as_of``."""

        _require_aware(as_of, "R6 activation approval as_of")
        return self.recorded_at <= as_of < self.valid_until


def validate_r6_activation_approval(approval: R6ActivationApproval) -> None:
    """Revalidate an owner-returned approval, including all nested seals."""

    if not isinstance(approval, R6ActivationApproval):
        raise ValueError("R6 activation approval has an invalid type")
    approval.__post_init__()


@dataclass(frozen=True)
class R6ActivationAuthorizationRef:
    """ID/version-only locator for one manual lifecycle authorization."""

    authorization_id: str
    authorization_version: str

    def __post_init__(self) -> None:
        _require_token(self.authorization_id, "R6ActivationAuthorizationRef.authorization_id")
        _require_token(
            self.authorization_version,
            "R6ActivationAuthorizationRef.authorization_version",
        )


@dataclass(frozen=True, init=False)
class R6ActivationAuthorization:
    """Manual owner authorization for exactly one stack transition."""

    authorization_id: str
    authorization_version: str
    event_id: str
    event_version: str
    scope_ref: R6ActivationScopeRef
    action: R6ActivationAction
    subject: R6ActivationApprovalRef
    rollback_target: R6ActivationApprovalRef | None
    expected_sequence: int
    expected_previous_event_hash: str | None
    owner: str
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    reason_codes: tuple[str, ...]
    evidence_ref: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    must_not_publish_current: bool
    must_not_execute: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        event_id: str,
        event_version: str,
        scope_ref: R6ActivationScopeRef,
        action: R6ActivationAction,
        subject: R6ActivationApprovalRef,
        rollback_target: R6ActivationApprovalRef | None,
        expected_sequence: int,
        expected_previous_event_hash: str | None,
        owner: str,
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        reason_codes: tuple[str, ...],
        evidence_ref: str,
        research_only: bool = True,
        must_not_use_for_decision: bool = True,
        must_not_replace_regime: bool = True,
        must_not_publish_current: bool = True,
        must_not_execute: bool = True,
    ) -> None:
        values = locals().copy()
        values.pop("self")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        for name in (
            "authorization_id",
            "authorization_version",
            "event_id",
            "event_version",
            "owner",
        ):
            _require_token(getattr(self, name), f"R6ActivationAuthorization.{name}")
        if self.owner != "research":
            raise ValueError("R6 activation authorization owner must be research")
        if not isinstance(self.scope_ref, R6ActivationScopeRef):
            raise ValueError("R6ActivationAuthorization.scope_ref has an invalid type")
        self.scope_ref.__post_init__()
        if not isinstance(self.subject, R6ActivationApprovalRef):
            raise ValueError("R6ActivationAuthorization.subject has an invalid type")
        self.subject.__post_init__()
        if self.rollback_target is not None:
            if not isinstance(self.rollback_target, R6ActivationApprovalRef):
                raise ValueError("R6ActivationAuthorization.rollback_target has an invalid type")
            self.rollback_target.__post_init__()
        if not isinstance(self.action, R6ActivationAction):
            raise ValueError("R6 activation authorization action is invalid")
        if (self.action is R6ActivationAction.ROLLBACK) != (self.rollback_target is not None):
            raise ValueError("only R6 rollback authorization has a target")
        if (
            isinstance(self.expected_sequence, bool)
            or not isinstance(self.expected_sequence, int)
            or self.expected_sequence < 1
        ):
            raise ValueError("R6 activation authorization sequence is invalid")
        if self.expected_sequence == 1:
            if self.expected_previous_event_hash is not None:
                raise ValueError("initial R6 activation authorization cannot claim a previous head")
        else:
            _require_hash(
                self.expected_previous_event_hash,
                "R6ActivationAuthorization.expected_previous_event_hash",
            )
        for name in ("issued_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, name), f"R6ActivationAuthorization.{name}")
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("R6 activation authorization clocks are invalid")
        _require_reasons(self.reason_codes, "R6ActivationAuthorization.reason_codes")
        _require_token(self.evidence_ref, "R6ActivationAuthorization.evidence_ref", maximum=300)
        _require_safe_flags(
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_replace_regime=self.must_not_replace_regime,
            must_not_publish_current=self.must_not_publish_current,
            must_not_execute=self.must_not_execute,
            field_name="R6 activation authorization",
        )
        _require_hash(self.content_hash, "R6ActivationAuthorization.content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R6 activation authorization content hash mismatch")

    @property
    def ref(self) -> R6ActivationAuthorizationRef:
        """Return the ID/version-only authorization locator."""

        return R6ActivationAuthorizationRef(
            self.authorization_id,
            self.authorization_version,
        )

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical authorization seal."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this authorization is known and valid at ``as_of``."""

        _require_aware(as_of, "R6 activation authorization as_of")
        return self.recorded_at <= as_of < self.valid_until


def validate_r6_activation_authorization(
    authorization: R6ActivationAuthorization,
) -> None:
    """Revalidate an owner-returned transition authorization and live seal."""

    if not isinstance(authorization, R6ActivationAuthorization):
        raise ValueError("R6 activation authorization has an invalid type")
    authorization.__post_init__()


@dataclass(frozen=True, init=False)
class R6ActivationEvent:
    """Immutable event in one exact activation scope stack."""

    event_id: str
    event_version: str
    scope_ref: R6ActivationScopeRef
    action: R6ActivationAction
    subject: R6ActivationApprovalRef
    rollback_target: R6ActivationApprovalRef | None
    authorization_id: str
    authorization_version: str
    authorization_hash: str
    sequence: int
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None
    reason_codes: tuple[str, ...]
    research_only: bool
    must_not_use_for_decision: bool
    must_not_replace_regime: bool
    must_not_publish_current: bool
    must_not_execute: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        event_id: str,
        event_version: str,
        scope_ref: R6ActivationScopeRef,
        action: R6ActivationAction,
        subject: R6ActivationApprovalRef,
        rollback_target: R6ActivationApprovalRef | None,
        authorization_id: str,
        authorization_version: str,
        authorization_hash: str,
        sequence: int,
        occurred_at: datetime,
        recorded_at: datetime,
        previous_event_hash: str | None,
        reason_codes: tuple[str, ...],
        research_only: bool = True,
        must_not_use_for_decision: bool = True,
        must_not_replace_regime: bool = True,
        must_not_publish_current: bool = True,
        must_not_execute: bool = True,
    ) -> None:
        values = locals().copy()
        values.pop("self")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "event_version",
            "authorization_id",
            "authorization_version",
        ):
            _require_token(getattr(self, name), f"R6ActivationEvent.{name}")
        if not isinstance(self.action, R6ActivationAction):
            raise ValueError("R6 activation event action is invalid")
        if not isinstance(self.scope_ref, R6ActivationScopeRef):
            raise ValueError("R6ActivationEvent.scope_ref has an invalid type")
        self.scope_ref.__post_init__()
        if not isinstance(self.subject, R6ActivationApprovalRef):
            raise ValueError("R6ActivationEvent.subject has an invalid type")
        self.subject.__post_init__()
        if self.rollback_target is not None:
            if not isinstance(self.rollback_target, R6ActivationApprovalRef):
                raise ValueError("R6ActivationEvent.rollback_target has an invalid type")
            self.rollback_target.__post_init__()
        if (self.action is R6ActivationAction.ROLLBACK) != (self.rollback_target is not None):
            raise ValueError("only R6 rollback event has a target")
        _require_hash(self.authorization_hash, "R6ActivationEvent.authorization_hash")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise ValueError("R6 activation event sequence is invalid")
        _require_aware(self.occurred_at, "R6ActivationEvent.occurred_at")
        _require_aware(self.recorded_at, "R6ActivationEvent.recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("R6 activation event recorded_at precedes occurrence")
        if self.previous_event_hash is not None:
            _require_hash(self.previous_event_hash, "R6ActivationEvent.previous_event_hash")
        _require_reasons(self.reason_codes, "R6ActivationEvent.reason_codes")
        _require_safe_flags(
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_replace_regime=self.must_not_replace_regime,
            must_not_publish_current=self.must_not_publish_current,
            must_not_execute=self.must_not_execute,
            field_name="R6 activation event",
        )
        _require_hash(self.content_hash, "R6ActivationEvent.content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R6 activation event content hash mismatch")

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical event seal."""

        return _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))


@dataclass(frozen=True)
class R6ActivationState:
    """Derived exact state of one activation stream."""

    scope_ref: R6ActivationScopeRef
    activation_stack: tuple[R6ActivationApprovalRef, ...]
    active_approval: R6ActivationApprovalRef | None
    sequence: int
    head_event_hash: str


def create_r6_activation_event(
    *,
    authorization: R6ActivationAuthorization,
    previous_events: tuple[R6ActivationEvent, ...],
    applied_at: datetime,
) -> R6ActivationEvent:
    """Create one owner-authorized legal stack transition at server time."""

    validate_r6_activation_authorization(authorization)
    _require_aware(applied_at, "R6 activation applied_at")
    if not authorization.is_active_at(applied_at):
        raise ValueError("R6 activation authorization is inactive at application time")
    previous_state = (
        None
        if not previous_events
        else derive_r6_activation_state(previous_events, evaluated_at=applied_at)
    )
    expected_sequence = 1 if previous_state is None else previous_state.sequence + 1
    if authorization.expected_sequence != expected_sequence:
        raise ValueError("R6 activation authorization sequence is stale")
    expected_previous_hash = None if previous_state is None else previous_state.head_event_hash
    if authorization.expected_previous_event_hash != expected_previous_hash:
        raise ValueError("R6 activation authorization previous head hash differs")
    if previous_state is not None and previous_state.scope_ref != authorization.scope_ref:
        raise ValueError("R6 activation authorization crosses scope streams")
    if previous_events and (
        authorization.issued_at <= previous_events[-1].recorded_at
        or authorization.recorded_at <= previous_events[-1].recorded_at
    ):
        raise ValueError("R6 activation authorization does not strictly follow the stream head")
    stack = [] if previous_state is None else list(previous_state.activation_stack)
    if authorization.action is R6ActivationAction.ACTIVATE:
        if authorization.subject in stack:
            raise ValueError("R6 activation cannot duplicate an approval in the live stack")
        stack.append(authorization.subject)
    elif authorization.action is R6ActivationAction.RETIRE:
        if not stack or stack[-1] != authorization.subject:
            raise ValueError("R6 retirement must target the active approval")
        stack.clear()
    elif (
        len(stack) < 2
        or stack[-1] != authorization.subject
        or authorization.rollback_target != stack[-2]
    ):
        raise ValueError("R6 rollback target must be exactly stack[-2]")
    else:
        stack.pop()
    previous_hash = None if previous_state is None else previous_state.head_event_hash
    return R6ActivationEvent(
        event_id=authorization.event_id,
        event_version=authorization.event_version,
        scope_ref=authorization.scope_ref,
        action=authorization.action,
        subject=authorization.subject,
        rollback_target=authorization.rollback_target,
        authorization_id=authorization.authorization_id,
        authorization_version=authorization.authorization_version,
        authorization_hash=authorization.content_hash,
        sequence=expected_sequence,
        occurred_at=applied_at,
        recorded_at=applied_at,
        previous_event_hash=previous_hash,
        reason_codes=authorization.reason_codes,
    )


def derive_r6_activation_state(
    events: tuple[R6ActivationEvent, ...],
    *,
    evaluated_at: datetime,
) -> R6ActivationState:
    """Replay an exact ordered prefix and reject gaps, forks, or illegal rollback."""

    _require_aware(evaluated_at, "R6 activation evaluated_at")
    if not events:
        raise ValueError("R6 activation lifecycle has no events")
    scope_ref = events[0].scope_ref
    stack: list[R6ActivationApprovalRef] = []
    previous_hash: str | None = None
    authorization_refs: set[tuple[str, str]] = set()
    for expected_sequence, event in enumerate(events, start=1):
        if not isinstance(event, R6ActivationEvent):
            raise ValueError("R6 activation event has an invalid type")
        event.__post_init__()
        if event.scope_ref != scope_ref:
            raise ValueError("R6 activation events cross scope streams")
        if event.sequence != expected_sequence:
            raise ValueError("R6 activation event sequence is discontinuous")
        if event.recorded_at > evaluated_at:
            raise ValueError("R6 activation lifecycle contains future evidence")
        if event.previous_event_hash != previous_hash:
            raise ValueError("R6 activation lifecycle hash chain is broken")
        authorization_ref = (event.authorization_id, event.authorization_version)
        if authorization_ref in authorization_refs:
            raise ValueError("R6 activation lifecycle reuses an authorization")
        authorization_refs.add(authorization_ref)
        if event.action is R6ActivationAction.ACTIVATE:
            if event.subject in stack:
                raise ValueError("R6 activation lifecycle duplicates a live approval")
            stack.append(event.subject)
        elif event.action is R6ActivationAction.RETIRE:
            if not stack or stack[-1] != event.subject:
                raise ValueError("R6 retirement does not target the active approval")
            stack.clear()
        elif len(stack) < 2 or event.subject != stack[-1] or event.rollback_target != stack[-2]:
            raise ValueError("R6 rollback does not target stack[-2]")
        else:
            stack.pop()
        previous_hash = event.content_hash
    if previous_hash is None:  # pragma: no cover - guarded by non-empty events
        raise ValueError("R6 activation lifecycle has no head")
    return R6ActivationState(
        scope_ref=scope_ref,
        activation_stack=tuple(stack),
        active_approval=None if not stack else stack[-1],
        sequence=len(events),
        head_event_hash=previous_hash,
    )


__all__ = [
    "R6ActivationAction",
    "R6ActivationApproval",
    "R6ActivationApprovalOutcome",
    "R6ActivationApprovalRef",
    "R6ActivationAuthorization",
    "R6ActivationAuthorizationRef",
    "R6ActivationEvent",
    "R6ActivationScope",
    "R6ActivationScopeRef",
    "R6ActivationState",
    "R6MonitoringActivationEvidence",
    "R6MonitoringActivationRef",
    "R6MonitoringActivationStatus",
    "create_r6_activation_event",
    "derive_r6_activation_state",
    "validate_r6_activation_approval",
    "validate_r6_activation_authorization",
    "validate_r6_activation_scope",
    "validate_r6_monitoring_activation_evidence",
]
