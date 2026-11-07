"""Cross-family contract checks for the existing R4 and R5 lifecycles.

These tests intentionally use the original typed family APIs and domain
factories. The same cases run against the unchanged baseline and the adopted
common replay implementation.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionDecisionIdentity,
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEvent,
    R4PromotionLifecycleEventType,
    R4PromotionLifecycleState,
    create_r4_promotion_lifecycle_event,
    create_r4_promotion_lifecycle_root,
    derive_r4_promotion_lifecycle_state,
)
from apps.research.domain.r4_promotion_scope_policy import R4PromotionScope
from apps.research.domain.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionDecision,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueDecisionIdentity,
    R5RelativeValueLifecycleAuthorization,
    R5RelativeValueLifecycleEvent,
    R5RelativeValueLifecycleEventType,
    R5RelativeValueLifecycleState,
    create_r5_relative_value_lifecycle_event,
    create_r5_relative_value_lifecycle_root,
    derive_r5_relative_value_lifecycle_state,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionScope,
)
from tests.unit.research.r4_promotion_factories import (
    DECIDED_AT,
    DECISION_RECORDED_AT,
    promotion_decision,
)
from tests.unit.research.r5_relative_value_promotion_factories import (
    make_decision,
)

_REASONS = ("research_owner_approved",)


def _r4_decisions() -> tuple[
    R4PromotionDecision,
    R4PromotionDecision,
    R4PromotionDecision,
]:
    """Build three approved, same-scope R4 decisions with distinct identities."""

    first = promotion_decision()
    second = promotion_decision(
        decision_id="r4-equivalence-second",
        decision_version="decision.v2",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )
    third = promotion_decision(
        decision_id="r4-equivalence-third",
        decision_version="decision.v3",
        decided_at=DECIDED_AT + timedelta(minutes=20),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=20),
    )
    return first, second, third


def _r5_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    R5RelativeValuePromotionDecision,
    R5RelativeValuePromotionDecision,
    R5RelativeValuePromotionDecision,
]:
    """Build three approved, same-scope R5 decisions with distinct identities."""

    return (
        make_decision(monkeypatch, decided_at_offset_minutes=181),
        make_decision(monkeypatch, decided_at_offset_minutes=182),
        make_decision(monkeypatch, decided_at_offset_minutes=183),
    )


def _r4_authorization(
    decision: R4PromotionDecision,
    *,
    event_type: R4PromotionLifecycleEventType,
    occurred_at: datetime,
    rollback_target: R4PromotionDecision | None = None,
) -> R4PromotionLifecycleAuthorization:
    issued_at = decision.recorded_at
    return R4PromotionLifecycleAuthorization.create(
        authorization_id=f"r4-equivalence-auth-{event_type.value}-{decision.decision_id}",
        authorization_version="authorization.v1",
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=_REASONS,
        issued_at=issued_at,
        recorded_at=issued_at + timedelta(seconds=1),
        valid_until=max(occurred_at, issued_at) + timedelta(hours=1),
    )


def _r5_authorization(
    decision: R5RelativeValuePromotionDecision,
    *,
    event_type: R5RelativeValueLifecycleEventType,
    occurred_at: datetime,
    rollback_target: R5RelativeValuePromotionDecision | None = None,
) -> R5RelativeValueLifecycleAuthorization:
    issued_at = decision.recorded_at
    return R5RelativeValueLifecycleAuthorization.create(
        authorization_version="r5-equivalence-auth-v1",
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=_REASONS,
        issued_at=issued_at,
        recorded_at=issued_at + timedelta(seconds=1),
        valid_until=max(occurred_at, issued_at) + timedelta(hours=1),
    )


def _r4_root(
    decision: R4PromotionDecision,
    *,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
    event_id: str = "r4-equivalence-root",
) -> R4PromotionLifecycleEvent:
    event_occurred_at = occurred_at or decision.recorded_at + timedelta(minutes=5)
    event_recorded_at = recorded_at or event_occurred_at + timedelta(seconds=5)
    return create_r4_promotion_lifecycle_root(
        event_id=event_id,
        event_version="event.v1",
        decision=decision,
        authorization=_r4_authorization(
            decision,
            event_type=R4PromotionLifecycleEventType.PROMOTED,
            occurred_at=event_occurred_at,
        ),
        reason_codes=_REASONS,
        occurred_at=event_occurred_at,
        recorded_at=event_recorded_at,
    )


def _r5_root(
    decision: R5RelativeValuePromotionDecision,
    *,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
    event_version: str = "event.v1",
) -> R5RelativeValueLifecycleEvent:
    event_occurred_at = occurred_at or decision.recorded_at + timedelta(minutes=5)
    event_recorded_at = recorded_at or event_occurred_at + timedelta(seconds=5)
    return create_r5_relative_value_lifecycle_root(
        event_version=event_version,
        decision=decision,
        authorization=_r5_authorization(
            decision,
            event_type=R5RelativeValueLifecycleEventType.PROMOTED,
            occurred_at=event_occurred_at,
        ),
        reason_codes=_REASONS,
        occurred_at=event_occurred_at,
        recorded_at=event_recorded_at,
    )


def _r4_append(
    previous_events: tuple[R4PromotionLifecycleEvent, ...],
    *,
    event_type: R4PromotionLifecycleEventType,
    decision: R4PromotionDecision,
    rollback_target: R4PromotionDecision | None = None,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
) -> R4PromotionLifecycleEvent:
    event_occurred_at = occurred_at or max(
        previous_events[-1].recorded_at,
        decision.recorded_at,
    ) + timedelta(minutes=1)
    event_recorded_at = recorded_at or event_occurred_at + timedelta(seconds=5)
    return create_r4_promotion_lifecycle_event(
        event_id=f"r4-equivalence-{len(previous_events) + 1}-{decision.decision_id}",
        event_version="event.v1",
        previous_events=previous_events,
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        authorization=_r4_authorization(
            decision,
            event_type=event_type,
            occurred_at=event_occurred_at,
            rollback_target=rollback_target,
        ),
        reason_codes=_REASONS,
        occurred_at=event_occurred_at,
        recorded_at=event_recorded_at,
    )


def _r5_append(
    previous_events: tuple[R5RelativeValueLifecycleEvent, ...],
    *,
    event_type: R5RelativeValueLifecycleEventType,
    decision: R5RelativeValuePromotionDecision,
    rollback_target: R5RelativeValuePromotionDecision | None = None,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
) -> R5RelativeValueLifecycleEvent:
    event_occurred_at = occurred_at or max(
        previous_events[-1].recorded_at,
        decision.recorded_at,
    ) + timedelta(minutes=1)
    event_recorded_at = recorded_at or event_occurred_at + timedelta(seconds=5)
    return create_r5_relative_value_lifecycle_event(
        event_version="event.v1",
        previous_events=previous_events,
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        authorization=_r5_authorization(
            decision,
            event_type=event_type,
            occurred_at=event_occurred_at,
            rollback_target=rollback_target,
        ),
        reason_codes=_REASONS,
        occurred_at=event_occurred_at,
        recorded_at=event_recorded_at,
    )


def test_recorded_prefix_and_exact_expiry_boundary_match_across_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r4_decision, _, _ = _r4_decisions()
    r5_decision, _, _ = _r5_decisions(monkeypatch)
    r4_root = _r4_root(r4_decision)
    r5_root = _r5_root(r5_decision)

    r4_prefix = derive_r4_promotion_lifecycle_state(
        (r4_root,),
        evaluated_at=r4_root.recorded_at,
    )
    r5_prefix = derive_r5_relative_value_lifecycle_state(
        (r5_root,),
        evaluated_at=r5_root.recorded_at,
    )
    assert r4_prefix.state.value == r5_prefix.state.value == "promoted"
    assert r4_prefix.active_decision == R4PromotionDecisionIdentity.from_decision(r4_decision)
    assert r5_prefix.active_decision == R5RelativeValueDecisionIdentity.from_decision(r5_decision)

    r4_before = derive_r4_promotion_lifecycle_state(
        (r4_root,),
        evaluated_at=r4_decision.valid_until - timedelta(microseconds=1),
    )
    r5_before = derive_r5_relative_value_lifecycle_state(
        (r5_root,),
        evaluated_at=r5_decision.valid_until - timedelta(microseconds=1),
    )
    assert r4_before.state is R4PromotionLifecycleState.PROMOTED
    assert r5_before.state is R5RelativeValueLifecycleState.PROMOTED

    r4_expired = derive_r4_promotion_lifecycle_state(
        (r4_root,),
        evaluated_at=r4_decision.valid_until,
    )
    r5_expired = derive_r5_relative_value_lifecycle_state(
        (r5_root,),
        evaluated_at=r5_decision.valid_until,
    )
    assert r4_expired.state.value == r5_expired.state.value == "expired"
    assert r4_expired.active_decision is None
    assert r5_expired.active_decision is None

    r4_future_event = _r4_append(
        (r4_root,),
        event_type=R4PromotionLifecycleEventType.RETIRED,
        decision=r4_decision,
    )
    r5_future_event = _r5_append(
        (r5_root,),
        event_type=R5RelativeValueLifecycleEventType.RETIRED,
        decision=r5_decision,
    )
    with pytest.raises(ValueError, match="future-unrecorded"):
        derive_r4_promotion_lifecycle_state(
            (r4_root, r4_future_event),
            evaluated_at=r4_root.recorded_at,
        )
    with pytest.raises(ValueError, match="future-unrecorded"):
        derive_r5_relative_value_lifecycle_state(
            (r5_root, r5_future_event),
            evaluated_at=r5_root.recorded_at,
        )


def test_retirement_clears_an_expired_top_without_reactivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r4_decision, _, _ = _r4_decisions()
    r5_decision, _, _ = _r5_decisions(monkeypatch)
    r4_root = _r4_root(r4_decision)
    r5_root = _r5_root(r5_decision)
    r4_retired = _r4_append(
        (r4_root,),
        event_type=R4PromotionLifecycleEventType.RETIRED,
        decision=r4_decision,
        occurred_at=r4_decision.valid_until + timedelta(minutes=1),
    )
    r5_retired = _r5_append(
        (r5_root,),
        event_type=R5RelativeValueLifecycleEventType.RETIRED,
        decision=r5_decision,
        occurred_at=r5_decision.valid_until + timedelta(minutes=1),
    )

    r4_snapshot = derive_r4_promotion_lifecycle_state(
        (r4_root, r4_retired),
        evaluated_at=r4_retired.recorded_at,
    )
    r5_snapshot = derive_r5_relative_value_lifecycle_state(
        (r5_root, r5_retired),
        evaluated_at=r5_retired.recorded_at,
    )
    assert r4_snapshot.state.value == r5_snapshot.state.value == "retired"
    assert r4_snapshot.active_decision is None
    assert r5_snapshot.active_decision is None


def test_both_families_pop_exact_stack_minus_two_on_repeated_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r4_first, r4_second, r4_third = _r4_decisions()
    r5_first, r5_second, r5_third = _r5_decisions(monkeypatch)
    r4_root = _r4_root(r4_first)
    r5_root = _r5_root(r5_first)
    r4_second_event = _r4_append(
        (r4_root,),
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=r4_second,
    )
    r5_second_event = _r5_append(
        (r5_root,),
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=r5_second,
    )
    r4_third_event = _r4_append(
        (r4_root, r4_second_event),
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=r4_third,
    )
    r5_third_event = _r5_append(
        (r5_root, r5_second_event),
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=r5_third,
    )
    r4_prefix = (r4_root, r4_second_event, r4_third_event)
    r5_prefix = (r5_root, r5_second_event, r5_third_event)

    with pytest.raises(ValueError, match=r"stack\[-2\]"):
        _r4_append(
            r4_prefix,
            event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
            decision=r4_third,
            rollback_target=r4_first,
        )
    with pytest.raises(ValueError, match=r"stack\[-2\]"):
        _r5_append(
            r5_prefix,
            event_type=R5RelativeValueLifecycleEventType.ROLLED_BACK,
            decision=r5_third,
            rollback_target=r5_first,
        )

    r4_rollback_to_second = _r4_append(
        r4_prefix,
        event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
        decision=r4_third,
        rollback_target=r4_second,
    )
    r5_rollback_to_second = _r5_append(
        r5_prefix,
        event_type=R5RelativeValueLifecycleEventType.ROLLED_BACK,
        decision=r5_third,
        rollback_target=r5_second,
    )
    r4_rollback_to_first = _r4_append(
        (*r4_prefix, r4_rollback_to_second),
        event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
        decision=r4_second,
        rollback_target=r4_first,
    )
    r5_rollback_to_first = _r5_append(
        (*r5_prefix, r5_rollback_to_second),
        event_type=R5RelativeValueLifecycleEventType.ROLLED_BACK,
        decision=r5_second,
        rollback_target=r5_first,
    )

    r4_after_first_pop = derive_r4_promotion_lifecycle_state(
        (*r4_prefix, r4_rollback_to_second),
        evaluated_at=r4_rollback_to_second.recorded_at,
    )
    r5_after_first_pop = derive_r5_relative_value_lifecycle_state(
        (*r5_prefix, r5_rollback_to_second),
        evaluated_at=r5_rollback_to_second.recorded_at,
    )
    assert r4_after_first_pop.state.value == r5_after_first_pop.state.value == "rolled_back"
    assert r4_after_first_pop.active_decision == R4PromotionDecisionIdentity.from_decision(
        r4_second
    )
    assert r5_after_first_pop.active_decision == R5RelativeValueDecisionIdentity.from_decision(
        r5_second
    )

    r4_after_second_pop = derive_r4_promotion_lifecycle_state(
        (*r4_prefix, r4_rollback_to_second, r4_rollback_to_first),
        evaluated_at=r4_rollback_to_first.recorded_at,
    )
    r5_after_second_pop = derive_r5_relative_value_lifecycle_state(
        (*r5_prefix, r5_rollback_to_second, r5_rollback_to_first),
        evaluated_at=r5_rollback_to_first.recorded_at,
    )
    assert r4_after_second_pop.active_decision == R4PromotionDecisionIdentity.from_decision(
        r4_first
    )
    assert r5_after_second_pop.active_decision == R5RelativeValueDecisionIdentity.from_decision(
        r5_first
    )


def test_only_duplicate_top_is_forbidden_and_full_typed_identity_is_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r4_first, r4_second, _ = _r4_decisions()
    r5_first, r5_second, _ = _r5_decisions(monkeypatch)
    r4_root = _r4_root(r4_first)
    r5_root = _r5_root(r5_first)
    r4_second_event = _r4_append(
        (r4_root,),
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=r4_second,
    )
    r5_second_event = _r5_append(
        (r5_root,),
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=r5_second,
    )

    with pytest.raises(ValueError, match="promote the active decision again"):
        _r4_append(
            (r4_root, r4_second_event),
            event_type=R4PromotionLifecycleEventType.PROMOTED,
            decision=r4_second,
        )
    with pytest.raises(ValueError, match="promote the active decision again"):
        _r5_append(
            (r5_root, r5_second_event),
            event_type=R5RelativeValueLifecycleEventType.PROMOTED,
            decision=r5_second,
        )

    r4_repromoted_lower = _r4_append(
        (r4_root, r4_second_event),
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=r4_first,
    )
    r5_repromoted_lower = _r5_append(
        (r5_root, r5_second_event),
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=r5_first,
    )
    assert derive_r4_promotion_lifecycle_state(
        (r4_root, r4_second_event, r4_repromoted_lower),
        evaluated_at=r4_repromoted_lower.recorded_at,
    ).active_decision == R4PromotionDecisionIdentity.from_decision(r4_first)
    assert derive_r5_relative_value_lifecycle_state(
        (r5_root, r5_second_event, r5_repromoted_lower),
        evaluated_at=r5_repromoted_lower.recorded_at,
    ).active_decision == R5RelativeValueDecisionIdentity.from_decision(r5_first)

    r4_identity = R4PromotionDecisionIdentity.from_decision(r4_first)
    assert r4_identity.portfolio_record_id == r4_first.trial.portfolio_record.record_id
    assert r4_identity.portfolio_record_hash == r4_first.trial.portfolio_record.record_hash
    assert r4_identity.current_r3_content_hash == (
        r4_first.trial.current_r3_attestation.content_hash
    )
    assert replace(r4_identity, portfolio_record_hash="0" * 64) != r4_identity
    assert replace(r4_identity, current_r3_content_hash="1" * 64) != r4_identity

    r5_identity = R5RelativeValueDecisionIdentity.from_decision(r5_first)
    assert r5_identity.result_identities
    assert r5_identity.outcome_identities
    changed_result = (
        *r5_identity.result_identities[:-1],
        (
            r5_identity.result_identities[-1][0],
            r5_identity.result_identities[-1][1],
            "0" * 64,
            r5_identity.result_identities[-1][3],
        ),
    )
    changed_outcome = (
        *r5_identity.outcome_identities[:-1],
        (
            r5_identity.outcome_identities[-1][0],
            r5_identity.outcome_identities[-1][1],
            "1" * 64,
            r5_identity.outcome_identities[-1][3],
        ),
    )
    assert replace(r5_identity, result_identities=changed_result) != r5_identity
    assert replace(r5_identity, outcome_identities=changed_outcome) != r5_identity


def test_sequence_and_previous_hash_are_ordered_by_the_recorded_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r4_first, r4_second, _ = _r4_decisions()
    r5_first, r5_second, _ = _r5_decisions(monkeypatch)
    r4_root = _r4_root(r4_first)
    r5_root = _r5_root(r5_first)
    r4_next = _r4_append(
        (r4_root,),
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=r4_second,
    )
    r5_next = _r5_append(
        (r5_root,),
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=r5_second,
    )
    assert r4_next.sequence == r4_root.sequence + 1
    assert r5_next.sequence == r5_root.sequence + 1
    assert r4_next.previous_event_hash == r4_root.content_hash
    assert r5_next.previous_event_hash == r5_root.content_hash

    r4_fork = _r4_root(r4_second, event_id="r4-equivalence-other-root")
    r5_fork = _r5_root(r5_second, event_version="event.other-root.v1")
    with pytest.raises(ValueError, match="discontinuous"):
        derive_r4_promotion_lifecycle_state(
            (r4_fork, r4_next),
            evaluated_at=max(r4_fork.recorded_at, r4_next.recorded_at),
        )
    with pytest.raises(ValueError, match="discontinuous"):
        derive_r5_relative_value_lifecycle_state(
            (r5_fork, r5_next),
            evaluated_at=max(r5_fork.recorded_at, r5_next.recorded_at),
        )
    with pytest.raises(ValueError, match="discontinuous"):
        derive_r4_promotion_lifecycle_state(
            (r4_next, r4_root),
            evaluated_at=max(r4_next.recorded_at, r4_root.recorded_at),
        )
    with pytest.raises(ValueError, match="discontinuous"):
        derive_r5_relative_value_lifecycle_state(
            (r5_next, r5_root),
            evaluated_at=max(r5_next.recorded_at, r5_root.recorded_at),
        )


def test_all_three_append_clock_regressions_fail_in_both_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r4_decision, _, _ = _r4_decisions()
    r5_decision, _, _ = _r5_decisions(monkeypatch)
    r4_occurred = r4_decision.recorded_at + timedelta(minutes=10)
    r5_occurred = r5_decision.recorded_at + timedelta(minutes=10)
    r4_roots = (
        _r4_root(r4_decision, occurred_at=r4_occurred, recorded_at=r4_occurred),
        _r4_root(
            r4_decision,
            occurred_at=r4_occurred,
            recorded_at=r4_occurred + timedelta(minutes=1),
            event_id="r4-equivalence-root-with-receipt-gap",
        ),
    )
    r5_roots = (
        _r5_root(r5_decision, occurred_at=r5_occurred, recorded_at=r5_occurred),
        _r5_root(
            r5_decision,
            occurred_at=r5_occurred,
            recorded_at=r5_occurred + timedelta(minutes=1),
            event_version="event.with-receipt-gap.v1",
        ),
    )

    for r4_root, r5_root in zip(r4_roots, r5_roots, strict=True):
        before_occurrence = r4_root.occurred_at - timedelta(microseconds=1)
        before_receipt = r4_root.recorded_at - timedelta(microseconds=1)
        before_record = r4_root.recorded_at - timedelta(microseconds=1)
        with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
            _r4_append(
                (r4_root,),
                event_type=R4PromotionLifecycleEventType.RETIRED,
                decision=r4_decision,
                occurred_at=before_occurrence,
                recorded_at=r4_root.recorded_at + timedelta(seconds=1),
            )
        with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
            _r4_append(
                (r4_root,),
                event_type=R4PromotionLifecycleEventType.RETIRED,
                decision=r4_decision,
                occurred_at=before_receipt,
                recorded_at=r4_root.recorded_at + timedelta(seconds=1),
            )
        with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
            _r4_append(
                (r4_root,),
                event_type=R4PromotionLifecycleEventType.RETIRED,
                decision=r4_decision,
                occurred_at=r4_root.recorded_at + timedelta(seconds=1),
                recorded_at=before_record,
            )

        r5_before_occurrence = r5_root.occurred_at - timedelta(microseconds=1)
        r5_before_receipt = r5_root.recorded_at - timedelta(microseconds=1)
        r5_before_record = r5_root.recorded_at - timedelta(microseconds=1)
        with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
            _r5_append(
                (r5_root,),
                event_type=R5RelativeValueLifecycleEventType.RETIRED,
                decision=r5_decision,
                occurred_at=r5_before_occurrence,
                recorded_at=r5_root.recorded_at + timedelta(seconds=1),
            )
        with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
            _r5_append(
                (r5_root,),
                event_type=R5RelativeValueLifecycleEventType.RETIRED,
                decision=r5_decision,
                occurred_at=r5_before_receipt,
                recorded_at=r5_root.recorded_at + timedelta(seconds=1),
            )
        with pytest.raises(ValueError, match="dual clocks cannot move backwards"):
            _r5_append(
                (r5_root,),
                event_type=R5RelativeValueLifecycleEventType.RETIRED,
                decision=r5_decision,
                occurred_at=r5_root.recorded_at + timedelta(seconds=1),
                recorded_at=r5_before_record,
            )


def _other_r4_scope() -> R4PromotionScope:
    return R4PromotionScope.create(
        study_family_id="other-r4-family",
        universe_policy_id="other-universe",
        factor_policy_id="other-factor-policy",
        split_policy_id="other-split-policy",
        cost_semantics_id="other-cost-semantics",
    )


def _other_r5_scope() -> R5RelativeValuePromotionScope:
    return R5RelativeValuePromotionScope.create(
        study_family_id="other-r5-family",
        currency="CNY",
        universe_policy_id="other-bond-universe",
        split_policy_id="other-split-policy",
        cost_policy_id="other-cost-policy",
        liquidity_policy_id="other-liquidity-policy",
    )


def test_original_event_entities_reject_cross_scope_foreign_types_unknown_and_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r4_decision, _, _ = _r4_decisions()
    r5_decision, _, _ = _r5_decisions(monkeypatch)
    r4_root = _r4_root(r4_decision)
    r5_root = _r5_root(r5_decision)

    with pytest.raises(ValueError, match="stream identity"):
        replace(r4_root, scope=_other_r4_scope())
    with pytest.raises(ValueError, match="stream identity"):
        replace(r5_root, scope=_other_r5_scope())
    with pytest.raises(ValueError, match="root must be"):
        replace(r4_root, event_type=R5RelativeValueLifecycleEventType.PROMOTED)
    with pytest.raises(ValueError, match="root must be"):
        replace(r5_root, event_type=R4PromotionLifecycleEventType.PROMOTED)
    with pytest.raises(ValueError, match="root must be"):
        replace(r4_root, event_type="unrecognized")
    with pytest.raises(ValueError, match="root must be"):
        replace(r5_root, event_type="unrecognized")
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(r4_root, content_hash="0" * 64)
    with pytest.raises(ValueError, match="content hash or identity mismatch"):
        replace(r5_root, content_hash="0" * 64)
