"""Scope-local append-only lifecycle for exact R4 promotion decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .r4_promotion_decision import (
    R4PromotionDecision,
    R4PromotionDecisionOutcome,
)
from .r4_promotion_scope_policy import (
    R4PromotionScope,
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
)


def r4_promotion_stream_id(scope: R4PromotionScope) -> str:
    """Return the sole lifecycle stream identifier for one stable scope."""

    return f"research:r4:macro-risk:{scope.scope_id}"


class R4PromotionLifecycleEventType(str, Enum):
    """Research-owned lifecycle transitions."""

    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


class R4PromotionLifecycleState(str, Enum):
    """Current state derived only by replaying a recorded prefix."""

    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"
    EXPIRED = "expired"


@dataclass(frozen=True)
class R4PromotionDecisionIdentity:
    """Complete decision header referenced by lifecycle evidence."""

    decision_id: str
    decision_version: str
    content_hash: str
    outcome: R4PromotionDecisionOutcome
    scope: R4PromotionScope
    trial_id: str
    trial_version: str
    trial_content_hash: str
    portfolio_record_id: str
    portfolio_record_hash: str
    policy_id: str
    policy_version: str
    policy_content_hash: str
    current_r3_content_hash: str
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime

    @classmethod
    def from_decision(
        cls,
        decision: R4PromotionDecision,
    ) -> R4PromotionDecisionIdentity:
        """Project exact lifecycle identity from a canonical decision."""

        return cls(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            content_hash=decision.content_hash,
            outcome=decision.outcome,
            scope=decision.scope,
            trial_id=decision.trial.trial_id,
            trial_version=decision.trial.trial_version,
            trial_content_hash=decision.trial.content_hash,
            portfolio_record_id=decision.trial.portfolio_record.record_id,
            portfolio_record_hash=decision.trial.portfolio_record.record_hash,
            policy_id=decision.policy.policy_id,
            policy_version=decision.policy.policy_version,
            policy_content_hash=decision.policy.content_hash,
            current_r3_content_hash=decision.trial.current_r3_attestation.content_hash,
            decided_at=decision.decided_at,
            recorded_at=decision.recorded_at,
            valid_until=decision.valid_until,
        )

    def __post_init__(self) -> None:
        for identifier_name, identifier_value in (
            ("decision_id", self.decision_id),
            ("decision_version", self.decision_version),
            ("trial_id", self.trial_id),
            ("trial_version", self.trial_version),
            ("portfolio_record_id", self.portfolio_record_id),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
        ):
            _require_token(identifier_value, f"R4 lifecycle decision {identifier_name}")
        for hash_name, hash_value in (
            ("content_hash", self.content_hash),
            ("trial_content_hash", self.trial_content_hash),
            ("portfolio_record_hash", self.portfolio_record_hash),
            ("policy_content_hash", self.policy_content_hash),
            ("current_r3_content_hash", self.current_r3_content_hash),
        ):
            _require_hash(hash_value, f"R4 lifecycle decision {hash_name}")
        for clock_name, clock_value in (
            ("decided_at", self.decided_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(clock_value, f"R4 lifecycle decision {clock_name}")
        if not self.decided_at <= self.recorded_at < self.valid_until:
            raise ValueError("R4 lifecycle decision time window is invalid")


def r4_promotion_lifecycle_reason_hash(reason_codes: tuple[str, ...]) -> str:
    """Hash a non-empty canonical lifecycle reason set."""

    if not reason_codes or reason_codes != tuple(sorted(set(reason_codes))):
        raise ValueError("R4 lifecycle reasons must be non-empty, unique and ordered")
    for reason_code in reason_codes:
        _require_token(reason_code, "R4 lifecycle reason")
    return _hash_payload(
        {
            "schema": "research-r4-promotion-lifecycle-reasons.v1",
            "reason_codes": list(reason_codes),
        }
    )


@dataclass(frozen=True)
class R4PromotionLifecycleAuthorization:
    """Exact Research authorization for one lifecycle action."""

    authorization_id: str
    authorization_version: str
    owner: str
    capability: str
    purpose: str
    scope: R4PromotionScope
    event_type: R4PromotionLifecycleEventType
    decision: R4PromotionDecisionIdentity
    rollback_target: R4PromotionDecisionIdentity | None
    reason_hash: str
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        authorization_id: str,
        authorization_version: str,
        event_type: R4PromotionLifecycleEventType,
        decision: R4PromotionDecision,
        rollback_target: R4PromotionDecision | None,
        reason_codes: tuple[str, ...],
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
    ) -> R4PromotionLifecycleAuthorization:
        """Seal exact Research authority without caller-derived identity."""

        decision_identity = R4PromotionDecisionIdentity.from_decision(decision)
        target_identity = (
            None
            if rollback_target is None
            else R4PromotionDecisionIdentity.from_decision(rollback_target)
        )
        values = (
            authorization_id,
            authorization_version,
            "research",
            "r4",
            "macro_risk_method_research",
            decision.scope,
            event_type,
            decision_identity,
            target_identity,
            r4_promotion_lifecycle_reason_hash(reason_codes),
            issued_at,
            recorded_at,
            valid_until,
        )
        digest = _hash_payload(_authorization_payload(*values))
        return cls(*values, digest)

    def __post_init__(self) -> None:
        _require_token(self.authorization_id, "R4 lifecycle authorization_id")
        _require_token(self.authorization_version, "R4 lifecycle authorization_version")
        if (
            self.owner != "research"
            or self.capability != "r4"
            or self.purpose != "macro_risk_method_research"
        ):
            raise ValueError("R4 lifecycle authorization authority is invalid")
        if (
            self.scope != self.decision.scope
            or self.scope.owner != self.owner
            or self.scope.capability != self.capability
            or self.scope.purpose != self.purpose
        ):
            raise ValueError("R4 lifecycle authorization crosses scopes")
        for field_name, value in (
            ("issued_at", self.issued_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(value, f"R4 lifecycle authorization {field_name}")
        if not self.decision.recorded_at <= self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("R4 lifecycle authorization receipt window is invalid")
        if self.event_type is R4PromotionLifecycleEventType.ROLLED_BACK:
            if self.rollback_target is None or self.rollback_target.scope != self.scope:
                raise ValueError("R4 rollback authorization requires an exact scope-local target")
        elif self.rollback_target is not None:
            raise ValueError("non-rollback R4 authorization cannot carry a rollback target")
        _require_hash(self.reason_hash, "R4 lifecycle authorization reason_hash")
        _require_hash(self.content_hash, "R4 lifecycle authorization content_hash")
        if self.content_hash != r4_promotion_lifecycle_authorization_hash(self):
            raise ValueError("R4 lifecycle authorization content hash mismatch")


def _decision_identity_payload(identity: R4PromotionDecisionIdentity) -> list[object]:
    return [
        identity.decision_id,
        identity.decision_version,
        identity.content_hash,
        identity.outcome.value,
        identity.scope.scope_id,
        identity.scope.content_hash,
        identity.trial_id,
        identity.trial_version,
        identity.trial_content_hash,
        identity.portfolio_record_id,
        identity.portfolio_record_hash,
        identity.policy_id,
        identity.policy_version,
        identity.policy_content_hash,
        identity.current_r3_content_hash,
        _utc_text(identity.decided_at),
        _utc_text(identity.recorded_at),
        _utc_text(identity.valid_until),
    ]


def _authorization_payload(
    authorization_id: str,
    authorization_version: str,
    owner: str,
    capability: str,
    purpose: str,
    scope: R4PromotionScope,
    event_type: R4PromotionLifecycleEventType,
    decision: R4PromotionDecisionIdentity,
    rollback_target: R4PromotionDecisionIdentity | None,
    reason_hash: str,
    issued_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-lifecycle-authorization.v1",
        "identity": [authorization_id, authorization_version, owner, capability, purpose],
        "scope": [scope.scope_id, scope.content_hash],
        "event_type": event_type.value,
        "decision": _decision_identity_payload(decision),
        "rollback_target": (
            None if rollback_target is None else _decision_identity_payload(rollback_target)
        ),
        "reason_hash": reason_hash,
        "window": [_utc_text(issued_at), _utc_text(recorded_at), _utc_text(valid_until)],
    }


def r4_promotion_lifecycle_authorization_hash(
    authorization: R4PromotionLifecycleAuthorization,
) -> str:
    """Recompute one exact R4 lifecycle authorization hash."""

    return _hash_payload(
        _authorization_payload(
            authorization.authorization_id,
            authorization.authorization_version,
            authorization.owner,
            authorization.capability,
            authorization.purpose,
            authorization.scope,
            authorization.event_type,
            authorization.decision,
            authorization.rollback_target,
            authorization.reason_hash,
            authorization.issued_at,
            authorization.recorded_at,
            authorization.valid_until,
        )
    )


@dataclass(frozen=True)
class R4PromotionLifecycleEvent:
    """One immutable authorized link in a scope-local R4 stream."""

    event_id: str
    event_version: str
    scope: R4PromotionScope
    stream_id: str
    event_type: R4PromotionLifecycleEventType
    sequence: int
    decision: R4PromotionDecisionIdentity
    rollback_target: R4PromotionDecisionIdentity | None
    authorization: R4PromotionLifecycleAuthorization
    reason_codes: tuple[str, ...]
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        _require_token(self.event_id, "R4 lifecycle event_id")
        _require_token(self.event_version, "R4 lifecycle event_version")
        if self.stream_id != r4_promotion_stream_id(self.scope):
            raise ValueError("R4 lifecycle stream identity is invalid")
        if self.scope != self.decision.scope or self.scope != self.authorization.scope:
            raise ValueError("R4 lifecycle event crosses scopes")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("R4 lifecycle sequence must be positive")
        _require_aware(self.occurred_at, "R4 lifecycle occurred_at")
        _require_aware(self.recorded_at, "R4 lifecycle recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("R4 lifecycle record cannot predate occurrence")
        if self.sequence == 1:
            if (
                self.event_type is not R4PromotionLifecycleEventType.PROMOTED
                or self.previous_event_hash is not None
            ):
                raise ValueError("R4 lifecycle root must be an unlinked promotion")
        elif self.previous_event_hash is None:
            raise ValueError("non-root R4 lifecycle event requires a previous hash")
        else:
            _require_hash(self.previous_event_hash, "R4 lifecycle previous_event_hash")
        if self.decision.outcome is not R4PromotionDecisionOutcome.APPROVED:
            raise ValueError("R4 lifecycle can reference only approved decisions")
        if self.event_type is R4PromotionLifecycleEventType.ROLLED_BACK:
            target = self.rollback_target
            if (
                target is None
                or target.scope != self.scope
                or target.outcome is not R4PromotionDecisionOutcome.APPROVED
                or not target.recorded_at <= self.occurred_at < target.valid_until
            ):
                raise ValueError("R4 lifecycle rollback target is invalid or inactive")
        elif self.rollback_target is not None:
            raise ValueError("non-rollback R4 event cannot carry a rollback target")
        if (
            self.event_type
            in {
                R4PromotionLifecycleEventType.PROMOTED,
                R4PromotionLifecycleEventType.ROLLED_BACK,
            }
            and not self.decision.recorded_at <= self.occurred_at < self.decision.valid_until
        ):
            raise ValueError("R4 lifecycle decision is inactive at occurrence")
        if self.occurred_at < self.authorization.recorded_at:
            raise ValueError("R4 lifecycle authorization was unavailable at occurrence")
        if not self.authorization.issued_at <= self.occurred_at < self.authorization.valid_until:
            raise ValueError("R4 lifecycle authorization is inactive at occurrence")
        if (
            self.authorization.event_type is not self.event_type
            or self.authorization.decision != self.decision
            or self.authorization.rollback_target != self.rollback_target
            or self.authorization.reason_hash
            != r4_promotion_lifecycle_reason_hash(self.reason_codes)
        ):
            raise ValueError("R4 lifecycle authorization does not match the event")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R4 lifecycle event must remain research-only")
        _require_hash(self.content_hash, "R4 lifecycle event content_hash")
        if self.content_hash != r4_promotion_lifecycle_event_hash(self):
            raise ValueError("R4 lifecycle event content hash mismatch")


def _event_payload(
    event_id: str,
    event_version: str,
    scope: R4PromotionScope,
    stream_id: str,
    event_type: R4PromotionLifecycleEventType,
    sequence: int,
    decision: R4PromotionDecisionIdentity,
    rollback_target: R4PromotionDecisionIdentity | None,
    authorization: R4PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
    previous_event_hash: str | None,
) -> dict[str, object]:
    return {
        "schema": "research-r4-promotion-lifecycle-event.v1",
        "identity": [event_id, event_version, stream_id],
        "scope": [scope.scope_id, scope.content_hash],
        "event_type": event_type.value,
        "sequence": sequence,
        "decision": _decision_identity_payload(decision),
        "rollback_target": (
            None if rollback_target is None else _decision_identity_payload(rollback_target)
        ),
        "authorization_hash": authorization.content_hash,
        "reason_codes": list(reason_codes),
        "window": [_utc_text(occurred_at), _utc_text(recorded_at)],
        "previous_event_hash": previous_event_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r4_promotion_lifecycle_event_hash(event: R4PromotionLifecycleEvent) -> str:
    """Recompute one exact R4 lifecycle event hash."""

    return _hash_payload(
        _event_payload(
            event.event_id,
            event.event_version,
            event.scope,
            event.stream_id,
            event.event_type,
            event.sequence,
            event.decision,
            event.rollback_target,
            event.authorization,
            event.reason_codes,
            event.occurred_at,
            event.recorded_at,
            event.previous_event_hash,
        )
    )


def create_r4_promotion_lifecycle_root(
    *,
    event_id: str,
    event_version: str,
    decision: R4PromotionDecision,
    authorization: R4PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
) -> R4PromotionLifecycleEvent:
    """Create the immutable first promotion link for one R4 scope."""

    return _build_event(
        event_id=event_id,
        event_version=event_version,
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        sequence=1,
        decision=decision,
        rollback_target=None,
        authorization=authorization,
        reason_codes=reason_codes,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=None,
    )


def create_r4_promotion_lifecycle_event(
    *,
    event_id: str,
    event_version: str,
    previous_events: tuple[R4PromotionLifecycleEvent, ...],
    event_type: R4PromotionLifecycleEventType,
    decision: R4PromotionDecision,
    rollback_target: R4PromotionDecision | None,
    authorization: R4PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
) -> R4PromotionLifecycleEvent:
    """Create the next legal link after replaying the exact scope stack."""

    stack, _ = _replay_chain(previous_events)
    previous = previous_events[-1]
    if (
        occurred_at < previous.occurred_at
        or occurred_at < previous.recorded_at
        or recorded_at < previous.recorded_at
    ):
        raise ValueError("R4 lifecycle dual clocks cannot move backwards")
    decision_identity = R4PromotionDecisionIdentity.from_decision(decision)
    target_identity = (
        None
        if rollback_target is None
        else R4PromotionDecisionIdentity.from_decision(rollback_target)
    )
    if decision_identity.scope != previous.scope:
        raise ValueError("R4 lifecycle cannot append across scopes")
    if target_identity is not None and target_identity.scope != previous.scope:
        raise ValueError("R4 lifecycle rollback cannot cross scopes")
    if event_type is R4PromotionLifecycleEventType.PROMOTED:
        if stack and stack[-1] == decision_identity:
            raise ValueError("R4 lifecycle cannot promote the active decision again")
    elif event_type is R4PromotionLifecycleEventType.RETIRED:
        if not stack or stack[-1] != decision_identity:
            raise ValueError("R4 retirement must target the active decision")
    elif len(stack) < 2 or stack[-1] != decision_identity or target_identity != stack[-2]:
        raise ValueError("R4 rollback target must be exactly stack[-2]")
    return _build_event(
        event_id=event_id,
        event_version=event_version,
        event_type=event_type,
        sequence=previous.sequence + 1,
        decision=decision,
        rollback_target=rollback_target,
        authorization=authorization,
        reason_codes=reason_codes,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=previous.content_hash,
    )


def _build_event(
    *,
    event_id: str,
    event_version: str,
    event_type: R4PromotionLifecycleEventType,
    sequence: int,
    decision: R4PromotionDecision,
    rollback_target: R4PromotionDecision | None,
    authorization: R4PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
    previous_event_hash: str | None,
) -> R4PromotionLifecycleEvent:
    ordered_reasons = tuple(sorted(reason_codes))
    decision_identity = R4PromotionDecisionIdentity.from_decision(decision)
    target_identity = (
        None
        if rollback_target is None
        else R4PromotionDecisionIdentity.from_decision(rollback_target)
    )
    scope = decision.scope
    stream_id = r4_promotion_stream_id(scope)
    values = (
        event_id,
        event_version,
        scope,
        stream_id,
        event_type,
        sequence,
        decision_identity,
        target_identity,
        authorization,
        ordered_reasons,
        occurred_at,
        recorded_at,
        previous_event_hash,
    )
    digest = _hash_payload(_event_payload(*values))
    return R4PromotionLifecycleEvent(*values, digest)


@dataclass(frozen=True)
class R4PromotionLifecycleSnapshot:
    """PIT state returned after exact recorded-prefix replay."""

    scope: R4PromotionScope
    stream_id: str
    state: R4PromotionLifecycleState
    active_decision: R4PromotionDecisionIdentity | None
    latest_event_hash: str
    evaluated_at: datetime


def derive_r4_promotion_lifecycle_state(
    events: tuple[R4PromotionLifecycleEvent, ...],
    *,
    evaluated_at: datetime,
) -> R4PromotionLifecycleSnapshot:
    """Verify a complete recorded prefix and derive current scope state."""

    _require_aware(evaluated_at, "R4 lifecycle evaluated_at")
    if any(event.recorded_at > evaluated_at for event in events):
        raise ValueError("R4 lifecycle prefix contains future-unrecorded evidence")
    stack, last_type = _replay_chain(events)
    latest = events[-1]
    if not stack:
        state = R4PromotionLifecycleState.RETIRED
        active = None
    else:
        candidate = stack[-1]
        if not candidate.recorded_at <= evaluated_at < candidate.valid_until:
            state = R4PromotionLifecycleState.EXPIRED
            active = None
        else:
            state = (
                R4PromotionLifecycleState.ROLLED_BACK
                if last_type is R4PromotionLifecycleEventType.ROLLED_BACK
                else R4PromotionLifecycleState.PROMOTED
            )
            active = candidate
    return R4PromotionLifecycleSnapshot(
        scope=latest.scope,
        stream_id=latest.stream_id,
        state=state,
        active_decision=active,
        latest_event_hash=latest.content_hash,
        evaluated_at=evaluated_at,
    )


def _replay_chain(
    events: tuple[R4PromotionLifecycleEvent, ...],
) -> tuple[list[R4PromotionDecisionIdentity], R4PromotionLifecycleEventType]:
    if not events:
        raise ValueError("R4 lifecycle chain cannot be empty")
    stack: list[R4PromotionDecisionIdentity] = []
    expected_previous: str | None = None
    previous_occurred_at: datetime | None = None
    previous_recorded_at: datetime | None = None
    scope = events[0].scope
    stream_id = r4_promotion_stream_id(scope)
    for expected_sequence, event in enumerate(events, start=1):
        if event.scope != scope or event.stream_id != stream_id:
            raise ValueError("R4 lifecycle chain crosses scopes")
        if event.sequence != expected_sequence or event.previous_event_hash != expected_previous:
            raise ValueError("R4 lifecycle chain is discontinuous")
        if previous_occurred_at is not None and event.occurred_at < previous_occurred_at:
            raise ValueError("R4 lifecycle occurred_at moves backwards")
        if previous_recorded_at is not None and event.recorded_at < previous_recorded_at:
            raise ValueError("R4 lifecycle recorded_at moves backwards")
        if previous_recorded_at is not None and event.occurred_at < previous_recorded_at:
            raise ValueError("R4 lifecycle occurrence predates the previous receipt")
        if event.event_type is R4PromotionLifecycleEventType.PROMOTED:
            if stack and stack[-1] == event.decision:
                raise ValueError("R4 lifecycle duplicates the active decision")
            stack.append(event.decision)
        elif event.event_type is R4PromotionLifecycleEventType.RETIRED:
            if not stack or stack[-1] != event.decision:
                raise ValueError("R4 retirement does not target the active decision")
            stack.clear()
        else:
            if len(stack) < 2 or stack[-1] != event.decision or event.rollback_target != stack[-2]:
                raise ValueError("R4 rollback does not target stack[-2]")
            stack.pop()
        expected_previous = event.content_hash
        previous_occurred_at = event.occurred_at
        previous_recorded_at = event.recorded_at
    return stack, events[-1].event_type


__all__ = [
    "R4PromotionDecisionIdentity",
    "R4PromotionLifecycleAuthorization",
    "R4PromotionLifecycleEvent",
    "R4PromotionLifecycleEventType",
    "R4PromotionLifecycleSnapshot",
    "R4PromotionLifecycleState",
    "create_r4_promotion_lifecycle_event",
    "create_r4_promotion_lifecycle_root",
    "derive_r4_promotion_lifecycle_state",
    "r4_promotion_lifecycle_authorization_hash",
    "r4_promotion_lifecycle_event_hash",
    "r4_promotion_lifecycle_reason_hash",
    "r4_promotion_stream_id",
]
