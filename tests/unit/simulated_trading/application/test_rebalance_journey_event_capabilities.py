"""User-visible plan capabilities reuse the actual event-review gate."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventReviewAssessment,
    TransitionPlanEventReviewState,
)
from apps.simulated_trading.application.rebalance_journey_public import RebalanceJourneyCommand
from apps.simulated_trading.application.rebalance_journey_service import RebalanceJourneyApplication
from tests.unit.portfolio.test_transition_plan_revision_asset_identity import _NOW, _revision


@pytest.mark.parametrize("state", (None, *TransitionPlanEventReviewState))
def test_current_event_outcome_controls_advertised_actions_without_mutating_plan(state):
    revision = _revision()
    original = revision.to_payload()
    repository = Mock()
    repository.get_family_head.return_value = revision
    validator = None if state is None else Mock()
    if validator is not None:
        validator.assess.return_value = TransitionPlanEventReviewAssessment(
            state, "SYNTHETIC_EVENT_REASON"
        )
    clock = Mock()
    clock.now.return_value = _NOW + timedelta(seconds=1)
    progress = Mock()
    progress.read.return_value = {"synthetic": True}
    app = RebalanceJourneyApplication(
        repository=repository,
        authorizer=Mock(),
        clock=clock,
        preparation_factory=Mock(),
        progress_reader=progress,
        order_previewer=Mock(),
        event_review_validator=validator,
    )
    result = app._envelope(
        RebalanceJourneyCommand(
            "read",
            23,
            17,
            revision.identity.plan_id,
            revision.identity.version,
            revision.identity.revision_hash,
        ),
        revision,
    )
    assert result["capabilities"]["can_preview_order"] is (
        state is TransitionPlanEventReviewState.UNCHANGED
    )
    assert result["capabilities"]["can_request_review"] is (
        state is TransitionPlanEventReviewState.UNCHANGED
    )
    assert result["capabilities"]["can_create_successor"] is True
    assert result["review"]["event_review_blocking_reason"] == (
        None
        if state is TransitionPlanEventReviewState.UNCHANGED
        else {
            None: "TRANSITION_PLAN_EVENT_REVIEW_UNAVAILABLE",
            TransitionPlanEventReviewState.REVIEW_REQUIRED: "TRANSITION_PLAN_EVENT_REVIEW_REQUIRED",
            TransitionPlanEventReviewState.BLOCKED: "TRANSITION_PLAN_EVENT_REVIEW_BLOCKED",
        }[state]
    )
    assert revision.to_payload() == original
    repository.submit_for_review.assert_not_called()
    if validator is not None:
        validator.assess.assert_called_once_with(revision, as_of=clock.now.return_value)


@pytest.mark.parametrize("state", (None, *TransitionPlanEventReviewState))
def test_preview_request_stops_at_current_event_gate_before_market_or_order_preparation(
    monkeypatch, state
):
    from core.exceptions import BusinessLogicError

    revision = _revision()
    original = revision.to_payload()
    repository, authorizer, progress, previewer, clock = (Mock() for _ in range(5))
    repository.get_family_head.return_value = revision
    clock.now.return_value = _NOW + timedelta(seconds=1)
    progress.read.return_value = {"synthetic": True}
    previewer.preview.return_value = ({"synthetic_display": True}, {"synthetic_handoff": True})
    validator = None if state is None else Mock()
    if validator is not None:
        validator.assess.return_value = TransitionPlanEventReviewAssessment(
            state, "SYNTHETIC_EVENT_REASON"
        )
    app = RebalanceJourneyApplication(
        repository=repository,
        authorizer=authorizer,
        clock=clock,
        preparation_factory=Mock(),
        progress_reader=progress,
        order_previewer=previewer,
        event_review_validator=validator,
    )
    monkeypatch.setattr(app, "_read", lambda command: revision)
    order = revision.orders[0]
    command = RebalanceJourneyCommand(
        "preview_order",
        23,
        17,
        revision.identity.plan_id,
        revision.identity.version,
        revision.identity.revision_hash,
        "synthetic-preview-request",
        order_ordinal=order.ordinal,
        order_content_hash=order.order_content_hash,
        plan_order_binding_id=order.plan_order_binding_id,
        quantity=Decimal(order.approved_quantity),
        limit_price=order.reference_price,
    )
    if state is TransitionPlanEventReviewState.UNCHANGED:
        result = app.execute(command)
        assert result["preview"] == {"synthetic_display": True}
        previewer.preview.assert_called_once_with(command=command, revision=revision)
    else:
        with pytest.raises(BusinessLogicError) as blocked:
            app.execute(command)
        assert (
            blocked.value.code
            == {
                None: "TRANSITION_PLAN_EVENT_REVIEW_UNAVAILABLE",
                TransitionPlanEventReviewState.REVIEW_REQUIRED: "TRANSITION_PLAN_EVENT_REVIEW_REQUIRED",
                TransitionPlanEventReviewState.BLOCKED: "TRANSITION_PLAN_EVENT_REVIEW_BLOCKED",
            }[state]
        )
        previewer.preview.assert_not_called()
    assert revision.to_payload() == original
