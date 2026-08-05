"""Append-only, internal-only lifecycle contracts for R7 human review reminders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from apps.research.domain.scenario_probability_contracts import (
    ScenarioProbabilityResearchPolicy,
)
from apps.research.domain.scenario_research_evidence import (
    ScenarioPathStudyEvidence,
    conditional_probability_evidence_identity,
    transition_probability_evidence_identity,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)
from apps.research.domain.scenario_review_intent import ReviewReminderIntent


class ReminderEventType(str, Enum):
    """Append-only occurrence types in the internal review lifecycle."""

    SCHEDULED = "scheduled"
    DUE = "due"
    ESCALATED = "escalated"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"


class ReminderLifecycleState(str, Enum):
    """State derived exclusively from a validated event chain."""

    SCHEDULED = "scheduled"
    DUE = "due"
    ESCALATED = "escalated"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"


class ReminderLifecycleBlocked(ValueError):
    """Fail-closed lifecycle rejection carrying a stable reason code."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code


class ScenarioReviewReminderConflict(ValueError):
    """Stable idempotency conflict for reminder evidence."""

    reason_code = "scenario_review_reminder.idempotency.conflict"


@dataclass(frozen=True)
class ScenarioReviewReminderSchedulePolicy:
    """Versioned owner, expiry, and escalation evidence for one schedule."""

    schedule_version: str
    probability_policy_version: str
    probability_policy_hash: str
    expiry_delay: timedelta
    escalation_delay: timedelta
    maximum_escalation_level: int
    path_horizon_periods: int
    owner_evidence_hash: str
    escalation_policy_version: str
    escalation_policy_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        schedule_version: str,
        probability_policy_version: str,
        probability_policy_hash: str,
        expiry_delay: timedelta,
        escalation_delay: timedelta,
        maximum_escalation_level: int,
        path_horizon_periods: int,
        owner_evidence_hash: str,
        escalation_policy_version: str,
        escalation_policy_hash: str,
    ) -> ScenarioReviewReminderSchedulePolicy:
        """Create a policy whose hash seals every schedule control."""

        digest = _schedule_policy_hash(
            schedule_version=schedule_version,
            probability_policy_version=probability_policy_version,
            probability_policy_hash=probability_policy_hash,
            expiry_delay=expiry_delay,
            escalation_delay=escalation_delay,
            maximum_escalation_level=maximum_escalation_level,
            path_horizon_periods=path_horizon_periods,
            owner_evidence_hash=owner_evidence_hash,
            escalation_policy_version=escalation_policy_version,
            escalation_policy_hash=escalation_policy_hash,
        )
        return cls(
            schedule_version=schedule_version,
            probability_policy_version=probability_policy_version,
            probability_policy_hash=probability_policy_hash,
            expiry_delay=expiry_delay,
            escalation_delay=escalation_delay,
            maximum_escalation_level=maximum_escalation_level,
            path_horizon_periods=path_horizon_periods,
            owner_evidence_hash=owner_evidence_hash,
            escalation_policy_version=escalation_policy_version,
            escalation_policy_hash=escalation_policy_hash,
            content_hash=digest,
        )

    @classmethod
    def from_probability_policy(
        cls,
        *,
        probability_policy: ScenarioProbabilityResearchPolicy,
        schedule_version: str,
        expiry_delay: timedelta,
        escalation_delay: timedelta,
        maximum_escalation_level: int,
        path_horizon_periods: int,
        owner_evidence_hash: str,
        escalation_policy_version: str,
        escalation_policy_hash: str,
    ) -> ScenarioReviewReminderSchedulePolicy:
        """Project exact typed probability-policy identity into reminder scheduling."""

        if path_horizon_periods != probability_policy.path_horizon_periods:
            raise ValueError("reminder path horizon does not match probability policy")
        return cls.create(
            schedule_version=schedule_version,
            probability_policy_version=probability_policy.policy_version,
            probability_policy_hash=probability_policy.content_hash,
            expiry_delay=expiry_delay,
            escalation_delay=escalation_delay,
            maximum_escalation_level=maximum_escalation_level,
            path_horizon_periods=path_horizon_periods,
            owner_evidence_hash=owner_evidence_hash,
            escalation_policy_version=escalation_policy_version,
            escalation_policy_hash=escalation_policy_hash,
        )

    def __post_init__(self) -> None:
        """Reject defaultless ownership, unsafe delays, and forged policy hashes."""

        require_token(self.schedule_version, "schedule_version")
        require_token(self.probability_policy_version, "probability_policy_version")
        require_sha256(self.probability_policy_hash, "probability_policy_hash")
        require_token(self.escalation_policy_version, "escalation_policy_version")
        require_sha256(self.owner_evidence_hash, "owner_evidence_hash")
        require_sha256(self.escalation_policy_hash, "escalation_policy_hash")
        if self.expiry_delay <= timedelta(0):
            raise ValueError("expiry_delay must be positive")
        if self.escalation_delay <= timedelta(0):
            raise ValueError("escalation_delay must be positive")
        if (
            isinstance(self.maximum_escalation_level, bool)
            or not isinstance(self.maximum_escalation_level, int)
            or self.maximum_escalation_level < 1
        ):
            raise ValueError("maximum_escalation_level must be a positive integer")
        if (
            isinstance(self.path_horizon_periods, bool)
            or not isinstance(self.path_horizon_periods, int)
            or self.path_horizon_periods < 1
        ):
            raise ValueError("path_horizon_periods must be a positive integer")
        expected = _schedule_policy_hash(
            schedule_version=self.schedule_version,
            probability_policy_version=self.probability_policy_version,
            probability_policy_hash=self.probability_policy_hash,
            expiry_delay=self.expiry_delay,
            escalation_delay=self.escalation_delay,
            maximum_escalation_level=self.maximum_escalation_level,
            path_horizon_periods=self.path_horizon_periods,
            owner_evidence_hash=self.owner_evidence_hash,
            escalation_policy_version=self.escalation_policy_version,
            escalation_policy_hash=self.escalation_policy_hash,
        )
        require_sha256(self.content_hash, "schedule policy content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario review schedule policy content_hash mismatch")


