"""Research-only Promotion and retirement contracts for persisted R7 results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _clock_token(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _flag_token(value: bool) -> str:
    return "true" if value else "false"


class R7ResultLifecycleAction(str, Enum):
    """Manual owner actions for an internal research result record."""

    PROMOTE = "promote"
    RETIRE = "retire"


class R7ResultLifecycleStatus(str, Enum):
    """Derived, non-operational lifecycle state used only by internal audit."""

    UNPROMOTED = "unpromoted"
    PROMOTED = "promoted"
    RETIRED = "retired"


@dataclass(frozen=True)
class R7ResearchResultRef:
    """Exact immutable identity and content seal of one persisted R7 result."""

    result_id: str
    result_version: str
    content_hash: str

    def __post_init__(self) -> None:
        require_token(self.result_id, "R7 result ref result_id", maximum=192)
        require_token(self.result_version, "R7 result ref result_version", maximum=192)
        require_sha256(self.content_hash, "R7 result ref content_hash")


@dataclass(frozen=True, init=False)
class R7ResultPromotionAuthorization:
    """Exact Research-owner authorization; never a probability or trade approval."""

    authorization_id: str
    authorization_version: str
    result_ref: R7ResearchResultRef
    event_id: str
    event_version: str
    action: R7ResultLifecycleAction
    expected_sequence: int
    owner: str
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    reason_codes: tuple[str, ...]
    evidence_ref: str
    research_only: bool
    promotes_internal_research_record_only: bool
    publishes_model_probability: bool
    produces_decision: bool
    executes_orders: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        result_ref: R7ResearchResultRef,
        event_id: str,
        event_version: str,
        action: R7ResultLifecycleAction,
        expected_sequence: int,
        owner: str,
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        reason_codes: tuple[str, ...],
        evidence_ref: str,
        research_only: bool = True,
        promotes_internal_research_record_only: bool = True,
        publishes_model_probability: bool = False,
        produces_decision: bool = False,
        executes_orders: bool = False,
        must_not_use_for_decision: bool = True,
        must_not_execute: bool = True,
    ) -> None:
        values: dict[str, object] = {
            "authorization_id": authorization_id,
            "authorization_version": authorization_version,
            "result_ref": result_ref,
            "event_id": event_id,
            "event_version": event_version,
            "action": action,
            "expected_sequence": expected_sequence,
            "owner": owner,
            "issued_at": issued_at,
            "recorded_at": recorded_at,
            "valid_until": valid_until,
            "reason_codes": reason_codes,
            "evidence_ref": evidence_ref,
            "research_only": research_only,
            "promotes_internal_research_record_only": promotes_internal_research_record_only,
            "publishes_model_probability": publishes_model_probability,
            "produces_decision": produces_decision,
            "executes_orders": executes_orders,
            "must_not_use_for_decision": must_not_use_for_decision,
            "must_not_execute": must_not_execute,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("authorization_id", self.authorization_id),
            ("authorization_version", self.authorization_version),
            ("event_id", self.event_id),
            ("event_version", self.event_version),
        ):
            require_token(value, f"R7 result authorization {field_name}", maximum=192)
        require_token(self.owner, "R7 result authorization owner", maximum=96)
        if self.owner != "research":
            raise ValueError("R7 result authorization owner must be research")
        if not isinstance(self.action, R7ResultLifecycleAction):
            raise ValueError("R7 result authorization action is invalid")
        if isinstance(self.expected_sequence, bool) or self.expected_sequence < 1:
            raise ValueError("R7 result authorization sequence is invalid")
        for field_name, clock_value in (
            ("issued_at", self.issued_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            _require_aware(clock_value, f"R7 result authorization {field_name}")
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("R7 result authorization clocks are invalid")
        if (
            not self.reason_codes
            or len(self.reason_codes) != len(set(self.reason_codes))
            or self.reason_codes != tuple(sorted(self.reason_codes))
        ):
            raise ValueError(
                "R7 result authorization reasons must be unique and canonically ordered"
            )
        for reason_code in self.reason_codes:
            require_token(
                reason_code,
                "R7 result authorization reason_code",
                maximum=96,
            )
        require_token(
            self.evidence_ref,
            "R7 result authorization evidence_ref",
            maximum=300,
        )
        if not _safety_is_strict(self):
            raise ValueError("R7 result lifecycle must remain research-only")
        require_sha256(self.content_hash, "R7 result authorization content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R7 result authorization content_hash mismatch")

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical authorization seal."""

        return hash_components(
            "r7-result-promotion-authorization.v1",
            self.authorization_id,
            self.authorization_version,
            self.result_ref.result_id,
            self.result_ref.result_version,
            self.result_ref.content_hash,
            self.event_id,
            self.event_version,
            self.action.value,
            str(self.expected_sequence),
            self.owner,
            _clock_token(self.issued_at),
            _clock_token(self.recorded_at),
            _clock_token(self.valid_until),
            *self.reason_codes,
            self.evidence_ref,
            *(_flag_token(value) for value in _safety_values(self)),
        )

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this authorization may create a new event at ``as_of``."""

        _require_aware(as_of, "R7 result authorization as_of")
        return self.issued_at <= as_of < self.valid_until


@dataclass(frozen=True, init=False)
class R7ResultLifecycleEvent:
    """Immutable result-local lifecycle event with a strict hash-chain anchor."""

    event_id: str
    event_version: str
    result_ref: R7ResearchResultRef
    authorization_id: str
    authorization_version: str
    authorization_hash: str
    action: R7ResultLifecycleAction
    sequence: int
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None
    reason_codes: tuple[str, ...]
    research_only: bool
    promotes_internal_research_record_only: bool
    publishes_model_probability: bool
    produces_decision: bool
    executes_orders: bool
    must_not_use_for_decision: bool
    must_not_execute: bool
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        event_id: str,
        event_version: str,
        result_ref: R7ResearchResultRef,
        authorization_id: str,
        authorization_version: str,
        authorization_hash: str,
        action: R7ResultLifecycleAction,
        sequence: int,
        occurred_at: datetime,
        recorded_at: datetime,
        previous_event_hash: str | None,
        reason_codes: tuple[str, ...],
        research_only: bool = True,
        promotes_internal_research_record_only: bool = True,
        publishes_model_probability: bool = False,
        produces_decision: bool = False,
        executes_orders: bool = False,
        must_not_use_for_decision: bool = True,
        must_not_execute: bool = True,
    ) -> None:
        values: dict[str, object] = {
            "event_id": event_id,
            "event_version": event_version,
            "result_ref": result_ref,
            "authorization_id": authorization_id,
            "authorization_version": authorization_version,
            "authorization_hash": authorization_hash,
            "action": action,
            "sequence": sequence,
            "occurred_at": occurred_at,
            "recorded_at": recorded_at,
            "previous_event_hash": previous_event_hash,
            "reason_codes": reason_codes,
            "research_only": research_only,
            "promotes_internal_research_record_only": promotes_internal_research_record_only,
            "publishes_model_probability": publishes_model_probability,
            "produces_decision": produces_decision,
            "executes_orders": executes_orders,
            "must_not_use_for_decision": must_not_use_for_decision,
            "must_not_execute": must_not_execute,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "content_hash", self.calculated_content_hash)
        self.__post_init__()

    def __post_init__(self) -> None:
        for field_name, value in (
            ("event_id", self.event_id),
            ("event_version", self.event_version),
            ("authorization_id", self.authorization_id),
            ("authorization_version", self.authorization_version),
        ):
            require_token(value, f"R7 result lifecycle {field_name}", maximum=192)
        require_sha256(self.authorization_hash, "R7 lifecycle authorization_hash")
        if not isinstance(self.action, R7ResultLifecycleAction):
            raise ValueError("R7 result lifecycle action is invalid")
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("R7 result lifecycle sequence is invalid")
        _require_aware(self.occurred_at, "R7 result lifecycle occurred_at")
        _require_aware(self.recorded_at, "R7 result lifecycle recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("R7 result lifecycle recorded_at cannot precede occurrence")
        if self.previous_event_hash is not None:
            require_sha256(self.previous_event_hash, "R7 lifecycle previous_event_hash")
        if (
            not self.reason_codes
            or len(self.reason_codes) != len(set(self.reason_codes))
            or self.reason_codes != tuple(sorted(self.reason_codes))
        ):
            raise ValueError("R7 result lifecycle reasons must be unique and canonically ordered")
        for reason_code in self.reason_codes:
            require_token(reason_code, "R7 lifecycle reason_code", maximum=96)
        if not _safety_is_strict(self):
            raise ValueError("R7 result lifecycle events must remain research-only")
        require_sha256(self.content_hash, "R7 result lifecycle content_hash")
        if self.content_hash != self.calculated_content_hash:
            raise ValueError("R7 result lifecycle content_hash mismatch")

    @property
    def calculated_content_hash(self) -> str:
        """Return the canonical lifecycle event seal."""

        return hash_components(
            "r7-result-lifecycle-event.v1",
            self.event_id,
            self.event_version,
            self.result_ref.result_id,
            self.result_ref.result_version,
            self.result_ref.content_hash,
            self.authorization_id,
            self.authorization_version,
            self.authorization_hash,
            self.action.value,
            str(self.sequence),
            _clock_token(self.occurred_at),
            _clock_token(self.recorded_at),
            self.previous_event_hash or "",
            *self.reason_codes,
            *(_flag_token(value) for value in _safety_values(self)),
        )


@dataclass(frozen=True)
class R7ResultLifecycleState:
    """Derived PIT lifecycle state for internal research audit only."""

    result_ref: R7ResearchResultRef
    status: R7ResultLifecycleStatus
    sequence: int
    head_event_hash: str
    promoted_at: datetime
    retired_at: datetime | None


def create_r7_result_lifecycle_event(
    *,
    authorization: R7ResultPromotionAuthorization,
    occurred_at: datetime,
    recorded_at: datetime,
    previous_event_hash: str | None,
) -> R7ResultLifecycleEvent:
    """Create an event from an exact active owner authorization."""

    if not authorization.is_active_at(occurred_at):
        raise ValueError("R7 result lifecycle authorization is inactive at occurrence")
    if authorization.expected_sequence == 1 and previous_event_hash is not None:
        raise ValueError("R7 result lifecycle root cannot have a previous hash")
    if authorization.expected_sequence > 1 and previous_event_hash is None:
        raise ValueError("R7 result lifecycle continuation requires a previous hash")
    return R7ResultLifecycleEvent(
        event_id=authorization.event_id,
        event_version=authorization.event_version,
        result_ref=authorization.result_ref,
        authorization_id=authorization.authorization_id,
        authorization_version=authorization.authorization_version,
        authorization_hash=authorization.content_hash,
        action=authorization.action,
        sequence=authorization.expected_sequence,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        previous_event_hash=previous_event_hash,
        reason_codes=authorization.reason_codes,
    )


def derive_r7_result_lifecycle_state(
    events: tuple[R7ResultLifecycleEvent, ...],
    *,
    evaluated_at: datetime,
) -> R7ResultLifecycleState:
    """Replay a complete prefix and reject gaps, forks, look-ahead, and revival."""

    _require_aware(evaluated_at, "R7 result lifecycle evaluated_at")
    if not events:
        raise ValueError("R7 result lifecycle has no events")
    ordered = tuple(sorted(events, key=lambda item: item.sequence))
    result_ref = ordered[0].result_ref
    previous_hash: str | None = None
    previous_recorded_at: datetime | None = None
    status = R7ResultLifecycleStatus.UNPROMOTED
    promoted_at: datetime | None = None
    retired_at: datetime | None = None
    for expected_sequence, event in enumerate(ordered, start=1):
        if event.result_ref != result_ref:
            raise ValueError("R7 result lifecycle crosses result identities")
        if event.sequence != expected_sequence:
            raise ValueError("R7 result lifecycle sequence is discontinuous")
        if event.recorded_at > evaluated_at:
            raise ValueError("R7 result lifecycle contains future evidence")
        if previous_recorded_at is not None and event.recorded_at < previous_recorded_at:
            raise ValueError("R7 result lifecycle recording clocks are non-monotonic")
        if event.previous_event_hash != previous_hash:
            raise ValueError("R7 result lifecycle hash chain is broken")
        if expected_sequence == 1 and event.action is not R7ResultLifecycleAction.PROMOTE:
            raise ValueError("R7 result lifecycle root must promote")
        if status is R7ResultLifecycleStatus.RETIRED:
            raise ValueError("R7 result lifecycle retirement is terminal")
        if event.action is R7ResultLifecycleAction.PROMOTE:
            if status is not R7ResultLifecycleStatus.UNPROMOTED:
                raise ValueError("R7 result lifecycle promotes an already promoted item")
            status = R7ResultLifecycleStatus.PROMOTED
            promoted_at = event.occurred_at
        elif status is not R7ResultLifecycleStatus.PROMOTED:
            raise ValueError("R7 result lifecycle retires an unpromoted item")
        else:
            status = R7ResultLifecycleStatus.RETIRED
            retired_at = event.occurred_at
        previous_hash = event.content_hash
        previous_recorded_at = event.recorded_at
    if promoted_at is None or previous_hash is None:
        raise ValueError("R7 result lifecycle is missing its Promotion root")
    return R7ResultLifecycleState(
        result_ref=result_ref,
        status=status,
        sequence=len(ordered),
        head_event_hash=previous_hash,
        promoted_at=promoted_at,
        retired_at=retired_at,
    )


def _safety_values(
    item: R7ResultPromotionAuthorization | R7ResultLifecycleEvent,
) -> tuple[bool, ...]:
    return (
        item.research_only,
        item.promotes_internal_research_record_only,
        item.publishes_model_probability,
        item.produces_decision,
        item.executes_orders,
        item.must_not_use_for_decision,
        item.must_not_execute,
    )


def _safety_is_strict(
    item: R7ResultPromotionAuthorization | R7ResultLifecycleEvent,
) -> bool:
    return _safety_values(item) == (True, True, False, False, False, True, True)


__all__ = [
    "R7ResearchResultRef",
    "R7ResultLifecycleAction",
    "R7ResultLifecycleEvent",
    "R7ResultLifecycleState",
    "R7ResultLifecycleStatus",
    "R7ResultPromotionAuthorization",
    "create_r7_result_lifecycle_event",
    "derive_r7_result_lifecycle_state",
]
