"""Unit coverage for scope-local R4 promotion lifecycle replay."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.domain.r4_promotion_decision import R4PromotionDecision
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEvent,
    R4PromotionLifecycleEventType,
    R4PromotionLifecycleState,
    create_r4_promotion_lifecycle_event,
    create_r4_promotion_lifecycle_root,
    derive_r4_promotion_lifecycle_state,
)
from tests.unit.research.r4_promotion_factories import (
    DECIDED_AT,
    DECISION_RECORDED_AT,
    promotion_decision,
    promotion_policy,
    promotion_trial,
)


def _authorization(
    *,
    event_type: R4PromotionLifecycleEventType,
    decision: R4PromotionDecision,
    rollback_target: R4PromotionDecision | None = None,
    reason_codes: tuple[str, ...],
    base_time: datetime,
    suffix: str,
) -> R4PromotionLifecycleAuthorization:
    return R4PromotionLifecycleAuthorization.create(
        authorization_id=f"r4-auth-{suffix}",
        authorization_version="authorization.v1",
        event_type=event_type,
        decision=decision,
        rollback_target=rollback_target,
        reason_codes=reason_codes,
        issued_at=base_time,
        recorded_at=base_time + timedelta(minutes=1),
        valid_until=base_time + timedelta(hours=1),
    )


def _root(decision: R4PromotionDecision) -> R4PromotionLifecycleEvent:
    base = decision.recorded_at + timedelta(minutes=1)
    reasons = ("research_policy_approved",)
    authorization = _authorization(
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        reason_codes=reasons,
        base_time=base,
        suffix="root",
    )
    return create_r4_promotion_lifecycle_root(
        event_id="r4-event-root",
        event_version="event.v1",
        decision=decision,
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=base + timedelta(minutes=2),
        recorded_at=base + timedelta(minutes=3),
    )


def _second_decision() -> R4PromotionDecision:
    return promotion_decision(
        decision_id="r4-promotion-decision-second",
        decision_version="decision.v2",
        decided_at=DECIDED_AT + timedelta(minutes=10),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=10),
    )


def _third_decision() -> R4PromotionDecision:
    return promotion_decision(
        decision_id="r4-promotion-decision-third",
        decision_version="decision.v3",
        decided_at=DECIDED_AT + timedelta(minutes=20),
        recorded_at=DECISION_RECORDED_AT + timedelta(minutes=20),
    )


def _promote(
    previous_events: tuple[R4PromotionLifecycleEvent, ...],
    decision: R4PromotionDecision,
    *,
    suffix: str,
) -> R4PromotionLifecycleEvent:
    base = max(previous_events[-1].recorded_at, decision.recorded_at) + timedelta(minutes=1)
    reasons = ("replacement_policy_approved",)
    return create_r4_promotion_lifecycle_event(
        event_id=f"r4-event-promote-{suffix}",
        event_version="event.v1",
        previous_events=previous_events,
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        authorization=_authorization(
            event_type=R4PromotionLifecycleEventType.PROMOTED,
            decision=decision,
            reason_codes=reasons,
            base_time=base,
            suffix=f"promote-{suffix}",
        ),
        reason_codes=reasons,
        occurred_at=base + timedelta(minutes=2),
        recorded_at=base + timedelta(minutes=3),
    )


def _rollback(
    previous_events: tuple[R4PromotionLifecycleEvent, ...],
    decision: R4PromotionDecision,
    target: R4PromotionDecision,
    *,
    suffix: str,
) -> R4PromotionLifecycleEvent:
    base = previous_events[-1].recorded_at + timedelta(minutes=1)
    reasons = ("replacement_regression",)
    return create_r4_promotion_lifecycle_event(
        event_id=f"r4-event-rollback-{suffix}",
        event_version="event.v1",
        previous_events=previous_events,
        event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
        decision=decision,
        rollback_target=target,
        authorization=_authorization(
            event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
            decision=decision,
            rollback_target=target,
            reason_codes=reasons,
            base_time=base,
            suffix=f"rollback-{suffix}",
        ),
        reason_codes=reasons,
        occurred_at=base + timedelta(minutes=2),
        recorded_at=base + timedelta(minutes=3),
    )


def test_promote_three_then_consecutive_rollbacks_pop_exact_stack_minus_two() -> None:
    first = promotion_decision()
    second = _second_decision()
    third = _third_decision()
    root = _root(first)
    promoted_second = _promote((root,), second, suffix="second")
    promoted_third = _promote((root, promoted_second), third, suffix="third")
    rolled_back_to_second = _rollback(
        (root, promoted_second, promoted_third),
        third,
        second,
        suffix="to-second",
    )

    second_snapshot = derive_r4_promotion_lifecycle_state(
        (root, promoted_second, promoted_third, rolled_back_to_second),
        evaluated_at=rolled_back_to_second.recorded_at,
    )
    assert second_snapshot.state is R4PromotionLifecycleState.ROLLED_BACK
    assert second_snapshot.active_decision == promoted_second.decision

    rolled_back_to_first = _rollback(
        (root, promoted_second, promoted_third, rolled_back_to_second),
        second,
        first,
        suffix="to-first",
    )
    snapshot = derive_r4_promotion_lifecycle_state(
        (
            root,
            promoted_second,
            promoted_third,
            rolled_back_to_second,
            rolled_back_to_first,
        ),
        evaluated_at=rolled_back_to_first.recorded_at,
    )

    assert snapshot.state is R4PromotionLifecycleState.ROLLED_BACK
    assert snapshot.active_decision == root.decision
    retirement_base = rolled_back_to_first.recorded_at + timedelta(minutes=1)
    retirement_reasons = ("methodology_retired",)
    retired = create_r4_promotion_lifecycle_event(
        event_id="r4-event-retired",
        event_version="event.v1",
        previous_events=(
            root,
            promoted_second,
            promoted_third,
            rolled_back_to_second,
            rolled_back_to_first,
        ),
        event_type=R4PromotionLifecycleEventType.RETIRED,
        decision=first,
        rollback_target=None,
        authorization=_authorization(
            event_type=R4PromotionLifecycleEventType.RETIRED,
            decision=first,
            reason_codes=retirement_reasons,
            base_time=retirement_base,
            suffix="retire",
        ),
        reason_codes=retirement_reasons,
        occurred_at=retirement_base + timedelta(minutes=2),
        recorded_at=retirement_base + timedelta(minutes=3),
    )
    retired_snapshot = derive_r4_promotion_lifecycle_state(
        (
            root,
            promoted_second,
            promoted_third,
            rolled_back_to_second,
            rolled_back_to_first,
            retired,
        ),
        evaluated_at=retired.recorded_at,
    )
    assert retired_snapshot.state is R4PromotionLifecycleState.RETIRED
    assert retired_snapshot.active_decision is None


def test_rollback_rejects_any_target_other_than_stack_minus_two() -> None:
    first = promotion_decision()
    second = _second_decision()
    root = _root(first)
    promote_base = second.recorded_at + timedelta(minutes=1)
    reasons = ("replacement_policy_approved",)
    promoted = create_r4_promotion_lifecycle_event(
        event_id="r4-event-promote-second",
        event_version="event.v1",
        previous_events=(root,),
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=second,
        rollback_target=None,
        authorization=_authorization(
            event_type=R4PromotionLifecycleEventType.PROMOTED,
            decision=second,
            reason_codes=reasons,
            base_time=promote_base,
            suffix="second",
        ),
        reason_codes=reasons,
        occurred_at=promote_base + timedelta(minutes=2),
        recorded_at=promote_base + timedelta(minutes=3),
    )
    rollback_base = promoted.recorded_at + timedelta(minutes=1)
    rollback_reasons = ("wrong_target_test",)

    with pytest.raises(ValueError, match=r"exactly stack\[-2\]"):
        create_r4_promotion_lifecycle_event(
            event_id="r4-event-bad-rollback",
            event_version="event.v1",
            previous_events=(root, promoted),
            event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
            decision=second,
            rollback_target=second,
            authorization=_authorization(
                event_type=R4PromotionLifecycleEventType.ROLLED_BACK,
                decision=second,
                rollback_target=second,
                reason_codes=rollback_reasons,
                base_time=rollback_base,
                suffix="bad-rollback",
            ),
            reason_codes=rollback_reasons,
            occurred_at=rollback_base + timedelta(minutes=2),
            recorded_at=rollback_base + timedelta(minutes=3),
        )


def test_rejected_decision_future_prefix_and_hash_tamper_fail_closed() -> None:
    rejected_policy = promotion_policy(minimum_relative_net_return=Decimal("0.5"))
    rejected = promotion_decision(
        policy=rejected_policy,
        trial=promotion_trial(policy=rejected_policy),
    )
    base = rejected.recorded_at + timedelta(minutes=1)
    reasons = ("should_not_promote",)
    authorization = _authorization(
        event_type=R4PromotionLifecycleEventType.PROMOTED,
        decision=rejected,
        reason_codes=reasons,
        base_time=base,
        suffix="rejected",
    )
    with pytest.raises(ValueError, match="only approved"):
        create_r4_promotion_lifecycle_root(
            event_id="r4-event-rejected",
            event_version="event.v1",
            decision=rejected,
            authorization=authorization,
            reason_codes=reasons,
            occurred_at=base + timedelta(minutes=2),
            recorded_at=base + timedelta(minutes=3),
        )

    root = _root(promotion_decision())
    with pytest.raises(ValueError, match="future-unrecorded"):
        derive_r4_promotion_lifecycle_state(
            (root,),
            evaluated_at=root.recorded_at - timedelta(microseconds=1),
        )
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(root, content_hash="0" * 64)