@dataclass(frozen=True)
class ScenarioReviewPeriodEvidenceBinding:
    """Exact conditional and transition evidence identities for one path period."""

    period_index: int
    conditional_probability_identity_hashes: tuple[str, ...]
    transition_probability_identity_hashes: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        period_index: int,
        conditional_probability_identity_hashes: tuple[str, ...],
        transition_probability_identity_hashes: tuple[str, ...],
    ) -> ScenarioReviewPeriodEvidenceBinding:
        """Canonicalize exact source identities without deriving probabilities."""

        conditional = tuple(sorted(conditional_probability_identity_hashes))
        transitions = tuple(sorted(transition_probability_identity_hashes))
        digest = hash_components(
            "scenario-review-period-binding.v1",
            str(period_index),
            *conditional,
            "transition-identities",
            *transitions,
        )
        return cls(period_index, conditional, transitions, digest)

    def __post_init__(self) -> None:
        """Require complete, unique and canonical exact identities."""

        if isinstance(self.period_index, bool) or self.period_index < 1:
            raise ValueError("period_index must be a positive integer")
        if not self.conditional_probability_identity_hashes:
            raise ValueError("period binding requires conditional probability identities")
        if not self.transition_probability_identity_hashes:
            raise ValueError("period binding requires transition probability identities")
        for label, identities in (
            ("conditional", self.conditional_probability_identity_hashes),
            ("transition", self.transition_probability_identity_hashes),
        ):
            if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
                raise ValueError(f"{label} probability identities must be unique and canonical")
            for identity in identities:
                require_sha256(identity, f"{label} probability identity")
        expected = hash_components(
            "scenario-review-period-binding.v1",
            str(self.period_index),
            *self.conditional_probability_identity_hashes,
            "transition-identities",
            *self.transition_probability_identity_hashes,
        )
        require_sha256(self.content_hash, "period binding content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario review period binding content_hash mismatch")


