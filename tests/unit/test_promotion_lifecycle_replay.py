"""Pure contract tests for the shared research lifecycle replay mechanics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import pytest

from apps.research.domain.promotion_lifecycle_replay import (
    PromotionLifecycleReplay,
    replay_promotion_lifecycle_prefix,
    validate_promotion_lifecycle_append_clocks,
    validate_promotion_lifecycle_transition,
)


class _EventType(StrEnum):
    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class _Scope:
    scope_id: str


@dataclass(frozen=True)
class _DecisionIdentity:
    scope: _Scope
    identity: str
    valid_until: datetime | None = None


@dataclass(frozen=True)
class _Event:
    scope: _Scope
    stream_id: str
    sequence: int
    event_type: _EventType
    decision: _DecisionIdentity
    rollback_target: _DecisionIdentity | None
    occurred_at: datetime
    recorded_at: datetime
    previous_event_hash: str | None
    content_hash: str


_BASE_TIME = datetime(2026, 11, 7, tzinfo=UTC)
_SCOPE = _Scope("scope-a")


def _stream_id_for_scope(scope: _Scope) -> str:
    """Return the fixture stream ID for one scope."""

    return f"research:test:{scope.scope_id}"


def _make_event(
    *,
    sequence: int,
    event_type: _EventType,
    decision: _DecisionIdentity,
    previous_event_hash: str | None,
    rollback_target: _DecisionIdentity | None = None,
    scope: _Scope = _SCOPE,
    occurred_offset_seconds: int | None = None,
    recorded_offset_seconds: int | None = None,
) -> _Event:
    """Construct a small typed event fixture without a persistence dependency."""

    occurred_offset = sequence * 10 if occurred_offset_seconds is None else occurred_offset_seconds
    recorded_offset = (
        occurred_offset + 1 if recorded_offset_seconds is None else recorded_offset_seconds
    )
    return _Event(
        scope=scope,
        stream_id=_stream_id_for_scope(scope),
        sequence=sequence,
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        occurred_at=_BASE_TIME + timedelta(seconds=occurred_offset),
        recorded_at=_BASE_TIME + timedelta(seconds=recorded_offset),
        previous_event_hash=previous_event_hash,
        content_hash=f"event-hash-{sequence}",
    )


def _replay(
    events: tuple[_Event, ...],
) -> PromotionLifecycleReplay[_DecisionIdentity, _EventType]:
    """Replay fixtures using the typed enum values and stream resolver."""

    return replay_promotion_lifecycle_prefix(
        events,
        stream_id_for_scope=_stream_id_for_scope,
        promoted_type=_EventType.PROMOTED,
        retired_type=_EventType.RETIRED,
        rolled_back_type=_EventType.ROLLED_BACK,
        family="test",
    )


def test_replay_preserves_order_and_allows_non_active_identity_repetition() -> None:
    first = _DecisionIdentity(_SCOPE, "decision-a")
    second = _DecisionIdentity(_SCOPE, "decision-b")
    events = (
        _make_event(
            sequence=1,
            event_type=_EventType.PROMOTED,
            decision=first,
            previous_event_hash=None,
        ),
        _make_event(
            sequence=2,
            event_type=_EventType.PROMOTED,
            decision=second,
            previous_event_hash="event-hash-1",
        ),
        _make_event(
            sequence=3,
            event_type=_EventType.PROMOTED,
            decision=first,
            previous_event_hash="event-hash-2",
        ),
    )

    replay = _replay(events)

    assert replay.stack == (first, second, first)
    assert replay.last_event_type is _EventType.PROMOTED


def test_replay_rejects_duplicate_active_identity_and_wrong_rollback_target() -> None:
    first = _DecisionIdentity(_SCOPE, "decision-a")
    second = _DecisionIdentity(_SCOPE, "decision-b")
    root = _make_event(
        sequence=1,
        event_type=_EventType.PROMOTED,
        decision=first,
        previous_event_hash=None,
    )
    promoted = _make_event(
        sequence=2,
        event_type=_EventType.PROMOTED,
        decision=second,
        previous_event_hash=root.content_hash,
    )
    duplicate = _make_event(
        sequence=3,
        event_type=_EventType.PROMOTED,
        decision=second,
        previous_event_hash=promoted.content_hash,
    )
    wrong_rollback = _make_event(
        sequence=3,
        event_type=_EventType.ROLLED_BACK,
        decision=second,
        rollback_target=second,
        previous_event_hash=promoted.content_hash,
    )

    with pytest.raises(ValueError, match="duplicates the active decision"):
        _replay((root, promoted, duplicate))
    with pytest.raises(ValueError, match=r"rollback does not target stack\[-2\]"):
        _replay((root, promoted, wrong_rollback))


def test_unknown_kind_cannot_use_valid_rollback_payload() -> None:
    first = _DecisionIdentity(_SCOPE, "decision-a")
    second = _DecisionIdentity(_SCOPE, "decision-b")
    root = _make_event(
        sequence=1,
        event_type=_EventType.PROMOTED,
        decision=first,
        previous_event_hash=None,
    )
    promoted = _make_event(
        sequence=2,
        event_type=_EventType.PROMOTED,
        decision=second,
        previous_event_hash=root.content_hash,
    )
    unknown = _make_event(
        sequence=3,
        event_type=_EventType.UNKNOWN,
        decision=second,
        rollback_target=first,
        previous_event_hash=promoted.content_hash,
    )
    replay = _replay((root, promoted))

    with pytest.raises(ValueError, match="event type is invalid"):
        _replay((root, promoted, unknown))
    with pytest.raises(ValueError, match="event type is invalid"):
        validate_promotion_lifecycle_transition(
            replay.stack,
            previous_scope=_SCOPE,
            previous_sequence=promoted.sequence,
            previous_event_hash=promoted.content_hash,
            event_type=_EventType.UNKNOWN,
            decision=second,
            rollback_target=first,
            promoted_type=_EventType.PROMOTED,
            retired_type=_EventType.RETIRED,
            rolled_back_type=_EventType.ROLLED_BACK,
            family="test",
        )


def test_retirement_clears_the_stack_and_rollback_pops_only_one_item() -> None:
    first = _DecisionIdentity(_SCOPE, "decision-a")
    second = _DecisionIdentity(_SCOPE, "decision-b")
    root = _make_event(
        sequence=1,
        event_type=_EventType.PROMOTED,
        decision=first,
        previous_event_hash=None,
    )
    promoted = _make_event(
        sequence=2,
        event_type=_EventType.PROMOTED,
        decision=second,
        previous_event_hash=root.content_hash,
    )
    rolled_back = _make_event(
        sequence=3,
        event_type=_EventType.ROLLED_BACK,
        decision=second,
        rollback_target=first,
        previous_event_hash=promoted.content_hash,
    )
    retired = _make_event(
        sequence=4,
        event_type=_EventType.RETIRED,
        decision=first,
        previous_event_hash=rolled_back.content_hash,
    )

    after_rollback = _replay((root, promoted, rolled_back))
    after_retirement = _replay((root, promoted, rolled_back, retired))

    assert after_rollback.stack == (first,)
    assert after_rollback.last_event_type is _EventType.ROLLED_BACK
    assert after_retirement.stack == ()
    assert after_retirement.last_event_type is _EventType.RETIRED


def test_retirement_may_clear_an_expired_active_identity() -> None:
    expired_decision = _DecisionIdentity(
        _SCOPE,
        "expired-decision",
        valid_until=_BASE_TIME + timedelta(seconds=15),
    )
    root = _make_event(
        sequence=1,
        event_type=_EventType.PROMOTED,
        decision=expired_decision,
        previous_event_hash=None,
    )
    retired = _make_event(
        sequence=2,
        event_type=_EventType.RETIRED,
        decision=expired_decision,
        previous_event_hash=root.content_hash,
    )

    replay = _replay((root, retired))

    assert replay.stack == ()
    assert replay.last_event_type is _EventType.RETIRED


def test_append_position_checks_clocks_then_exact_scope_and_stack_transition() -> None:
    first = _DecisionIdentity(_SCOPE, "decision-a")
    second = _DecisionIdentity(_SCOPE, "decision-b")
    root = _make_event(
        sequence=1,
        event_type=_EventType.PROMOTED,
        decision=first,
        previous_event_hash=None,
    )
    promoted = _make_event(
        sequence=2,
        event_type=_EventType.PROMOTED,
        decision=second,
        previous_event_hash=root.content_hash,
    )
    replay = _replay((root, promoted))
    occurred_at = promoted.recorded_at
    recorded_at = occurred_at + timedelta(seconds=1)

    validate_promotion_lifecycle_append_clocks(
        promoted,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        family="test",
    )
    position = validate_promotion_lifecycle_transition(
        replay.stack,
        previous_scope=_SCOPE,
        previous_sequence=promoted.sequence,
        previous_event_hash=promoted.content_hash,
        event_type=_EventType.ROLLED_BACK,
        decision=second,
        rollback_target=first,
        promoted_type=_EventType.PROMOTED,
        retired_type=_EventType.RETIRED,
        rolled_back_type=_EventType.ROLLED_BACK,
        family="test",
    )

    assert position.sequence == 3
    assert position.previous_event_hash == promoted.content_hash
    with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
        validate_promotion_lifecycle_append_clocks(
            promoted,
            occurred_at=promoted.occurred_at,
            recorded_at=promoted.recorded_at - timedelta(seconds=1),
            family="test",
        )
    with pytest.raises(ValueError, match="cannot append across scopes"):
        validate_promotion_lifecycle_transition(
            replay.stack,
            previous_scope=_Scope("scope-b"),
            previous_sequence=promoted.sequence,
            previous_event_hash=promoted.content_hash,
            event_type=_EventType.ROLLED_BACK,
            decision=second,
            rollback_target=first,
            promoted_type=_EventType.PROMOTED,
            retired_type=_EventType.RETIRED,
            rolled_back_type=_EventType.ROLLED_BACK,
            family="test",
        )


def test_replay_rejects_scope_sequence_hash_and_effective_time_discontinuity() -> None:
    first = _DecisionIdentity(_SCOPE, "decision-a")
    other_scope = _Scope("scope-b")
    root = _make_event(
        sequence=1,
        event_type=_EventType.PROMOTED,
        decision=first,
        previous_event_hash=None,
        occurred_offset_seconds=10,
        recorded_offset_seconds=15,
    )
    cross_scope = _make_event(
        sequence=2,
        event_type=_EventType.PROMOTED,
        decision=_DecisionIdentity(other_scope, "decision-b"),
        previous_event_hash=root.content_hash,
        scope=other_scope,
    )
    discontinuous = _make_event(
        sequence=3,
        event_type=_EventType.PROMOTED,
        decision=first,
        previous_event_hash=root.content_hash,
    )
    forked_hash = _make_event(
        sequence=2,
        event_type=_EventType.PROMOTED,
        decision=first,
        previous_event_hash="different-event-hash",
    )
    occurrence_before_receipt = _make_event(
        sequence=2,
        event_type=_EventType.PROMOTED,
        decision=first,
        previous_event_hash=root.content_hash,
        occurred_offset_seconds=12,
        recorded_offset_seconds=20,
    )

    with pytest.raises(ValueError, match="chain crosses scopes"):
        _replay((root, cross_scope))
    with pytest.raises(ValueError, match="chain is discontinuous"):
        _replay((root, discontinuous))
    with pytest.raises(ValueError, match="chain is discontinuous"):
        _replay((root, forked_hash))
    with pytest.raises(ValueError, match="occurrence predates the previous receipt"):
        _replay((root, occurrence_before_receipt))
