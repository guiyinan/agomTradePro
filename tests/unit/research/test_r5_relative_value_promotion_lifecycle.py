"""Scope-local R5 promotion/retirement/rollback stack semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

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
from tests.unit.research.r5_relative_value_promotion_factories import (
    BASE_TIME,
    make_decision,
    make_policy,
    make_scope,
    make_trial,
)


def _authorization(
    decision: R5RelativeValuePromotionDecision,
    *,
    event_type: R5RelativeValueLifecycleEventType,
    occurred_at: datetime,
    rollback_target: R5RelativeValuePromotionDecision | None = None,
    reason_codes: tuple[str, ...] = ("research_owner_approved",),
) -> R5RelativeValueLifecycleAuthorization:
    return R5RelativeValueLifecycleAuthorization.create(
        authorization_version="lifecycle-auth-v1",
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reason_codes,
        issued_at=occurred_at - timedelta(seconds=20),
        recorded_at=occurred_at - timedelta(seconds=10),
        valid_until=occurred_at + timedelta(hours=1),
    )


def _root(
    decision: R5RelativeValuePromotionDecision,
    *,
    occurred_at: datetime,
) -> R5RelativeValueLifecycleEvent:
    return create_r5_relative_value_lifecycle_root(
        event_version="event-v1",
        decision=decision,
        authorization=_authorization(
            decision,
            event_type=R5RelativeValueLifecycleEventType.PROMOTED,
            occurred_at=occurred_at,
        ),
        reason_codes=("research_owner_approved",),
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(seconds=5),
    )


def _append(
    history: tuple[R5RelativeValueLifecycleEvent, ...],
    *,
    event_type: R5RelativeValueLifecycleEventType,
    decision: R5RelativeValuePromotionDecision,
    occurred_at: datetime,
    rollback_target: R5RelativeValuePromotionDecision | None = None,
) -> R5RelativeValueLifecycleEvent:
    return create_r5_relative_value_lifecycle_event(
        event_version="event-v1",
        previous_events=history,
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        authorization=_authorization(
            decision,
            event_type=event_type,
            rollback_target=rollback_target,
            occurred_at=occurred_at,
        ),
        reason_codes=("research_owner_approved",),
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(seconds=5),
    )


def _three_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    R5RelativeValuePromotionDecision,
    R5RelativeValuePromotionDecision,
    R5RelativeValuePromotionDecision,
]:
    scope = make_scope()
    decisions: list[R5RelativeValuePromotionDecision] = []
    for index, threshold in enumerate(
        (Decimal("0.001"), Decimal("0.002"), Decimal("0.003")),
        start=1,
    ):
        policy = make_policy(
            scope=scope,
            minimum_excess_net_return=threshold,
        )
        trial = make_trial(monkeypatch, policy=policy)
        decisions.append(
            make_decision(
                monkeypatch,
                policy=policy,
                trial=trial,
                decided_at_offset_minutes=180 + index,
            )
        )
    return decisions[0], decisions[1], decisions[2]


def test_promote_three_then_roll_back_only_through_stack_minus_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consecutive rollback pops C→B→A and cannot jump a stack level."""

    first, second, third = _three_decisions(monkeypatch)
    root_at = BASE_TIME + timedelta(minutes=190)
    root = _root(first, occurred_at=root_at)
    promote_second = _append(
        (root,),
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=second,
        occurred_at=root_at + timedelta(minutes=2),
    )
    promote_third = _append(
        (root, promote_second),
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=third,
        occurred_at=root_at + timedelta(minutes=4),
    )
    with pytest.raises(ValueError, match=r"stack\[-2\]"):
        _append(
            (root, promote_second, promote_third),
            event_type=R5RelativeValueLifecycleEventType.ROLLED_BACK,
            decision=third,
            rollback_target=first,
            occurred_at=root_at + timedelta(minutes=6),
        )
    rollback_to_second = _append(
        (root, promote_second, promote_third),
        event_type=R5RelativeValueLifecycleEventType.ROLLED_BACK,
        decision=third,
        rollback_target=second,
        occurred_at=root_at + timedelta(minutes=6),
    )
    rollback_to_first = _append(
        (root, promote_second, promote_third, rollback_to_second),
        event_type=R5RelativeValueLifecycleEventType.ROLLED_BACK,
        decision=second,
        rollback_target=first,
        occurred_at=root_at + timedelta(minutes=8),
    )
    snapshot = derive_r5_relative_value_lifecycle_state(
        (root, promote_second, promote_third, rollback_to_second, rollback_to_first),
        evaluated_at=rollback_to_first.recorded_at,
    )
    assert snapshot.state is R5RelativeValueLifecycleState.ROLLED_BACK
    assert snapshot.active_decision == R5RelativeValueDecisionIdentity.from_decision(first)


def test_retire_can_clear_an_expired_top_without_reactivating_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retirement is allowed after validity expiry and produces no active result."""

    decision = make_decision(monkeypatch)
    root_at = decision.recorded_at + timedelta(minutes=1)
    root = _root(decision, occurred_at=root_at)
    expired_at = decision.valid_until + timedelta(minutes=1)
    expired = derive_r5_relative_value_lifecycle_state(
        (root,),
        evaluated_at=expired_at,
    )
    assert expired.state is R5RelativeValueLifecycleState.EXPIRED
    retired = _append(
        (root,),
        event_type=R5RelativeValueLifecycleEventType.RETIRED,
        decision=decision,
        occurred_at=expired_at,
    )
    snapshot = derive_r5_relative_value_lifecycle_state(
        (root, retired),
        evaluated_at=retired.recorded_at,
    )
    assert snapshot.state is R5RelativeValueLifecycleState.RETIRED
    assert snapshot.active_decision is None


def test_content_addressed_event_and_chain_tamper_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An event cannot be re-sealed under one ID or replayed with a broken link."""

    decision = make_decision(monkeypatch)
    root = _root(decision, occurred_at=decision.recorded_at + timedelta(minutes=1))
    assert root.event_id == f"r5-rv-event:{root.content_hash}"
    with pytest.raises(ValueError, match="authorization|content hash|identity"):
        replace(root, reason_codes=("substituted_reason",))
    with pytest.raises(ValueError, match="future-unrecorded"):
        derive_r5_relative_value_lifecycle_state(
            (root,),
            evaluated_at=root.recorded_at - timedelta(seconds=1),
        )
