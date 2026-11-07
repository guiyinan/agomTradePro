"""Typed, deterministic replay mechanics shared by research promotion lifecycles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Protocol, TypeVar

_ScopeT_co = TypeVar("_ScopeT_co", covariant=True)
_DecisionIdentityT_co = TypeVar("_DecisionIdentityT_co", covariant=True)
_EventTypeT_co = TypeVar("_EventTypeT_co", covariant=True)


class PromotionLifecycleIdentity(Protocol[_ScopeT_co]):
    """Read-only scope contract for a domain-specific decision identity."""

    @property
    def scope(self) -> _ScopeT_co:
        """Return the domain-specific stable scope."""


class PromotionLifecycleEvent(Protocol[_ScopeT_co, _DecisionIdentityT_co, _EventTypeT_co]):
    """Read-only event shape consumed without erasing its concrete domain types."""

    @property
    def scope(self) -> _ScopeT_co:
        """Return the domain-specific stable scope."""

    @property
    def stream_id(self) -> str:
        """Return the domain-specific stream identifier."""

    @property
    def sequence(self) -> int:
        """Return the one-based stream position."""

    @property
    def event_type(self) -> _EventTypeT_co:
        """Return the domain-specific lifecycle event enum value."""

    @property
    def decision(self) -> _DecisionIdentityT_co:
        """Return the complete domain-specific decision identity."""

    @property
    def rollback_target(self) -> _DecisionIdentityT_co | None:
        """Return the complete domain-specific rollback target, if present."""

    @property
    def occurred_at(self) -> datetime:
        """Return the event's effective time."""

    @property
    def recorded_at(self) -> datetime:
        """Return the event's known/receipt time."""

    @property
    def previous_event_hash(self) -> str | None:
        """Return the preceding event hash, if this is not the root."""

    @property
    def content_hash(self) -> str:
        """Return this event's domain-specific content hash."""


_ScopeT = TypeVar("_ScopeT")
_DecisionIdentityT = TypeVar("_DecisionIdentityT", bound=PromotionLifecycleIdentity[object])
_EventTypeT = TypeVar("_EventTypeT")


@dataclass(frozen=True)
class PromotionLifecycleReplay(Generic[_DecisionIdentityT, _EventTypeT]):
    """The exact active identity stack and final event type for a prefix."""

    stack: tuple[_DecisionIdentityT, ...]
    last_event_type: _EventTypeT


@dataclass(frozen=True)
class PromotionLifecycleAppendPosition:
    """Validated sequence and previous hash for one proposed append."""

    sequence: int
    previous_event_hash: str


def replay_promotion_lifecycle_prefix(
    events: tuple[PromotionLifecycleEvent[_ScopeT, _DecisionIdentityT, _EventTypeT], ...],
    *,
    stream_id_for_scope: Callable[[_ScopeT], str],
    promoted_type: _EventTypeT,
    retired_type: _EventTypeT,
    rolled_back_type: _EventTypeT,
    family: str,
) -> PromotionLifecycleReplay[_DecisionIdentityT, _EventTypeT]:
    """Validate and replay one complete ordered lifecycle prefix."""

    if not events:
        raise ValueError(f"{family} lifecycle chain cannot be empty")

    first_event = events[0]
    scope = first_event.scope
    expected_stream_id = stream_id_for_scope(scope)
    stack: list[_DecisionIdentityT] = []
    expected_previous: str | None = None
    previous_occurred_at: datetime | None = None
    previous_recorded_at: datetime | None = None

    for expected_sequence, event in enumerate(events, start=1):
        if event.scope != scope or event.stream_id != expected_stream_id:
            raise ValueError(f"{family} lifecycle chain crosses scopes")
        if event.sequence != expected_sequence or event.previous_event_hash != expected_previous:
            raise ValueError(f"{family} lifecycle chain is discontinuous")
        if previous_occurred_at is not None and event.occurred_at < previous_occurred_at:
            raise ValueError(f"{family} lifecycle occurred_at moves backwards")
        if previous_recorded_at is not None and event.recorded_at < previous_recorded_at:
            raise ValueError(f"{family} lifecycle recorded_at moves backwards")
        if previous_recorded_at is not None and event.occurred_at < previous_recorded_at:
            raise ValueError(f"{family} lifecycle occurrence predates the previous receipt")

        if event.event_type is promoted_type:
            if stack and stack[-1] == event.decision:
                raise ValueError(f"{family} lifecycle duplicates the active decision")
            stack.append(event.decision)
        elif event.event_type is retired_type:
            if not stack or stack[-1] != event.decision:
                raise ValueError(f"{family} retirement does not target the active decision")
            stack.clear()
        elif event.event_type is rolled_back_type:
            if len(stack) < 2 or stack[-1] != event.decision or event.rollback_target != stack[-2]:
                raise ValueError(f"{family} rollback does not target stack[-2]")
            stack.pop()
        else:
            raise ValueError(f"{family} lifecycle event type is invalid")

        expected_previous = event.content_hash
        previous_occurred_at = event.occurred_at
        previous_recorded_at = event.recorded_at

    return PromotionLifecycleReplay(
        stack=tuple(stack),
        last_event_type=events[-1].event_type,
    )


def validate_promotion_lifecycle_append_clocks(
    previous_event: PromotionLifecycleEvent[_ScopeT, _DecisionIdentityT, _EventTypeT],
    *,
    occurred_at: datetime,
    recorded_at: datetime,
    family: str,
) -> None:
    """Reject a proposed append whose effective/known clocks move backwards."""

    if (
        occurred_at < previous_event.occurred_at
        or occurred_at < previous_event.recorded_at
        or recorded_at < previous_event.recorded_at
    ):
        raise ValueError(f"{family} lifecycle dual clocks cannot move backwards")


def validate_promotion_lifecycle_transition(
    stack: tuple[_DecisionIdentityT, ...],
    *,
    previous_scope: _ScopeT,
    previous_sequence: int,
    previous_event_hash: str,
    event_type: _EventTypeT,
    decision: _DecisionIdentityT,
    rollback_target: _DecisionIdentityT | None,
    promoted_type: _EventTypeT,
    retired_type: _EventTypeT,
    rolled_back_type: _EventTypeT,
    family: str,
) -> PromotionLifecycleAppendPosition:
    """Validate scope and stack transition, then return the next chain position."""

    if decision.scope != previous_scope:
        raise ValueError(f"{family} lifecycle cannot append across scopes")
    if rollback_target is not None and rollback_target.scope != previous_scope:
        raise ValueError(f"{family} lifecycle rollback cannot cross scopes")

    if event_type is promoted_type:
        if stack and stack[-1] == decision:
            raise ValueError(f"{family} lifecycle cannot promote the active decision again")
    elif event_type is retired_type:
        if not stack or stack[-1] != decision:
            raise ValueError(f"{family} retirement must target the active decision")
    elif event_type is rolled_back_type and (
        len(stack) < 2 or stack[-1] != decision or rollback_target != stack[-2]
    ):
        raise ValueError(f"{family} rollback target must be exactly stack[-2]")
    elif event_type is not rolled_back_type:
        raise ValueError(f"{family} lifecycle event type is invalid")

    return PromotionLifecycleAppendPosition(
        sequence=previous_sequence + 1,
        previous_event_hash=previous_event_hash,
    )


__all__ = [
    "PromotionLifecycleAppendPosition",
    "PromotionLifecycleEvent",
    "PromotionLifecycleIdentity",
    "PromotionLifecycleReplay",
    "replay_promotion_lifecycle_prefix",
    "validate_promotion_lifecycle_append_clocks",
    "validate_promotion_lifecycle_transition",
]