@dataclass(frozen=True)
class ScenarioReviewReminder:
    """Immutable internal pull-outbox header for one exact forecast review intent."""

    reminder_version: str
    reminder_id: str
    intent: ReviewReminderIntent
    schedule_policy: ScenarioReviewReminderSchedulePolicy
    path_evidence_hash: str
    period_bindings: tuple[ScenarioReviewPeriodEvidenceBinding, ...]
    created_at: datetime
    due_at: datetime
    expires_at: datetime
    delivery_scope: str
    must_not_execute: bool
    external_dispatch_requested: bool
    auto_approval_requested: bool
    research_only: bool
    must_not_use_for_decision: bool
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        intent: ReviewReminderIntent,
        schedule_policy: ScenarioReviewReminderSchedulePolicy,
        path_evidence_hash: str,
        period_bindings: tuple[ScenarioReviewPeriodEvidenceBinding, ...],
    ) -> ScenarioReviewReminder:
        """Seal one deterministic schedule without sending or approving anything."""

        bindings = tuple(sorted(period_bindings, key=lambda item: item.period_index))
        expires_at = intent.review_due_at + schedule_policy.expiry_delay
        reminder_version = "scenario-review-reminder.v1"
        reminder_id = _reminder_identity_hash(
            reminder_version=reminder_version,
            intent=intent,
            schedule_policy=schedule_policy,
            path_evidence_hash=path_evidence_hash,
            period_bindings=bindings,
        )
        content_hash = _reminder_hash(
            reminder_version=reminder_version,
            reminder_id=reminder_id,
            intent=intent,
            schedule_policy=schedule_policy,
            path_evidence_hash=path_evidence_hash,
            period_bindings=bindings,
            created_at=intent.created_at,
            due_at=intent.review_due_at,
            expires_at=expires_at,
        )
        return cls(
            reminder_version=reminder_version,
            reminder_id=reminder_id,
            intent=intent,
            schedule_policy=schedule_policy,
            path_evidence_hash=path_evidence_hash,
            period_bindings=bindings,
            created_at=intent.created_at,
            due_at=intent.review_due_at,
            expires_at=expires_at,
            delivery_scope="internal_review",
            must_not_execute=True,
            external_dispatch_requested=False,
            auto_approval_requested=False,
            research_only=True,
            must_not_use_for_decision=True,
            content_hash=content_hash,
        )

    def __post_init__(self) -> None:
        """Validate exact bindings, deterministic clocks, and safety invariants."""

        require_token(self.reminder_version, "reminder_version")
        require_sha256(self.reminder_id, "reminder_id")
        require_sha256(self.path_evidence_hash, "path_evidence_hash")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.due_at, "due_at")
        _require_aware(self.expires_at, "expires_at")
        if self.created_at != self.intent.created_at or self.due_at != self.intent.review_due_at:
            raise ValueError("reminder schedule must match the exact review intent")
        if self.expires_at != self.due_at + self.schedule_policy.expiry_delay:
            raise ValueError("reminder expiry must match the versioned schedule policy")
        if self.schedule_policy.probability_policy_version != self.intent.policy_version:
            raise ValueError("reminder probability policy version mismatch")
        if self.schedule_policy.probability_policy_hash != self.intent.policy_content_hash:
            raise ValueError("reminder probability policy hash mismatch")
        indices = tuple(item.period_index for item in self.period_bindings)
        expected_indices = tuple(range(1, self.schedule_policy.path_horizon_periods + 1))
        if indices != expected_indices:
            raise ValueError(
                "reminder period bindings must be non-empty, contiguous, and match path horizon"
            )
        if self.delivery_scope != "internal_review":
            raise ValueError("reminder delivery_scope must be internal_review")
        if (
            not self.must_not_execute
            or self.external_dispatch_requested
            or self.auto_approval_requested
            or not self.research_only
            or not self.must_not_use_for_decision
        ):
            raise ValueError("scenario review reminder safety boundary was loosened")
        expected_reminder_id = _reminder_identity_hash(
            reminder_version=self.reminder_version,
            intent=self.intent,
            schedule_policy=self.schedule_policy,
            path_evidence_hash=self.path_evidence_hash,
            period_bindings=self.period_bindings,
        )
        if self.reminder_id != expected_reminder_id:
            raise ValueError("scenario review reminder_id mismatch")
        expected = _reminder_hash(
            reminder_version=self.reminder_version,
            reminder_id=self.reminder_id,
            intent=self.intent,
            schedule_policy=self.schedule_policy,
            path_evidence_hash=self.path_evidence_hash,
            period_bindings=self.period_bindings,
            created_at=self.created_at,
            due_at=self.due_at,
            expires_at=self.expires_at,
        )
        require_sha256(self.content_hash, "reminder content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario review reminder content_hash mismatch")


