"""Hash-chained lifecycle for governed optimization research results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from apps.portfolio.domain._optimization_canonical import (
    hash_components,
    require_aware,
    require_ordered_unique,
    require_sha256,
    require_token,
    utc_text,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.optimization_research_result import (
    GovernedOptimizationResearchResult,
)


class OptimizationLifecycleEventType(StrEnum):
    """Append-only result lifecycle events."""

    RECORDED = "recorded"
    PROMOTION_ATTESTED = "promotion_attested"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


class OptimizationLifecycleState(StrEnum):
    """State derived exclusively from the event chain."""

    RESEARCH = "research"
    PROMOTION_ATTESTED = "promotion_attested"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class OptimizationLifecycleOwnerAttestation:
    """Owner-signed identity for a retirement or rollback event."""

    attestation_id: str
    owner: str
    result_id: str
    result_hash: str
    event_type: OptimizationLifecycleEventType
    reason_hash: str
    issued_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        attestation_id: str,
        owner: str,
        result_id: str,
        result_hash: str,
        event_type: OptimizationLifecycleEventType,
        reason_hash: str,
        issued_at: datetime,
    ) -> OptimizationLifecycleOwnerAttestation:
        """Create canonical owner evidence without inferring authorization."""

        digest = lifecycle_owner_attestation_hash_values(
            attestation_id=attestation_id,
            owner=owner,
            result_id=result_id,
            result_hash=result_hash,
            event_type=event_type,
            reason_hash=reason_hash,
            issued_at=issued_at,
        )
        return cls(
            attestation_id=attestation_id,
            owner=owner,
            result_id=result_id,
            result_hash=result_hash,
            event_type=event_type,
            reason_hash=reason_hash,
            issued_at=issued_at,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Recompute exact result, event and reason identity."""

        require_token(self.attestation_id, "lifecycle attestation_id")
        require_token(self.owner, "lifecycle attestation owner")
        if self.owner != "portfolio":
            raise ValueError("optimization lifecycle owner must be portfolio")
        require_token(self.result_id, "lifecycle attestation result_id")
        require_sha256(self.result_hash, "lifecycle attestation result_hash")
        require_sha256(self.reason_hash, "lifecycle attestation reason_hash")
        require_aware(self.issued_at, "lifecycle attestation issued_at")
        if self.event_type not in {
            OptimizationLifecycleEventType.RETIRED,
            OptimizationLifecycleEventType.ROLLED_BACK,
        }:
            raise ValueError("owner attestation is only valid for retirement or rollback")
        require_sha256(self.content_hash, "lifecycle attestation content_hash")
        if self.content_hash != lifecycle_owner_attestation_hash(self):
            raise ValueError("lifecycle owner attestation content hash mismatch")


def lifecycle_owner_attestation_hash(
    attestation: OptimizationLifecycleOwnerAttestation,
) -> str:
    """Recompute a retirement/rollback owner attestation."""

    return lifecycle_owner_attestation_hash_values(
        attestation_id=attestation.attestation_id,
        owner=attestation.owner,
        result_id=attestation.result_id,
        result_hash=attestation.result_hash,
        event_type=attestation.event_type,
        reason_hash=attestation.reason_hash,
        issued_at=attestation.issued_at,
    )


def lifecycle_owner_attestation_hash_values(
    *,
    attestation_id: str,
    owner: str,
    result_id: str,
    result_hash: str,
    event_type: OptimizationLifecycleEventType,
    reason_hash: str,
    issued_at: datetime,
) -> str:
    """Hash all owner-attestation fields."""

    return hash_components(
        "optimization-lifecycle-owner-attestation.v1",
        attestation_id,
        owner,
        result_id,
        result_hash,
        event_type.value,
        reason_hash,
        utc_text(issued_at),
    )


