"""Focused compatibility evidence for R5's typed lifecycle adapter."""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueDecisionIdentity,
    R5RelativeValueLifecycleAuthorization,
    R5RelativeValueLifecycleEventType,
    R5RelativeValueLifecycleState,
    create_r5_relative_value_lifecycle_root,
    derive_r5_relative_value_lifecycle_state,
)
from tests.unit.research.r5_relative_value_promotion_factories import make_decision


def test_r5_replay_keeps_relative_value_identity_and_content_addressed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared replay returns the complete typed R5 identity unchanged."""

    decision = make_decision(monkeypatch)
    occurred_at = decision.recorded_at + timedelta(minutes=1)
    reasons = ("research_owner_approved",)
    authorization = R5RelativeValueLifecycleAuthorization.create(
        authorization_version="r5-lifecycle-auth-v1",
        event_type=R5RelativeValueLifecycleEventType.PROMOTED,
        decision=decision,
        rollback_target=None,
        reason_codes=reasons,
        issued_at=occurred_at - timedelta(seconds=20),
        recorded_at=occurred_at - timedelta(seconds=10),
        valid_until=occurred_at + timedelta(hours=1),
    )
    event = create_r5_relative_value_lifecycle_root(
        event_version="r5-lifecycle-event-v1",
        decision=decision,
        authorization=authorization,
        reason_codes=reasons,
        occurred_at=occurred_at,
        recorded_at=occurred_at + timedelta(seconds=5),
    )

    snapshot = derive_r5_relative_value_lifecycle_state(
        (event,),
        evaluated_at=event.recorded_at,
    )
    identity = R5RelativeValueDecisionIdentity.from_decision(decision)

    assert snapshot.active_decision == identity
    assert snapshot.state is R5RelativeValueLifecycleState.PROMOTED
    assert identity.result_identities == tuple(
        sorted(
            (
                item.fixed_income_record.result_id,
                item.fixed_income_record.result_version,
                item.fixed_income_record.result_record_hash,
                item.fixed_income_record.content_hash,
            )
            for item in decision.trial.observations
        )
    )
    assert identity.outcome_identities == tuple(
        sorted(
            (
                item.portfolio_outcome.outcome_id,
                item.portfolio_outcome.outcome_version,
                item.portfolio_outcome.owner_record_hash,
                item.portfolio_outcome.content_hash,
            )
            for item in decision.trial.observations
        )
    )
    assert event.stream_id == f"research:r5:relative-value:{decision.scope.scope_id}"
    assert event.event_id == f"r5-rv-event:{event.content_hash}"
    assert authorization.authorization_id == (f"r5-rv-lifecycle-auth:{authorization.content_hash}")