@dataclass(frozen=True)
class ScenarioReviewReminderEvent:
    """One immutable, hash-chained internal lifecycle occurrence."""

    event_version: str
    event_id: str
    reminder_id: str
    event_type: ReminderEventType
    sequence: int
    escalation_level: int
    occurred_at: datetime
    recorded_at: datetime
    actor_evidence_hash: str
    reason_code: str
    idempotency_key: str
    previous_event_hash: str | None
    delivery_scope: str
    must_not_execute: bool
    external_dispatch_requested: bool
    auto_approval_requested: bool
    research_only: bool
    must_not_use_for_decision: bool
    content_hash: str
    record_hash: str

    def __post_init__(self) -> None:
        """Reject malformed roots, broken evidence, or side-effect flags."""

        require_token(self.event_version, "event_version")
        require_sha256(self.event_id, "event_id")
        require_sha256(self.reminder_id, "event reminder_id")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("event sequence must be positive")
        if isinstance(self.escalation_level, bool) or self.escalation_level < 0:
            raise ValueError("event escalation_level cannot be negative")
        _require_aware(self.occurred_at, "event occurred_at")
        _require_aware(self.recorded_at, "event recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("event recorded_at cannot precede occurred_at")
        require_sha256(self.actor_evidence_hash, "actor_evidence_hash")
        require_token(self.reason_code, "event reason_code")
        require_token(self.idempotency_key, "event idempotency_key")
        if self.previous_event_hash is not None:
            require_sha256(self.previous_event_hash, "previous_event_hash")
        if self.delivery_scope != "internal_review":
            raise ValueError("reminder event delivery_scope must be internal_review")
        if (
            not self.must_not_execute
            or self.external_dispatch_requested
            or self.auto_approval_requested
            or not self.research_only
            or not self.must_not_use_for_decision
        ):
            raise ValueError("scenario review reminder event safety boundary was loosened")
        expected = _event_hash(
            event_version=self.event_version,
            event_id=self.event_id,
            reminder_id=self.reminder_id,
            event_type=self.event_type,
            sequence=self.sequence,
            escalation_level=self.escalation_level,
            occurred_at=self.occurred_at,
            actor_evidence_hash=self.actor_evidence_hash,
            reason_code=self.reason_code,
            idempotency_key=self.idempotency_key,
            previous_event_hash=self.previous_event_hash,
        )
        require_sha256(self.content_hash, "event content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario review reminder event content_hash mismatch")
        expected_record_hash = hash_components(
            self.content_hash,
            _utc_iso(self.recorded_at),
        )
        require_sha256(self.record_hash, "event record_hash")
        if self.record_hash != expected_record_hash:
            raise ValueError("scenario review reminder event record_hash mismatch")


@dataclass(frozen=True)
class ScenarioReviewReminderLedger:
    """Validated immutable reminder header and its complete event history."""

    reminder: ScenarioReviewReminder
    events: tuple[ScenarioReviewReminderEvent, ...]

    def __post_init__(self) -> None:
        """Require a valid root and hash chain."""

        derive_scenario_review_reminder_state(self.reminder, self.events)


def reconcile_scenario_review_reminder(
    *,
    reminder: ScenarioReviewReminder,
    events: tuple[ScenarioReviewReminderEvent, ...],
    as_of: datetime,
    recorded_at: datetime,
) -> tuple[ScenarioReviewReminderEvent, ...]:
    """Append deterministic internal occurrences due by ``as_of``; never dispatch."""

    _require_aware(as_of, "as_of")
    _require_aware(recorded_at, "recorded_at")
    if as_of < reminder.created_at:
        raise ValueError("reconciliation as_of cannot precede reminder creation")
    history = list(events)
    if history:
        state = derive_scenario_review_reminder_state(reminder, tuple(history))
        if state in {ReminderLifecycleState.ACKNOWLEDGED, ReminderLifecycleState.EXPIRED}:
            return tuple(history)
    else:
        history.append(
            _new_event(
                reminder=reminder,
                history=(),
                event_type=ReminderEventType.SCHEDULED,
                escalation_level=0,
                occurred_at=reminder.created_at,
                recorded_at=max(recorded_at, reminder.created_at),
                actor_evidence_hash=reminder.schedule_policy.owner_evidence_hash,
                reason_code="scenario_review_reminder.scheduled",
                idempotency_key=f"{reminder.reminder_id}:scheduled",
            )
        )
    if reminder.due_at <= as_of and not _has_type(history, ReminderEventType.DUE):
        history.append(
            _new_event(
                reminder=reminder,
                history=tuple(history),
                event_type=ReminderEventType.DUE,
                escalation_level=0,
                occurred_at=reminder.due_at,
                recorded_at=max(recorded_at, reminder.due_at),
                actor_evidence_hash=reminder.schedule_policy.owner_evidence_hash,
                reason_code="scenario_review_reminder.due",
                idempotency_key=f"{reminder.reminder_id}:due:{_utc_iso(reminder.due_at)}",
            )
        )
    current_level = max((item.escalation_level for item in history), default=0)
    for level in range(current_level + 1, reminder.schedule_policy.maximum_escalation_level + 1):
        threshold = reminder.due_at + reminder.schedule_policy.escalation_delay * level
        if threshold > as_of or threshold >= reminder.expires_at:
            break
        history.append(
            _new_event(
                reminder=reminder,
                history=tuple(history),
                event_type=ReminderEventType.ESCALATED,
                escalation_level=level,
                occurred_at=threshold,
                recorded_at=max(recorded_at, threshold),
                actor_evidence_hash=reminder.schedule_policy.escalation_policy_hash,
                reason_code="scenario_review_reminder.escalated",
                idempotency_key=(f"{reminder.reminder_id}:escalated:{level}:{_utc_iso(threshold)}"),
            )
        )
    if reminder.expires_at <= as_of and not _terminal(history):
        history.append(
            _new_event(
                reminder=reminder,
                history=tuple(history),
                event_type=ReminderEventType.EXPIRED,
                escalation_level=max((item.escalation_level for item in history), default=0),
                occurred_at=reminder.expires_at,
                recorded_at=max(recorded_at, reminder.expires_at),
                actor_evidence_hash=reminder.schedule_policy.escalation_policy_hash,
                reason_code="scenario_review_reminder.expired",
                idempotency_key=f"{reminder.reminder_id}:expired:{_utc_iso(reminder.expires_at)}",
            )
        )
    derive_scenario_review_reminder_state(reminder, tuple(history))
    return tuple(history)


def build_scenario_review_period_evidence_bindings(
    *,
    intent: ReviewReminderIntent,
    schedule_policy: ScenarioReviewReminderSchedulePolicy,
    path_evidence: ScenarioPathStudyEvidence,
) -> tuple[ScenarioReviewPeriodEvidenceBinding, ...]:
    """Project exact typed path estimates into forecast-bound period identities."""

    if intent.scenario_revision_id not in path_evidence.scenario_revision_ids:
        raise ValueError("path evidence does not contain the forecast scenario revision")
    if path_evidence.scenario_set_revision_id != intent.scenario_set_revision_id:
        raise ValueError("path evidence scenario-set revision does not match forecast intent")
    if path_evidence.generated_at > intent.created_at:
        raise ValueError("path evidence cannot postdate the invalidation review intent")
    if path_evidence.valid_until <= intent.created_at:
        raise ValueError("path evidence is expired at the invalidation review intent")
    shock_periods = {item.period_index for item in path_evidence.shocks}
    expected_periods = set(range(1, schedule_policy.path_horizon_periods + 1))
    if shock_periods != expected_periods:
        raise ValueError("path evidence horizon does not match reminder schedule")
    bindings: list[ScenarioReviewPeriodEvidenceBinding] = []
    for period_index in range(1, schedule_policy.path_horizon_periods + 1):
        conditionals = tuple(
            conditional_probability_evidence_identity(item)
            for item in path_evidence.conditional_probabilities
            if item.period_index == period_index
        )
        transitions = tuple(
            transition_probability_evidence_identity(item)
            for item in path_evidence.transition_probabilities
            if item.horizon_periods == period_index
        )
        bindings.append(
            ScenarioReviewPeriodEvidenceBinding.create(
                period_index=period_index,
                conditional_probability_identity_hashes=conditionals,
                transition_probability_identity_hashes=transitions,
            )
        )
    return tuple(bindings)


def acknowledge_scenario_review_reminder(
    *,
    reminder: ScenarioReviewReminder,
    events: tuple[ScenarioReviewReminderEvent, ...],
    acknowledged_at: datetime,
    recorded_at: datetime,
    actor_evidence_hash: str,
    reason_code: str,
    idempotency_key: str,
) -> ScenarioReviewReminderEvent:
    """Create human acknowledgement evidence without approval or execution effects."""

    _require_aware(acknowledged_at, "acknowledged_at")
    _require_aware(recorded_at, "recorded_at")
    require_sha256(actor_evidence_hash, "ack actor_evidence_hash")
    state = derive_scenario_review_reminder_state(reminder, events)
    if state in {ReminderLifecycleState.ACKNOWLEDGED, ReminderLifecycleState.EXPIRED}:
        raise ReminderLifecycleBlocked(
            "scenario_review_reminder.lifecycle.terminal",
            "terminal reminder cannot be acknowledged",
        )
    if acknowledged_at < reminder.due_at:
        raise ReminderLifecycleBlocked(
            "scenario_review_reminder.lifecycle.not_due",
            "reminder cannot be acknowledged before due_at",
        )
    if acknowledged_at >= reminder.expires_at:
        raise ReminderLifecycleBlocked(
            "scenario_review_reminder.lifecycle.expired",
            "reminder cannot be acknowledged at or after expires_at",
        )
    if not _has_type(events, ReminderEventType.DUE):
        raise ReminderLifecycleBlocked(
            "scenario_review_reminder.lifecycle.due_event_missing",
            "acknowledgement requires the deterministic due event",
        )
    return _new_event(
        reminder=reminder,
        history=events,
        event_type=ReminderEventType.ACKNOWLEDGED,
        escalation_level=max((item.escalation_level for item in events), default=0),
        occurred_at=acknowledged_at,
        recorded_at=recorded_at,
        actor_evidence_hash=actor_evidence_hash,
        reason_code=reason_code,
        idempotency_key=idempotency_key,
    )


def derive_scenario_review_reminder_state(
    reminder: ScenarioReviewReminder,
    events: tuple[ScenarioReviewReminderEvent, ...],
) -> ReminderLifecycleState:
    """Validate the complete root/hash chain and derive its terminal-safe state."""

    if not events:
        raise ValueError("scenario review reminder event root is missing")
    if events[0].event_type is not ReminderEventType.SCHEDULED:
        raise ValueError("scenario review reminder event root is missing")
    previous: ScenarioReviewReminderEvent | None = None
    state: ReminderLifecycleState | None = None
    expected_level = 0
    for index, event in enumerate(events, start=1):
        if event.reminder_id != reminder.reminder_id or event.sequence != index:
            raise ValueError("scenario review reminder event identity or sequence mismatch")
        expected_event_id = _event_identity_hash(
            reminder_id=reminder.reminder_id,
            event_type=event.event_type,
            escalation_level=event.escalation_level,
            occurred_at=event.occurred_at,
            idempotency_key=event.idempotency_key,
        )
        if event.event_id != expected_event_id:
            raise ValueError("scenario review reminder event_id mismatch")
        if index == 1:
            if (
                event.event_type is not ReminderEventType.SCHEDULED
                or event.previous_event_hash is not None
                or event.occurred_at != reminder.created_at
                or event.escalation_level != 0
            ):
                raise ValueError("scenario review reminder root event mismatch")
        else:
            assert previous is not None
            if event.previous_event_hash != previous.content_hash:
                raise ValueError("scenario review reminder event hash chain mismatch")
            if event.occurred_at < previous.occurred_at:
                raise ValueError("scenario review reminder events are not chronological")
            if state in {ReminderLifecycleState.ACKNOWLEDGED, ReminderLifecycleState.EXPIRED}:
                raise ValueError("scenario review reminder terminal state cannot transition")
        if event.event_type is ReminderEventType.SCHEDULED:
            if index != 1:
                raise ValueError("scheduled event must be the event root")
            _require_system_event(
                reminder=reminder,
                event=event,
                actor_evidence_hash=reminder.schedule_policy.owner_evidence_hash,
                reason_code="scenario_review_reminder.scheduled",
                idempotency_key=f"{reminder.reminder_id}:scheduled",
            )
            state = ReminderLifecycleState.SCHEDULED
        elif event.event_type is ReminderEventType.DUE:
            if (
                state is not ReminderLifecycleState.SCHEDULED
                or event.occurred_at != reminder.due_at
                or event.escalation_level != 0
            ):
                raise ValueError("due event must follow schedule at exact due_at")
            _require_system_event(
                reminder=reminder,
                event=event,
                actor_evidence_hash=reminder.schedule_policy.owner_evidence_hash,
                reason_code="scenario_review_reminder.due",
                idempotency_key=f"{reminder.reminder_id}:due:{_utc_iso(reminder.due_at)}",
            )
            state = ReminderLifecycleState.DUE
        elif event.event_type is ReminderEventType.ESCALATED:
            if state not in {ReminderLifecycleState.DUE, ReminderLifecycleState.ESCALATED}:
                raise ValueError("escalation requires a due reminder")
            expected_level += 1
            if event.escalation_level != expected_level:
                raise ValueError("reminder escalation levels must be contiguous")
            expected_at = (
                reminder.due_at + reminder.schedule_policy.escalation_delay * expected_level
            )
            if event.occurred_at != expected_at or event.occurred_at >= reminder.expires_at:
                raise ValueError("reminder escalation occurrence does not match policy")
            _require_system_event(
                reminder=reminder,
                event=event,
                actor_evidence_hash=reminder.schedule_policy.escalation_policy_hash,
                reason_code="scenario_review_reminder.escalated",
                idempotency_key=(
                    f"{reminder.reminder_id}:escalated:{expected_level}:" f"{_utc_iso(expected_at)}"
                ),
            )
            state = ReminderLifecycleState.ESCALATED
        elif event.event_type is ReminderEventType.ACKNOWLEDGED:
            if state not in {ReminderLifecycleState.DUE, ReminderLifecycleState.ESCALATED}:
                raise ValueError("acknowledgement requires a due reminder")
            if not reminder.due_at <= event.occurred_at < reminder.expires_at:
                raise ValueError("acknowledgement occurred outside the review window")
            state = ReminderLifecycleState.ACKNOWLEDGED
        elif event.event_type is ReminderEventType.EXPIRED:
            if state not in {ReminderLifecycleState.DUE, ReminderLifecycleState.ESCALATED}:
                raise ValueError("expiry requires a due reminder")
            if event.occurred_at != reminder.expires_at:
                raise ValueError("expiry event must occur at exact expires_at")
            _require_system_event(
                reminder=reminder,
                event=event,
                actor_evidence_hash=reminder.schedule_policy.escalation_policy_hash,
                reason_code="scenario_review_reminder.expired",
                idempotency_key=(f"{reminder.reminder_id}:expired:{_utc_iso(reminder.expires_at)}"),
            )
            state = ReminderLifecycleState.EXPIRED
        previous = event
    assert state is not None
    return state


def is_scenario_review_reminder_due(
    reminder: ScenarioReviewReminder,
    events: tuple[ScenarioReviewReminderEvent, ...],
    as_of: datetime,
) -> bool:
    """Return due only inside ``due_at <= as_of < expires_at`` and while open."""

    _require_aware(as_of, "as_of")
    if not reminder.due_at <= as_of < reminder.expires_at:
        return False
    state = derive_scenario_review_reminder_state(reminder, events)
    return state in {ReminderLifecycleState.DUE, ReminderLifecycleState.ESCALATED}


def _new_event(
    *,
    reminder: ScenarioReviewReminder,
    history: tuple[ScenarioReviewReminderEvent, ...],
    event_type: ReminderEventType,
    escalation_level: int,
    occurred_at: datetime,
    recorded_at: datetime,
    actor_evidence_hash: str,
    reason_code: str,
    idempotency_key: str,
) -> ScenarioReviewReminderEvent:
    sequence = len(history) + 1
    previous_event_hash = history[-1].content_hash if history else None
    event_version = "scenario-review-reminder-event.v1"
    event_id = _event_identity_hash(
        reminder_id=reminder.reminder_id,
        event_type=event_type,
        escalation_level=escalation_level,
        occurred_at=occurred_at,
        idempotency_key=idempotency_key,
    )
    content_hash = _event_hash(
        event_version=event_version,
        event_id=event_id,
        reminder_id=reminder.reminder_id,
        event_type=event_type,
        sequence=sequence,
        escalation_level=escalation_level,
        occurred_at=occurred_at,
        actor_evidence_hash=actor_evidence_hash,
        reason_code=reason_code,
        idempotency_key=idempotency_key,
        previous_event_hash=previous_event_hash,
    )
    record_hash = hash_components(content_hash, _utc_iso(recorded_at))
    return ScenarioReviewReminderEvent(
        event_version=event_version,
        event_id=event_id,
        reminder_id=reminder.reminder_id,
        event_type=event_type,
        sequence=sequence,
        escalation_level=escalation_level,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        actor_evidence_hash=actor_evidence_hash,
        reason_code=reason_code,
        idempotency_key=idempotency_key,
        previous_event_hash=previous_event_hash,
        delivery_scope="internal_review",
        must_not_execute=True,
        external_dispatch_requested=False,
        auto_approval_requested=False,
        research_only=True,
        must_not_use_for_decision=True,
        content_hash=content_hash,
        record_hash=record_hash,
    )


def _schedule_policy_hash(
    *,
    schedule_version: str,
    probability_policy_version: str,
    probability_policy_hash: str,
    expiry_delay: timedelta,
    escalation_delay: timedelta,
    maximum_escalation_level: int,
    path_horizon_periods: int,
    owner_evidence_hash: str,
    escalation_policy_version: str,
    escalation_policy_hash: str,
) -> str:
    return hash_components(
        schedule_version,
        probability_policy_version,
        probability_policy_hash,
        str(expiry_delay.total_seconds()),
        str(escalation_delay.total_seconds()),
        str(maximum_escalation_level),
        str(path_horizon_periods),
        owner_evidence_hash,
        escalation_policy_version,
        escalation_policy_hash,
    )


def _reminder_hash(
    *,
    reminder_version: str,
    reminder_id: str,
    intent: ReviewReminderIntent,
    schedule_policy: ScenarioReviewReminderSchedulePolicy,
    path_evidence_hash: str,
    period_bindings: tuple[ScenarioReviewPeriodEvidenceBinding, ...],
    created_at: datetime,
    due_at: datetime,
    expires_at: datetime,
) -> str:
    return hash_components(
        reminder_version,
        reminder_id,
        intent.content_hash,
        schedule_policy.content_hash,
        path_evidence_hash,
        *(item.content_hash for item in period_bindings),
        _utc_iso(created_at),
        _utc_iso(due_at),
        _utc_iso(expires_at),
        "internal_review",
        "True",
        "False",
        "False",
        "True",
        "True",
    )


def _reminder_identity_hash(
    *,
    reminder_version: str,
    intent: ReviewReminderIntent,
    schedule_policy: ScenarioReviewReminderSchedulePolicy,
    path_evidence_hash: str,
    period_bindings: tuple[ScenarioReviewPeriodEvidenceBinding, ...],
) -> str:
    return hash_components(
        reminder_version,
        intent.intent_id,
        intent.content_hash,
        schedule_policy.content_hash,
        path_evidence_hash,
        *(item.content_hash for item in period_bindings),
    )


def _event_hash(
    *,
    event_version: str,
    event_id: str,
    reminder_id: str,
    event_type: ReminderEventType,
    sequence: int,
    escalation_level: int,
    occurred_at: datetime,
    actor_evidence_hash: str,
    reason_code: str,
    idempotency_key: str,
    previous_event_hash: str | None,
) -> str:
    return hash_components(
        event_version,
        event_id,
        reminder_id,
        event_type.value,
        str(sequence),
        str(escalation_level),
        _utc_iso(occurred_at),
        actor_evidence_hash,
        reason_code,
        idempotency_key,
        previous_event_hash or "",
        "internal_review",
        "True",
        "False",
        "False",
        "True",
        "True",
    )


def _event_identity_hash(
    *,
    reminder_id: str,
    event_type: ReminderEventType,
    escalation_level: int,
    occurred_at: datetime,
    idempotency_key: str,
) -> str:
    return hash_components(
        "scenario-review-reminder-event.v1",
        reminder_id,
        event_type.value,
        str(escalation_level),
        _utc_iso(occurred_at),
        idempotency_key,
    )


def _require_system_event(
    *,
    reminder: ScenarioReviewReminder,
    event: ScenarioReviewReminderEvent,
    actor_evidence_hash: str,
    reason_code: str,
    idempotency_key: str,
) -> None:
    if (
        event.actor_evidence_hash != actor_evidence_hash
        or event.reason_code != reason_code
        or event.idempotency_key != idempotency_key
    ):
        raise ValueError("scenario review reminder system event evidence mismatch")


def _utc_iso(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(UTC).isoformat()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _has_type(
    events: list[ScenarioReviewReminderEvent] | tuple[ScenarioReviewReminderEvent, ...],
    event_type: ReminderEventType,
) -> bool:
    return any(item.event_type is event_type for item in events)


def _terminal(
    events: list[ScenarioReviewReminderEvent] | tuple[ScenarioReviewReminderEvent, ...],
) -> bool:
    return any(
        item.event_type in {ReminderEventType.ACKNOWLEDGED, ReminderEventType.EXPIRED}
        for item in events
    )


__all__ = [
    "ReminderEventType",
    "ReminderLifecycleBlocked",
    "ReminderLifecycleState",
    "ScenarioReviewPeriodEvidenceBinding",
    "ScenarioReviewReminder",
    "ScenarioReviewReminderConflict",
    "ScenarioReviewReminderEvent",
    "ScenarioReviewReminderLedger",
    "ScenarioReviewReminderSchedulePolicy",
    "acknowledge_scenario_review_reminder",
    "build_scenario_review_period_evidence_bindings",
    "derive_scenario_review_reminder_state",
    "is_scenario_review_reminder_due",
    "reconcile_scenario_review_reminder",
]