@dataclass(frozen=True)
class OptimizationResearchLifecycleEvent:
    """One immutable hash-chain link for a governed result."""

    event_id: str
    result_id: str
    result_hash: str
    event_type: OptimizationLifecycleEventType
    sequence: int
    occurred_at: datetime
    recorded_at: datetime
    reason_codes: tuple[str, ...]
    previous_event_hash: str | None
    promotion_attestation: ExactPromotionAttestation | None
    owner_attestation: OptimizationLifecycleOwnerAttestation | None
    content_hash: str
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        """Validate event-specific evidence and recompute its chain hash."""

        require_token(self.event_id, "lifecycle event_id")
        require_token(self.result_id, "lifecycle result_id")
        require_sha256(self.result_hash, "lifecycle result_hash")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("lifecycle sequence must be positive")
        require_aware(self.occurred_at, "lifecycle occurred_at")
        require_aware(self.recorded_at, "lifecycle recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("lifecycle record cannot predate occurrence")
        if self.reason_codes:
            require_ordered_unique(self.reason_codes, "lifecycle reason codes")
        if self.sequence == 1:
            if (
                self.event_type is not OptimizationLifecycleEventType.RECORDED
                or self.previous_event_hash is not None
                or self.reason_codes
                or self.promotion_attestation is not None
                or self.owner_attestation is not None
            ):
                raise ValueError("lifecycle root evidence is invalid")
        else:
            if self.previous_event_hash is None:
                raise ValueError("non-root lifecycle event requires previous hash")
            require_sha256(self.previous_event_hash, "lifecycle previous_event_hash")
            if not self.reason_codes:
                raise ValueError("non-root lifecycle event requires reason codes")
        if self.event_type is OptimizationLifecycleEventType.PROMOTION_ATTESTED:
            promotion = self.promotion_attestation
            if promotion is None or self.owner_attestation is not None:
                raise ValueError("promotion lifecycle event requires exact Promotion only")
            if (
                promotion.capability_key != "r8"
                or promotion.artifact_id != self.result_id
                or promotion.artifact_content_hash != self.result_hash
                or promotion.owner != "research"
                or promotion.retired_at is not None
                or not promotion.approved_at <= self.occurred_at < promotion.valid_until
            ):
                raise ValueError("R8 Promotion attestation does not match the result")
        elif self.event_type in {
            OptimizationLifecycleEventType.RETIRED,
            OptimizationLifecycleEventType.ROLLED_BACK,
        }:
            owner = self.owner_attestation
            if owner is None or self.promotion_attestation is not None:
                raise ValueError("terminal lifecycle event requires owner attestation only")
            reason_hash = hash_components("optimization-lifecycle-reasons.v1", *self.reason_codes)
            if (
                owner.result_id != self.result_id
                or owner.result_hash != self.result_hash
                or owner.event_type is not self.event_type
                or owner.reason_hash != reason_hash
                or not owner.issued_at <= self.occurred_at <= self.recorded_at
            ):
                raise ValueError("lifecycle owner attestation does not match the event")
        elif self.event_type is not OptimizationLifecycleEventType.RECORDED:
            raise ValueError("unsupported optimization lifecycle event")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("optimization lifecycle must remain research-only")
        require_sha256(self.content_hash, "lifecycle content_hash")
        if self.content_hash != optimization_lifecycle_event_hash(self):
            raise ValueError("optimization lifecycle event content hash mismatch")


def create_optimization_lifecycle_root(
    result: GovernedOptimizationResearchResult,
) -> OptimizationResearchLifecycleEvent:
    """Create the deterministic first chain link for a persisted result."""

    content_hash = optimization_lifecycle_event_hash_values(
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=OptimizationLifecycleEventType.RECORDED,
        sequence=1,
        occurred_at=result.evaluated_at,
        recorded_at=result.evaluated_at,
        reason_codes=(),
        previous_event_hash=None,
        promotion_attestation=None,
        owner_attestation=None,
    )
    return OptimizationResearchLifecycleEvent(
        event_id=f"optimization_lifecycle_event:{content_hash[:24]}",
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=OptimizationLifecycleEventType.RECORDED,
        sequence=1,
        occurred_at=result.evaluated_at,
        recorded_at=result.evaluated_at,
        reason_codes=(),
        previous_event_hash=None,
        promotion_attestation=None,
        owner_attestation=None,
        content_hash=content_hash,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )


def create_optimization_lifecycle_event(
    *,
    result: GovernedOptimizationResearchResult,
    previous_events: tuple[OptimizationResearchLifecycleEvent, ...],
    event_type: OptimizationLifecycleEventType,
    occurred_at: datetime,
    recorded_at: datetime,
    reason_codes: tuple[str, ...],
    promotion_attestation: ExactPromotionAttestation | None = None,
    owner_attestation: OptimizationLifecycleOwnerAttestation | None = None,
) -> OptimizationResearchLifecycleEvent:
    """Create the next valid event; transition legality is chain-derived."""

    require_aware(occurred_at, "lifecycle occurred_at")
    require_aware(recorded_at, "lifecycle recorded_at")
    state = derive_optimization_lifecycle_state(previous_events)
    previous_event = previous_events[-1]
    if (
        previous_event.result_id != result.result_id
        or previous_event.result_hash != result.content_hash
    ):
        raise ValueError("optimization lifecycle result identity does not match its chain")
    if occurred_at < previous_event.occurred_at:
        raise ValueError("optimization lifecycle occurred_at cannot move backwards")
    if recorded_at < previous_event.recorded_at:
        raise ValueError("optimization lifecycle recorded_at cannot move backwards")
    allowed: dict[OptimizationLifecycleState, set[OptimizationLifecycleEventType]] = {
        OptimizationLifecycleState.RESEARCH: {
            OptimizationLifecycleEventType.PROMOTION_ATTESTED,
            OptimizationLifecycleEventType.RETIRED,
        },
        OptimizationLifecycleState.PROMOTION_ATTESTED: {
            OptimizationLifecycleEventType.RETIRED,
            OptimizationLifecycleEventType.ROLLED_BACK,
        },
        OptimizationLifecycleState.RETIRED: set(),
        OptimizationLifecycleState.ROLLED_BACK: set(),
    }
    if event_type not in allowed[state]:
        raise ValueError("optimization lifecycle transition is invalid")
    ordered_reasons = tuple(sorted(reason_codes))
    sequence = previous_event.sequence + 1
    digest = optimization_lifecycle_event_hash_values(
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=event_type,
        sequence=sequence,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        reason_codes=ordered_reasons,
        previous_event_hash=previous_event.content_hash,
        promotion_attestation=promotion_attestation,
        owner_attestation=owner_attestation,
    )
    return OptimizationResearchLifecycleEvent(
        event_id=f"optimization_lifecycle_event:{digest[:24]}",
        result_id=result.result_id,
        result_hash=result.content_hash,
        event_type=event_type,
        sequence=sequence,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        reason_codes=ordered_reasons,
        previous_event_hash=previous_event.content_hash,
        promotion_attestation=promotion_attestation,
        owner_attestation=owner_attestation,
        content_hash=digest,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )


def optimization_lifecycle_event_hash(
    event: OptimizationResearchLifecycleEvent,
) -> str:
    """Recompute one lifecycle chain link."""

    return optimization_lifecycle_event_hash_values(
        result_id=event.result_id,
        result_hash=event.result_hash,
        event_type=event.event_type,
        sequence=event.sequence,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        reason_codes=event.reason_codes,
        previous_event_hash=event.previous_event_hash,
        promotion_attestation=event.promotion_attestation,
        owner_attestation=event.owner_attestation,
    )


def optimization_lifecycle_event_hash_values(
    *,
    result_id: str,
    result_hash: str,
    event_type: OptimizationLifecycleEventType,
    sequence: int,
    occurred_at: datetime,
    recorded_at: datetime,
    reason_codes: tuple[str, ...],
    previous_event_hash: str | None,
    promotion_attestation: ExactPromotionAttestation | None,
    owner_attestation: OptimizationLifecycleOwnerAttestation | None,
) -> str:
    """Hash the full event evidence and previous link."""

    return hash_components(
        "optimization-research-lifecycle-event.v1",
        result_id,
        result_hash,
        event_type.value,
        str(sequence),
        utc_text(occurred_at),
        utc_text(recorded_at),
        *reason_codes,
        previous_event_hash or "",
        promotion_attestation.attestation_hash if promotion_attestation is not None else "",
        owner_attestation.content_hash if owner_attestation is not None else "",
        "research_only",
        "must_not_execute",
        "must_not_use_for_decision",
    )


def derive_optimization_lifecycle_state(
    events: tuple[OptimizationResearchLifecycleEvent, ...],
) -> OptimizationLifecycleState:
    """Verify a complete ordered chain and derive its current state."""

    if not events or events[0].event_type is not OptimizationLifecycleEventType.RECORDED:
        raise ValueError("optimization lifecycle requires a recorded root")
    expected_previous: str | None = None
    previous_occurred_at: datetime | None = None
    previous_recorded_at: datetime | None = None
    state = OptimizationLifecycleState.RESEARCH
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence or event.previous_event_hash != expected_previous:
            raise ValueError("optimization lifecycle chain is discontinuous")
        if event.result_id != events[0].result_id or event.result_hash != events[0].result_hash:
            raise ValueError("optimization lifecycle chain changes result identity")
        if previous_occurred_at is not None and event.occurred_at < previous_occurred_at:
            raise ValueError("optimization lifecycle occurred_at moves backwards")
        if previous_recorded_at is not None and event.recorded_at < previous_recorded_at:
            raise ValueError("optimization lifecycle recorded_at moves backwards")
        if event.event_type is OptimizationLifecycleEventType.PROMOTION_ATTESTED:
            if state is not OptimizationLifecycleState.RESEARCH:
                raise ValueError("optimization Promotion transition is invalid")
            state = OptimizationLifecycleState.PROMOTION_ATTESTED
        elif event.event_type is OptimizationLifecycleEventType.RETIRED:
            if state not in {
                OptimizationLifecycleState.RESEARCH,
                OptimizationLifecycleState.PROMOTION_ATTESTED,
            }:
                raise ValueError("optimization retirement transition is invalid")
            state = OptimizationLifecycleState.RETIRED
        elif event.event_type is OptimizationLifecycleEventType.ROLLED_BACK:
            if state is not OptimizationLifecycleState.PROMOTION_ATTESTED:
                raise ValueError("optimization rollback transition is invalid")
            state = OptimizationLifecycleState.ROLLED_BACK
        elif event.sequence != 1:
            raise ValueError("recorded event may only be the chain root")
        expected_previous = event.content_hash
        previous_occurred_at = event.occurred_at
        previous_recorded_at = event.recorded_at
    return state


__all__ = [
    "OptimizationLifecycleEventType",
    "OptimizationLifecycleOwnerAttestation",
    "OptimizationLifecycleState",
    "OptimizationResearchLifecycleEvent",
    "create_optimization_lifecycle_event",
    "create_optimization_lifecycle_root",
    "derive_optimization_lifecycle_state",
    "lifecycle_owner_attestation_hash",
    "optimization_lifecycle_event_hash",
]
