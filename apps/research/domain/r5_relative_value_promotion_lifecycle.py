"""Scope-local append-only lifecycle for exact R5 promotion decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TypedDict

from apps.fixed_income.domain.evidence import (
    canonical_hash,
    require_aware,
    require_sha256,
    require_token,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionDecision,
    R5RelativeValuePromotionDecisionOutcome,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionScope,
)


def r5_relative_value_promotion_stream_id(
    scope: R5RelativeValuePromotionScope,
) -> str:
    """Return the sole append-only stream identity for one semantic scope."""

    return f"research:r5:relative-value:{scope.scope_id}"


class R5RelativeValueLifecycleEventType(str, Enum):
    """Research-owned lifecycle transitions."""

    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


class R5RelativeValueLifecycleState(str, Enum):
    """PIT state derived by replaying an exact recorded prefix."""

    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"
    EXPIRED = "expired"


@dataclass(frozen=True)
class R5RelativeValueDecisionIdentity:
    """Complete decision header referenced by lifecycle evidence."""

    decision_id: str
    decision_version: str
    content_hash: str
    outcome: R5RelativeValuePromotionDecisionOutcome
    scope: R5RelativeValuePromotionScope
    trial_id: str
    trial_version: str
    trial_content_hash: str
    policy_id: str
    policy_version: str
    policy_content_hash: str
    result_identities: tuple[tuple[str, str, str, str], ...]
    outcome_identities: tuple[tuple[str, str, str, str], ...]
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime

    @classmethod
    def from_decision(
        cls,
        decision: R5RelativeValuePromotionDecision,
    ) -> R5RelativeValueDecisionIdentity:
        """Project the exact lifecycle identity from a canonical decision."""

        return cls(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            content_hash=decision.content_hash,
            outcome=decision.outcome,
            scope=decision.scope,
            trial_id=decision.trial.trial_id,
            trial_version=decision.trial.trial_version,
            trial_content_hash=decision.trial.content_hash,
            policy_id=decision.policy.policy_id,
            policy_version=decision.policy.policy_version,
            policy_content_hash=decision.policy.content_hash,
            result_identities=tuple(
                sorted(
                    (
                        item.fixed_income_record.result_id,
                        item.fixed_income_record.result_version,
                        item.fixed_income_record.result_record_hash,
                        item.fixed_income_record.content_hash,
                    )
                    for item in decision.trial.observations
                )
            ),
            outcome_identities=tuple(
                sorted(
                    (
                        item.portfolio_outcome.outcome_id,
                        item.portfolio_outcome.outcome_version,
                        item.portfolio_outcome.owner_record_hash,
                        item.portfolio_outcome.content_hash,
                    )
                    for item in decision.trial.observations
                )
            ),
            decided_at=decision.decided_at,
            recorded_at=decision.recorded_at,
            valid_until=decision.valid_until,
        )

    def __post_init__(self) -> None:
        for field_name in (
            "decision_id",
            "decision_version",
            "trial_id",
            "trial_version",
            "policy_id",
            "policy_version",
        ):
            require_token(
                str(getattr(self, field_name)),
                f"R5 lifecycle decision {field_name}",
                maximum=300,
            )
        for field_name in (
            "content_hash",
            "trial_content_hash",
            "policy_content_hash",
        ):
            require_sha256(
                str(getattr(self, field_name)),
                f"R5 lifecycle decision {field_name}",
            )
        if not self.result_identities or self.result_identities != tuple(
            sorted(set(self.result_identities))
        ):
            raise ValueError("R5 lifecycle result identities must be complete and ordered")
        for result_id, result_version, record_hash, seal_hash in self.result_identities:
            require_token(result_id, "R5 lifecycle result_id", maximum=300)
            require_token(result_version, "R5 lifecycle result_version")
            require_sha256(record_hash, "R5 lifecycle result record hash")
            require_sha256(seal_hash, "R5 lifecycle result seal hash")
        if not self.outcome_identities or self.outcome_identities != tuple(
            sorted(set(self.outcome_identities))
        ):
            raise ValueError("R5 lifecycle outcome identities must be complete and ordered")
        for outcome_id, outcome_version, record_hash, seal_hash in self.outcome_identities:
            require_token(outcome_id, "R5 lifecycle outcome_id", maximum=300)
            require_token(outcome_version, "R5 lifecycle outcome_version")
            require_sha256(record_hash, "R5 lifecycle outcome record hash")
            require_sha256(seal_hash, "R5 lifecycle outcome seal hash")
        for field_name in ("decided_at", "recorded_at", "valid_until"):
            require_aware(
                getattr(self, field_name),
                f"R5 lifecycle decision {field_name}",
            )
        if not self.decided_at <= self.recorded_at < self.valid_until:
            raise ValueError("R5 lifecycle decision time window is invalid")


def r5_relative_value_lifecycle_reason_hash(reason_codes: tuple[str, ...]) -> str:
    """Hash a non-empty canonical lifecycle reason set."""

    if not reason_codes or reason_codes != tuple(sorted(set(reason_codes))):
        raise ValueError("R5 lifecycle reasons must be non-empty and ordered")
    for reason_code in reason_codes:
        require_token(reason_code, "R5 lifecycle reason", maximum=200)
    return canonical_hash(
        {
            "schema": "research-r5-relative-value-lifecycle-reasons.v1",
            "reason_codes": reason_codes,
        }
    )


class _LifecycleAuthorizationValues(TypedDict):
    authorization_version: str
    scope: R5RelativeValuePromotionScope
    event_type: R5RelativeValueLifecycleEventType
    decision: R5RelativeValueDecisionIdentity
    rollback_target: R5RelativeValueDecisionIdentity | None
    reason_hash: str
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime


@dataclass(frozen=True)
class R5RelativeValueLifecycleAuthorization:
    """Exact Research authorization for one lifecycle action."""

    authorization_id: str
    authorization_version: str
    owner: str
    capability: str
    purpose: str
    scope: R5RelativeValuePromotionScope
    event_type: R5RelativeValueLifecycleEventType
    decision: R5RelativeValueDecisionIdentity
    rollback_target: R5RelativeValueDecisionIdentity | None
    reason_hash: str
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        authorization_version: str,
        event_type: R5RelativeValueLifecycleEventType,
        decision: R5RelativeValuePromotionDecision,
        rollback_target: R5RelativeValuePromotionDecision | None,
        reason_codes: tuple[str, ...],
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
    ) -> R5RelativeValueLifecycleAuthorization:
        """Seal exact lifecycle authority without caller-derived identities."""

        decision_identity = R5RelativeValueDecisionIdentity.from_decision(decision)
        target_identity = (
            None
            if rollback_target is None
            else R5RelativeValueDecisionIdentity.from_decision(rollback_target)
        )
        values: _LifecycleAuthorizationValues = {
            "authorization_version": authorization_version,
            "scope": decision.scope,
            "event_type": event_type,
            "decision": decision_identity,
            "rollback_target": target_identity,
            "reason_hash": r5_relative_value_lifecycle_reason_hash(reason_codes),
            "issued_at": issued_at,
            "recorded_at": recorded_at,
            "valid_until": valid_until,
        }
        digest = canonical_hash(_authorization_payload(**values))
        return cls(
            authorization_id=f"r5-rv-lifecycle-auth:{digest}",
            owner="research",
            capability="r5",
            purpose="fixed_income_relative_value_research",
            content_hash=digest,
            **values,
        )

    def __post_init__(self) -> None:
        require_token(self.authorization_version, "R5 lifecycle authorization version")
        if (
            self.owner != "research"
            or self.capability != "r5"
            or self.purpose != "fixed_income_relative_value_research"
            or self.scope != self.decision.scope
        ):
            raise ValueError("R5 lifecycle authorization authority is invalid")
        for field_name in ("issued_at", "recorded_at", "valid_until"):
            require_aware(
                getattr(self, field_name),
                f"R5 lifecycle authorization {field_name}",
            )
        if not self.decision.recorded_at <= self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("R5 lifecycle authorization receipt window is invalid")
        if self.event_type is R5RelativeValueLifecycleEventType.ROLLED_BACK:
            if self.rollback_target is None or self.rollback_target.scope != self.scope:
                raise ValueError("R5 rollback authorization requires an exact local target")
        elif self.rollback_target is not None:
            raise ValueError("non-rollback R5 authorization cannot carry a target")
        require_sha256(self.reason_hash, "R5 lifecycle authorization reason_hash")
        require_sha256(self.content_hash, "R5 lifecycle authorization content_hash")
        expected = r5_relative_value_lifecycle_authorization_hash(self)
        if (
            self.content_hash != expected
            or self.authorization_id != f"r5-rv-lifecycle-auth:{expected}"
        ):
            raise ValueError("R5 lifecycle authorization content hash or identity mismatch")


def _identity_payload(identity: R5RelativeValueDecisionIdentity) -> tuple[object, ...]:
    return (
        identity.decision_id,
        identity.decision_version,
        identity.content_hash,
        identity.outcome.value,
        identity.scope.scope_id,
        identity.scope.content_hash,
        identity.trial_id,
        identity.trial_version,
        identity.trial_content_hash,
        identity.policy_id,
        identity.policy_version,
        identity.policy_content_hash,
        identity.result_identities,
        identity.outcome_identities,
        identity.decided_at,
        identity.recorded_at,
        identity.valid_until,
    )


def _authorization_payload(
    *,
    authorization_version: str,
    scope: R5RelativeValuePromotionScope,
    event_type: R5RelativeValueLifecycleEventType,
    decision: R5RelativeValueDecisionIdentity,
    rollback_target: R5RelativeValueDecisionIdentity | None,
    reason_hash: str,
    issued_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-lifecycle-authorization.v1",
        "identity": (authorization_version, "research", "r5"),
        "scope": (scope.scope_id, scope.content_hash),
        "event_type": event_type.value,
        "decision": _identity_payload(decision),
        "rollback_target": (
            None if rollback_target is None else _identity_payload(rollback_target)
        ),
        "reason_hash": reason_hash,
        "window": (issued_at, recorded_at, valid_until),
    }


def r5_relative_value_lifecycle_authorization_hash(
    authorization: R5RelativeValueLifecycleAuthorization,
) -> str:
    """Recompute one exact lifecycle authorization hash."""

    return canonical_hash(
        _authorization_payload(
            authorization_version=authorization.authorization_version,
            scope=authorization.scope,
            event_type=authorization.event_type,
            decision=authorization.decision,
            rollback_target=authorization.rollback_target,
            reason_hash=authorization.reason_hash,
            issued_at=authorization.issued_at,
            recorded_at=authorization.recorded_at,
            valid_until=authorization.valid_until,
        )
    )


class _LifecycleEventValues(TypedDict):
    event_version: str
    scope: R5RelativeValuePromotionScope
    stream_id: str
    event_type: R5RelativeValueLifecycleEventType
    sequence: int
    decision: R5RelativeValueDecisionIdentity
    rollback_target: R5RelativeValueDecisionIdentity | None
    authorization: R5RelativeValueLifecycleAuthorization
    reason_codes: tuple[str, ...]
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None


@dataclass(frozen=True)
class R5RelativeValueLifecycleEvent:
    """One immutable authorized link in a scope-local lifecycle stream."""

    event_id: str
    event_version: str
    scope: R5RelativeValuePromotionScope
    stream_id: str
    event_type: R5RelativeValueLifecycleEventType
    sequence: int
    decision: R5RelativeValueDecisionIdentity
    rollback_target: R5RelativeValueDecisionIdentity | None
    authorization: R5RelativeValueLifecycleAuthorization
    reason_codes: tuple[str, ...]
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None
    content_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        require_token(self.event_version, "R5 lifecycle event_version")
        if self.stream_id != r5_relative_value_promotion_stream_id(self.scope):
            raise ValueError("R5 lifecycle stream identity is invalid")
        if self.scope != self.decision.scope or self.scope != self.authorization.scope:
            raise ValueError("R5 lifecycle event crosses semantic scopes")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("R5 lifecycle sequence must be positive")
        require_aware(self.occurred_at, "R5 lifecycle occurred_at")
        require_aware(self.recorded_at, "R5 lifecycle recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("R5 lifecycle record cannot predate occurrence")
        if self.sequence == 1:
            if (
                self.event_type is not R5RelativeValueLifecycleEventType.PROMOTED
                or self.previous_event_hash is not None
            ):
                raise ValueError("R5 lifecycle root must be an unlinked promotion")
        elif self.previous_event_hash is None:
            raise ValueError("non-root R5 lifecycle event requires a previous hash")
        else:
            require_sha256(self.previous_event_hash, "R5 lifecycle previous hash")
        if self.decision.outcome is not R5RelativeValuePromotionDecisionOutcome.APPROVED:
            raise ValueError("R5 lifecycle can reference only approved decisions")
        if self.event_type is R5RelativeValueLifecycleEventType.ROLLED_BACK:
            target = self.rollback_target
            if (
                target is None
                or target.scope != self.scope
                or target.outcome is not R5RelativeValuePromotionDecisionOutcome.APPROVED
                or not target.recorded_at <= self.occurred_at < target.valid_until
            ):
                raise ValueError("R5 lifecycle rollback target is invalid or inactive")
        elif self.rollback_target is not None:
            raise ValueError("non-rollback R5 event cannot carry a target")
        if (
            self.event_type
            in {
                R5RelativeValueLifecycleEventType.PROMOTED,
                R5RelativeValueLifecycleEventType.ROLLED_BACK,
            }
            and not self.decision.recorded_at <= self.occurred_at < self.decision.valid_until
        ):
            raise ValueError("R5 lifecycle decision is inactive at occurrence")
        if not (
            self.authorization.recorded_at <= self.occurred_at < self.authorization.valid_until
            and self.authorization.issued_at <= self.occurred_at
        ):
            raise ValueError("R5 lifecycle authorization is unavailable at occurrence")
        if (
            self.authorization.event_type is not self.event_type
            or self.authorization.decision != self.decision
            or self.authorization.rollback_target != self.rollback_target
            or self.authorization.reason_hash
            != r5_relative_value_lifecycle_reason_hash(self.reason_codes)
        ):
            raise ValueError("R5 lifecycle authorization does not match the event")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("R5 lifecycle event must remain research-only")
        require_sha256(self.content_hash, "R5 lifecycle event content_hash")
        expected = r5_relative_value_lifecycle_event_hash(self)
        if self.content_hash != expected or self.event_id != f"r5-rv-event:{expected}":
            raise ValueError("R5 lifecycle event content hash or identity mismatch")


def _event_payload(
    *,
    event_version: str,
    scope: R5RelativeValuePromotionScope,
    stream_id: str,
    event_type: R5RelativeValueLifecycleEventType,
    sequence: int,
    decision: R5RelativeValueDecisionIdentity,
    rollback_target: R5RelativeValueDecisionIdentity | None,
    authorization: R5RelativeValueLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
    previous_event_hash: str | None,
) -> dict[str, object]:
    return {
        "schema": "research-r5-relative-value-lifecycle-event.v1",
        "identity": (event_version, stream_id),
        "scope": (scope.scope_id, scope.content_hash),
        "event_type": event_type.value,
        "sequence": sequence,
        "decision": _identity_payload(decision),
        "rollback_target": (
            None if rollback_target is None else _identity_payload(rollback_target)
        ),
        "authorization": authorization.content_hash,
        "reason_codes": reason_codes,
        "window": (occurred_at, recorded_at),
        "previous_event_hash": previous_event_hash,
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r5_relative_value_lifecycle_event_hash(
    event: R5RelativeValueLifecycleEvent,
) -> str:
    """Recompute one exact content-addressed lifecycle event hash."""

    return canonical_hash(
        _event_payload(
            event_version=event.event_version,
            scope=event.scope,
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
    )


def create_r5_relative_value_lifecycle_root(
    *,
    event_version: str,
    decision: R5RelativeValuePromotionDecision,
    authorization: R5RelativeValueLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
) -> R5RelativeValueLifecycleEvent:
    """Create the immutable first promotion link for one R5 scope."""

    return _build_event(
        event_version=event_version,
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        sequence=1,
        decision=decision,
        rollback_target=None,
        authorization=authorization,
        reason_codes=reason_codes,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=None,
    )


def create_r5_relative_value_lifecycle_event(
    *,
    event_version: str,
    previous_events: tuple[R5RelativeValueLifecycleEvent, ...],
    event_type: R5RelativeValueLifecycleEventType,
    decision: R5RelativeValuePromotionDecision,
    rollback_target: R5RelativeValuePromotionDecision | None,
    authorization: R5RelativeValueLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
) -> R5RelativeValueLifecycleEvent:
    """Create the next legal event after replaying the exact scope stack."""

    stack, _ = _replay_chain(previous_events)
    previous = previous_events[-1]
    if (
        occurred_at < previous.occurred_at
        or occurred_at < previous.recorded_at
        or recorded_at < previous.recorded_at
    ):
        raise ValueError("R5 lifecycle dual clocks cannot move backwards")
    decision_identity = R5RelativeValueDecisionIdentity.from_decision(decision)
    target_identity = (
        None
        if rollback_target is None
        else R5RelativeValueDecisionIdentity.from_decision(rollback_target)
    )
    if decision_identity.scope != previous.scope:
        raise ValueError("R5 lifecycle cannot append across scopes")
    if target_identity is not None and target_identity.scope != previous.scope:
        raise ValueError("R5 lifecycle rollback cannot cross scopes")
    if event_type is R5RelativeValueLifecycleEventType.PROMOTED:
        if stack and stack[-1] == decision_identity:
            raise ValueError("R5 lifecycle cannot promote the active decision again")
    elif event_type is R5RelativeValueLifecycleEventType.RETIRED:
        if not stack or stack[-1] != decision_identity:
            raise ValueError("R5 retirement must target the active decision")
    elif len(stack) < 2 or stack[-1] != decision_identity or target_identity != stack[-2]:
        raise ValueError("R5 rollback target must be exactly stack[-2]")
    return _build_event(
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
    event_version: str,
    event_type: R5RelativeValueLifecycleEventType,
    sequence: int,
    decision: R5RelativeValuePromotionDecision,
    rollback_target: R5RelativeValuePromotionDecision | None,
    authorization: R5RelativeValueLifecycleAuthorization,
    reason_codes: tuple[str, ...],
    occurred_at: datetime,
    recorded_at: datetime,
    previous_event_hash: str | None,
) -> R5RelativeValueLifecycleEvent:
    ordered_reasons = tuple(sorted(reason_codes))
    decision_identity = R5RelativeValueDecisionIdentity.from_decision(decision)
    target_identity = (
        None
        if rollback_target is None
        else R5RelativeValueDecisionIdentity.from_decision(rollback_target)
    )
    scope = decision.scope
    values: _LifecycleEventValues = {
        "event_version": event_version,
        "scope": scope,
        "stream_id": r5_relative_value_promotion_stream_id(scope),
        "event_type": event_type,
        "sequence": sequence,
        "decision": decision_identity,
        "rollback_target": target_identity,
        "authorization": authorization,
        "reason_codes": ordered_reasons,
        "occurred_at": occurred_at,
        "recorded_at": recorded_at,
        "previous_event_hash": previous_event_hash,
    }
    digest = canonical_hash(_event_payload(**values))
    return R5RelativeValueLifecycleEvent(
        event_id=f"r5-rv-event:{digest}",
        content_hash=digest,
        research_only=True,
        must_not_use_for_decision=True,
        must_not_execute=True,
        **values,
    )


@dataclass(frozen=True)
class R5RelativeValueLifecycleSnapshot:
    """PIT state produced from one exact recorded-prefix replay."""

    scope: R5RelativeValuePromotionScope
    stream_id: str
    state: R5RelativeValueLifecycleState
    active_decision: R5RelativeValueDecisionIdentity | None
    latest_event_hash: str
    evaluated_at: datetime


def derive_r5_relative_value_lifecycle_state(
    events: tuple[R5RelativeValueLifecycleEvent, ...],
    *,
    evaluated_at: datetime,
) -> R5RelativeValueLifecycleSnapshot:
    """Verify a complete recorded prefix and derive current scope state."""

    require_aware(evaluated_at, "R5 lifecycle evaluated_at")
    if any(event.recorded_at > evaluated_at for event in events):
        raise ValueError("R5 lifecycle prefix contains future-unrecorded evidence")
    stack, last_type = _replay_chain(events)
    latest = events[-1]
    if not stack:
        state = R5RelativeValueLifecycleState.RETIRED
        active = None
    else:
        candidate = stack[-1]
        if not candidate.recorded_at <= evaluated_at < candidate.valid_until:
            state = R5RelativeValueLifecycleState.EXPIRED
            active = None
        else:
            state = (
                R5RelativeValueLifecycleState.ROLLED_BACK
                if last_type is R5RelativeValueLifecycleEventType.ROLLED_BACK
                else R5RelativeValueLifecycleState.PROMOTED
            )
            active = candidate
    return R5RelativeValueLifecycleSnapshot(
        scope=latest.scope,
        stream_id=latest.stream_id,
        state=state,
        active_decision=active,
        latest_event_hash=latest.content_hash,
        evaluated_at=evaluated_at,
    )


def _replay_chain(
    events: tuple[R5RelativeValueLifecycleEvent, ...],
) -> tuple[list[R5RelativeValueDecisionIdentity], R5RelativeValueLifecycleEventType]:
    if not events:
        raise ValueError("R5 lifecycle chain cannot be empty")
    stack: list[R5RelativeValueDecisionIdentity] = []
    expected_previous: str | None = None
    previous_occurred_at: datetime | None = None
    previous_recorded_at: datetime | None = None
    scope = events[0].scope
    stream_id = r5_relative_value_promotion_stream_id(scope)
    for expected_sequence, event in enumerate(events, start=1):
        if event.scope != scope or event.stream_id != stream_id:
            raise ValueError("R5 lifecycle chain crosses scopes")
        if event.sequence != expected_sequence or event.previous_event_hash != expected_previous:
            raise ValueError("R5 lifecycle chain is discontinuous")
        if previous_occurred_at is not None and event.occurred_at < previous_occurred_at:
            raise ValueError("R5 lifecycle occurred_at moves backwards")
        if previous_recorded_at is not None and event.recorded_at < previous_recorded_at:
            raise ValueError("R5 lifecycle recorded_at moves backwards")
        if previous_recorded_at is not None and event.occurred_at < previous_recorded_at:
            raise ValueError("R5 lifecycle occurrence predates the previous receipt")
        if event.event_type is R5RelativeValueLifecycleEventType.PROMOTED:
            if stack and stack[-1] == event.decision:
                raise ValueError("R5 lifecycle duplicates the active decision")
            stack.append(event.decision)
        elif event.event_type is R5RelativeValueLifecycleEventType.RETIRED:
            if not stack or stack[-1] != event.decision:
                raise ValueError("R5 retirement does not target the active decision")
            stack.clear()
        else:
            if len(stack) < 2 or stack[-1] != event.decision or event.rollback_target != stack[-2]:
                raise ValueError("R5 rollback does not target stack[-2]")
            stack.pop()
        expected_previous = event.content_hash
        previous_occurred_at = event.occurred_at
        previous_recorded_at = event.recorded_at
    return stack, events[-1].event_type


__all__ = [
    "R5RelativeValueDecisionIdentity",
    "R5RelativeValueLifecycleAuthorization",
    "R5RelativeValueLifecycleEvent",
    "R5RelativeValueLifecycleEventType",
    "R5RelativeValueLifecycleSnapshot",
    "R5RelativeValueLifecycleState",
    "create_r5_relative_value_lifecycle_event",
    "create_r5_relative_value_lifecycle_root",
    "derive_r5_relative_value_lifecycle_state",
    "r5_relative_value_lifecycle_authorization_hash",
    "r5_relative_value_lifecycle_event_hash",
    "r5_relative_value_lifecycle_reason_hash",
    "r5_relative_value_promotion_stream_id",
]
