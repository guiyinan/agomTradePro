"""Append-only hash-chain lifecycle for exact R1 promotion decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .r1_forecast_promotion_decision import (
    R1ForecastPromotionDecision,
    R1PromotionDecisionOutcome,
    R1PromotionScope,
    _hash_payload,
    _require_aware,
    _require_hash,
    _require_token,
    _utc_text,
)


def r1_promotion_stream_id(scope: R1PromotionScope) -> str:
    """Return the sole canonical lifecycle stream identifier for a scope."""

    return f"research:r1:valuation:{scope.scope_id}"


class R1PromotionLifecycleEventType(str, Enum):
    """Research-owned append-only lifecycle transitions."""

    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


class R1PromotionLifecycleState(str, Enum):
    """Current state derived exclusively by replaying the event chain."""

    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"
    EXPIRED = "expired"


@dataclass(frozen=True)
class R1PromotionDecisionIdentity:
    """Complete decision header referenced by lifecycle evidence."""

    decision_id: str
    decision_version: str
    content_hash: str
    outcome: R1PromotionDecisionOutcome
    promotion_scope: R1PromotionScope
    result_id: str
    result_version: str
    result_content_hash: str
    policy_id: str
    policy_version: str
    policy_content_hash: str
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime

    @classmethod
    def from_decision(
        cls,
        decision: R1ForecastPromotionDecision,
    ) -> R1PromotionDecisionIdentity:
        """Project exact lifecycle identity from a canonical decision."""

        return cls(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            content_hash=decision.content_hash,
            outcome=decision.outcome,
            promotion_scope=decision.promotion_scope,
            result_id=decision.trial.result_id,
            result_version=decision.trial.result_version,
            result_content_hash=decision.trial.result_content_hash,
            policy_id=decision.policy.policy_id,
            policy_version=decision.policy.policy_version,
            policy_content_hash=decision.policy.content_hash,
            decided_at=decision.decided_at,
            recorded_at=decision.recorded_at,
            valid_until=decision.valid_until,
        )

    def __post_init__(self) -> None:
        for field_name, token_value in (
            ("decision_id", self.decision_id),
            ("decision_version", self.decision_version),
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
        ):
            _require_token(token_value, f"lifecycle decision {field_name}")
        for field_name, hash_value in (
            ("content_hash", self.content_hash),
            ("result_content_hash", self.result_content_hash),
            ("policy_content_hash", self.policy_content_hash),
        ):
            _require_hash(hash_value, f"lifecycle decision {field_name}")
        for field_name, time_value in (
            ("decided_at", self.decided_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(time_value, f"lifecycle decision {field_name}")
        if not self.decided_at <= self.recorded_at < self.valid_until:
            raise ValueError("lifecycle decision time window is invalid")


def r1_promotion_lifecycle_reason_hash(reason_codes: tuple[str, ...]) -> str:
    """Hash a canonical non-empty lifecycle reason set."""

    if not reason_codes or reason_codes != tuple(sorted(set(reason_codes))):
        raise ValueError("R1 promotion lifecycle reasons must be non-empty, unique and ordered")
    for reason_code in reason_codes:
        _require_token(reason_code, "R1 promotion lifecycle reason")
    return _hash_payload(
        {
            "schema": "research-r1-promotion-lifecycle-reasons.v1",
            "reason_codes": list(reason_codes),
        }
    )


@dataclass(frozen=True)
class R1PromotionLifecycleAuthorization:
    """Exact Research owner authorization for one lifecycle transition."""

    authorization_id: str
    authorization_version: str
    owner: str
    capability: str
    purpose: str
    promotion_scope: R1PromotionScope
    event_type: R1PromotionLifecycleEventType
    decision: R1PromotionDecisionIdentity
    rollback_target: R1PromotionDecisionIdentity | None
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
        owner: str,
        capability: str,
        purpose: str,
        event_type: R1PromotionLifecycleEventType,
        decision: R1ForecastPromotionDecision,
        rollback_target: R1ForecastPromotionDecision | None,
        reason_codes: tuple[str, ...],
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
    ) -> R1PromotionLifecycleAuthorization:
        """Seal Research owner authorization without inferring identity."""

        decision_identity = R1PromotionDecisionIdentity.from_decision(decision)
        target_identity = (
            R1PromotionDecisionIdentity.from_decision(rollback_target)
            if rollback_target is not None
            else None
        )
        reason_hash = r1_promotion_lifecycle_reason_hash(reason_codes)
        digest = _authorization_hash_values(
            authorization_id=authorization_id,
            authorization_version=authorization_version,
            owner=owner,
            capability=capability,
            purpose=purpose,
            promotion_scope=decision_identity.promotion_scope,
            event_type=event_type,
            decision=decision_identity,
            rollback_target=target_identity,
            reason_hash=reason_hash,
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
        )
        return cls(
            authorization_id=authorization_id,
            authorization_version=authorization_version,
            owner=owner,
            capability=capability,
            purpose=purpose,
            promotion_scope=decision_identity.promotion_scope,
            event_type=event_type,
            decision=decision_identity,
            rollback_target=target_identity,
            reason_hash=reason_hash,
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_token(self.authorization_id, "lifecycle authorization_id")
        _require_token(self.authorization_version, "lifecycle authorization_version")
        if self.owner != "research" or self.capability != "r1" or self.purpose != "valuation":
            raise ValueError("R1 lifecycle authorization authority is invalid")
        if (
            self.promotion_scope != self.decision.promotion_scope
            or self.promotion_scope.owner != self.owner
            or self.promotion_scope.capability != self.capability
            or self.promotion_scope.purpose != self.purpose
        ):
            raise ValueError("R1 lifecycle authorization scope is invalid")
        for field_name, value in (
            ("authorization issued_at", self.issued_at),
            ("authorization recorded_at", self.recorded_at),
            ("authorization valid_until", self.valid_until),
        ):
            _require_aware(value, field_name)
        if not (self.decision.recorded_at <= self.issued_at <= self.recorded_at < self.valid_until):
            raise ValueError("R1 lifecycle authorization receipt window is invalid")
        if self.event_type is R1PromotionLifecycleEventType.ROLLED_BACK:
            if self.rollback_target is None:
                raise ValueError("rollback authorization requires an exact target decision")
            if self.rollback_target.promotion_scope != self.promotion_scope:
                raise ValueError("rollback authorization cannot cross promotion scopes")
        elif self.rollback_target is not None:
            raise ValueError("non-rollback authorization cannot carry a rollback target")
        _require_hash(self.reason_hash, "lifecycle authorization reason_hash")
        _require_hash(self.content_hash, "lifecycle authorization content_hash")
        if self.content_hash != r1_promotion_lifecycle_authorization_hash(self):
            raise ValueError("R1 lifecycle authorization content hash mismatch")


def _decision_identity_payload(identity: R1PromotionDecisionIdentity) -> list[object]:
    return [
        identity.decision_id,
        identity.decision_version,
        identity.content_hash,
        identity.outcome.value,
        identity.promotion_scope.scope_id,
        identity.promotion_scope.content_hash,
        identity.result_id,
        identity.result_version,
        identity.result_content_hash,
        identity.policy_id,
        identity.policy_version,
        identity.policy_content_hash,
        _utc_text(identity.decided_at),
        _utc_text(identity.recorded_at),
        _utc_text(identity.valid_until),
    ]


def _authorization_hash_values(
    *,
    authorization_id: str,
    authorization_version: str,
    owner: str,
    capability: str,
    purpose: str,
    promotion_scope: R1PromotionScope,
    event_type: R1PromotionLifecycleEventType,
    decision: R1PromotionDecisionIdentity,
    rollback_target: R1PromotionDecisionIdentity | None,
    reason_hash: str,
    issued_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> str:
    return _hash_payload(
        {
            "schema": "research-r1-promotion-lifecycle-authorization.v1",
            "identity": [authorization_id, authorization_version, owner, capability, purpose],
            "promotion_scope": [promotion_scope.scope_id, promotion_scope.content_hash],
            "event_type": event_type.value,
            "decision": _decision_identity_payload(decision),
            "rollback_target": (
                _decision_identity_payload(rollback_target) if rollback_target is not None else None
            ),
            "reason_hash": reason_hash,
            "window": [_utc_text(issued_at), _utc_text(recorded_at), _utc_text(valid_until)],
        }
    )


def r1_promotion_lifecycle_authorization_hash(
    authorization: R1PromotionLifecycleAuthorization,
) -> str:
    """Recompute exact lifecycle authorization evidence."""

    return _authorization_hash_values(
        authorization_id=authorization.authorization_id,
        authorization_version=authorization.authorization_version,
        owner=authorization.owner,
        capability=authorization.capability,
        purpose=authorization.purpose,
        promotion_scope=authorization.promotion_scope,
        event_type=authorization.event_type,
        decision=authorization.decision,
        rollback_target=authorization.rollback_target,
        reason_hash=authorization.reason_hash,
        issued_at=authorization.issued_at,
        recorded_at=authorization.recorded_at,
        valid_until=authorization.valid_until,
    )


@dataclass(frozen=True)
class R1PromotionLifecycleEvent:
    """One immutable, authorized link in the R1 promotion stream."""

    event_id: str
    event_version: str
    promotion_scope: R1PromotionScope
    stream_id: str
    event_type: R1PromotionLifecycleEventType
    sequence: int
    decision: R1PromotionDecisionIdentity
    rollback_target: R1PromotionDecisionIdentity | None
    authorization: R1PromotionLifecycleAuthorization
    reason_codes: tuple[str, ...]
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        _require_token(self.event_id, "R1 lifecycle event_id")
        _require_token(self.event_version, "R1 lifecycle event_version")
        if self.stream_id != r1_promotion_stream_id(self.promotion_scope):
            raise ValueError("R1 promotion lifecycle stream is invalid")
        if (
            self.promotion_scope != self.decision.promotion_scope
            or self.promotion_scope != self.authorization.promotion_scope
        ):
            raise ValueError("R1 promotion lifecycle event crosses promotion scopes")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("R1 lifecycle sequence must be positive")
        _require_aware(self.occurred_at, "R1 lifecycle occurred_at")
        _require_aware(self.recorded_at, "R1 lifecycle recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("R1 lifecycle record cannot predate occurrence")
        if self.sequence == 1:
            if (
                self.event_type is not R1PromotionLifecycleEventType.PROMOTED
                or self.previous_event_hash is not None
            ):
                raise ValueError("R1 lifecycle root must be an unlinked promotion")
        else:
            if self.previous_event_hash is None:
                raise ValueError("non-root R1 lifecycle event requires previous hash")
            _require_hash(self.previous_event_hash, "R1 lifecycle previous_event_hash")
        if self.decision.outcome is not R1PromotionDecisionOutcome.APPROVED:
            raise ValueError("R1 lifecycle can only reference approved decisions")
        if self.event_type is R1PromotionLifecycleEventType.ROLLED_BACK:
            target = self.rollback_target
            if (
                target is None
                or target.promotion_scope != self.promotion_scope
                or target.outcome is not R1PromotionDecisionOutcome.APPROVED
                or not target.recorded_at <= self.occurred_at < target.valid_until
            ):
                raise ValueError("R1 lifecycle rollback target is invalid or inactive")
        elif self.rollback_target is not None:
            raise ValueError("non-rollback lifecycle event cannot carry rollback target")
        if (
            self.event_type
            in {
                R1PromotionLifecycleEventType.PROMOTED,
                R1PromotionLifecycleEventType.ROLLED_BACK,
            }
            and not self.decision.recorded_at <= self.occurred_at < self.decision.valid_until
        ):
            raise ValueError("R1 lifecycle decision is inactive at occurrence")
        if self.occurred_at < self.authorization.recorded_at:
            raise ValueError("R1 lifecycle authorization was unavailable at occurrence")
        if not self.authorization.issued_at <= self.occurred_at < self.authorization.valid_until:
            raise ValueError("R1 lifecycle authorization is inactive at occurrence")
        if (
            self.authorization.event_type is not self.event_type
            or self.authorization.decision != self.decision
            or self.authorization.rollback_target != self.rollback_target
            or self.authorization.reason_hash
            != r1_promotion_lifecycle_reason_hash(self.reason_codes)
        ):
            raise ValueError("R1 lifecycle authorization does not match the event")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R1 lifecycle event must remain research-only")
        _require_hash(self.content_hash, "R1 lifecycle event content_hash")
        if self.content_hash != r1_promotion_lifecycle_event_hash(self):
            raise ValueError("R1 promotion lifecycle event content hash mismatch")


def _event_hash_values(
    *,
    event_id: str,
    event_version: str,
    promotion_scope: R1PromotionScope,
    stream_id: str,
    event_type: R1PromotionLifecycleEventType,
    sequence: int,
    decision: R1PromotionDecisionIdentity,
    rollback_target: R1PromotionDecisionIdentity | None,
    authorization: R1PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
    previous_event_hash: str | None,
) -> str:
    return _hash_payload(
        {
            "schema": "research-r1-promotion-lifecycle-event.v1",
            "identity": [event_id, event_version, stream_id],
            "promotion_scope": [promotion_scope.scope_id, promotion_scope.content_hash],
            "event_type": event_type.value,
            "sequence": sequence,
            "decision": _decision_identity_payload(decision),
            "rollback_target": (
                _decision_identity_payload(rollback_target) if rollback_target is not None else None
            ),
            "authorization_hash": authorization.content_hash,
            "reason_codes": list(reason_codes),
            "window": [_utc_text(occurred_at), _utc_text(recorded_at)],
            "previous_event_hash": previous_event_hash,
            "research_only": True,
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
    )


def r1_promotion_lifecycle_event_hash(event: R1PromotionLifecycleEvent) -> str:
    """Recompute one immutable lifecycle link."""

    return _event_hash_values(
        event_id=event.event_id,
        event_version=event.event_version,
        promotion_scope=event.promotion_scope,
        stream_id=event.stream_id,
        event_type=event.event_type,
        sequence=event.sequence,
        decision=event.decision,
        rollback_target=event.rollback_target,
        authorization=event.authorization,
        reason_codes=event.reason_codes,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        previous_event_hash=event.previous_event_hash,
    )


def create_r1_promotion_lifecycle_root(
    *,
    event_id: str,
    event_version: str,
    decision: R1ForecastPromotionDecision,
    authorization: R1PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
) -> R1PromotionLifecycleEvent:
    """Create the immutable first promotion link for the R1 stream."""

    return _build_event(
        event_id=event_id,
        event_version=event_version,
        event_type=R1PromotionLifecycleEventType.PROMOTED,
        sequence=1,
        decision=decision,
        rollback_target=None,
        authorization=authorization,
        reason_codes=reason_codes,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=None,
    )


def create_r1_promotion_lifecycle_event(
    *,
    event_id: str,
    event_version: str,
    previous_events: tuple[R1PromotionLifecycleEvent, ...],
    event_type: R1PromotionLifecycleEventType,
    decision: R1ForecastPromotionDecision,
    rollback_target: R1ForecastPromotionDecision | None,
    authorization: R1PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
) -> R1PromotionLifecycleEvent:
    """Create the next legal event after replaying the immutable chain."""

    stack, _ = _replay_chain(previous_events)
    previous = previous_events[-1]
    if (
        occurred_at < previous.occurred_at
        or occurred_at < previous.recorded_at
        or recorded_at < previous.recorded_at
    ):
        raise ValueError("R1 promotion lifecycle dual clocks cannot move backwards")
    decision_identity = R1PromotionDecisionIdentity.from_decision(decision)
    target_identity = (
        R1PromotionDecisionIdentity.from_decision(rollback_target)
        if rollback_target is not None
        else None
    )
    if decision_identity.promotion_scope != previous.promotion_scope:
        raise ValueError("R1 promotion lifecycle cannot append across promotion scopes")
    if target_identity is not None and target_identity.promotion_scope != previous.promotion_scope:
        raise ValueError("R1 promotion lifecycle rollback cannot cross promotion scopes")
    if event_type is R1PromotionLifecycleEventType.PROMOTED:
        if stack and stack[-1] == decision_identity:
            raise ValueError("R1 promotion lifecycle cannot promote the active decision again")
    elif event_type is R1PromotionLifecycleEventType.RETIRED:
        if not stack or stack[-1] != decision_identity:
            raise ValueError("R1 promotion retirement must target the active decision")
    elif len(stack) < 2 or stack[-1] != decision_identity or target_identity != stack[-2]:
        raise ValueError("R1 rollback target must be the exact previous promoted decision")
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
    event_type: R1PromotionLifecycleEventType,
    sequence: int,
    decision: R1ForecastPromotionDecision,
    rollback_target: R1ForecastPromotionDecision | None,
    authorization: R1PromotionLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
    previous_event_hash: str | None,
) -> R1PromotionLifecycleEvent:
    ordered_reasons = tuple(sorted(reason_codes))
    decision_identity = R1PromotionDecisionIdentity.from_decision(decision)
    target_identity = (
        R1PromotionDecisionIdentity.from_decision(rollback_target)
        if rollback_target is not None
        else None
    )
    promotion_scope = decision_identity.promotion_scope
    stream_id = r1_promotion_stream_id(promotion_scope)
    digest = _event_hash_values(
        event_id=event_id,
        event_version=event_version,
        promotion_scope=promotion_scope,
        stream_id=stream_id,
        event_type=event_type,
        sequence=sequence,
        decision=decision_identity,
        rollback_target=target_identity,
        authorization=authorization,
        reason_codes=ordered_reasons,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=previous_event_hash,
    )
    return R1PromotionLifecycleEvent(
        event_id=event_id,
        event_version=event_version,
        promotion_scope=promotion_scope,
        stream_id=stream_id,
        event_type=event_type,
        sequence=sequence,
        decision=decision_identity,
        rollback_target=target_identity,
        authorization=authorization,
        reason_codes=ordered_reasons,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=previous_event_hash,
        content_hash=digest,
    )


@dataclass(frozen=True)
class R1PromotionLifecycleSnapshot:
    """PIT state returned after exact chain replay."""

    promotion_scope: R1PromotionScope
    stream_id: str
    state: R1PromotionLifecycleState
    active_decision: R1PromotionDecisionIdentity | None
    latest_event_hash: str
    evaluated_at: datetime


def derive_r1_promotion_lifecycle_state(
    events: tuple[R1PromotionLifecycleEvent, ...],
    *,
    evaluated_at: datetime,
) -> R1PromotionLifecycleSnapshot:
    """Verify the full recorded chain and derive active evidence at knowledge time."""

    _require_aware(evaluated_at, "R1 lifecycle evaluated_at")
    if any(event.recorded_at > evaluated_at for event in events):
        raise ValueError("R1 lifecycle chain contains future-unrecorded evidence")
    stack, last_type = _replay_chain(events)
    latest = events[-1]
    if not stack:
        state = R1PromotionLifecycleState.RETIRED
        active = None
    else:
        candidate = stack[-1]
        if not candidate.recorded_at <= evaluated_at < candidate.valid_until:
            state = R1PromotionLifecycleState.EXPIRED
            active = None
        else:
            state = (
                R1PromotionLifecycleState.ROLLED_BACK
                if last_type is R1PromotionLifecycleEventType.ROLLED_BACK
                else R1PromotionLifecycleState.PROMOTED
            )
            active = candidate
    return R1PromotionLifecycleSnapshot(
        promotion_scope=latest.promotion_scope,
        stream_id=latest.stream_id,
        state=state,
        active_decision=active,
        latest_event_hash=latest.content_hash,
        evaluated_at=evaluated_at,
    )


def _replay_chain(
    events: tuple[R1PromotionLifecycleEvent, ...],
) -> tuple[list[R1PromotionDecisionIdentity], R1PromotionLifecycleEventType]:
    if not events:
        raise ValueError("R1 promotion lifecycle chain cannot be empty")
    stack: list[R1PromotionDecisionIdentity] = []
    expected_previous: str | None = None
    previous_occurred_at: datetime | None = None
    previous_recorded_at: datetime | None = None
    promotion_scope = events[0].promotion_scope
    stream_id = r1_promotion_stream_id(promotion_scope)
    for expected_sequence, event in enumerate(events, start=1):
        if event.promotion_scope != promotion_scope or event.stream_id != stream_id:
            raise ValueError("R1 promotion lifecycle chain crosses promotion scopes")
        if event.sequence != expected_sequence or event.previous_event_hash != expected_previous:
            raise ValueError("R1 promotion lifecycle chain is discontinuous")
        if previous_occurred_at is not None and event.occurred_at < previous_occurred_at:
            raise ValueError("R1 lifecycle occurred_at moves backwards")
        if previous_recorded_at is not None and event.recorded_at < previous_recorded_at:
            raise ValueError("R1 lifecycle recorded_at moves backwards")
        if previous_recorded_at is not None and event.occurred_at < previous_recorded_at:
            raise ValueError("R1 lifecycle occurrence predates previous receipt")
        if event.event_type is R1PromotionLifecycleEventType.PROMOTED:
            if stack and stack[-1] == event.decision:
                raise ValueError("R1 promotion lifecycle duplicates the active decision")
            stack.append(event.decision)
        elif event.event_type is R1PromotionLifecycleEventType.RETIRED:
            if not stack or stack[-1] != event.decision:
                raise ValueError("R1 retirement does not target the active decision")
            stack.clear()
        else:
            if len(stack) < 2 or stack[-1] != event.decision or event.rollback_target != stack[-2]:
                raise ValueError("R1 rollback does not target the previous promotion")
            stack.pop()
        expected_previous = event.content_hash
        previous_occurred_at = event.occurred_at
        previous_recorded_at = event.recorded_at
    return stack, events[-1].event_type


__all__ = [
    "R1PromotionDecisionIdentity",
    "R1PromotionLifecycleAuthorization",
    "R1PromotionLifecycleEvent",
    "R1PromotionLifecycleEventType",
    "R1PromotionLifecycleSnapshot",
    "R1PromotionLifecycleState",
    "create_r1_promotion_lifecycle_event",
    "create_r1_promotion_lifecycle_root",
    "derive_r1_promotion_lifecycle_state",
    "r1_promotion_lifecycle_authorization_hash",
    "r1_promotion_lifecycle_event_hash",
    "r1_promotion_lifecycle_reason_hash",
    "r1_promotion_stream_id",
]
