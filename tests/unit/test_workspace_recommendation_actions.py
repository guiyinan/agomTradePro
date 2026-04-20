from decimal import Decimal

import pytest

from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel, AlphaTriggerModel
from apps.decision_rhythm.application.workspace_services import (
    update_workspace_recommendation_action,
)
from apps.decision_rhythm.domain.entities import UserDecisionAction
from apps.decision_rhythm.infrastructure.models import UnifiedRecommendationModel


@pytest.mark.django_db
def test_ignore_recommendation_cancels_source_candidate_and_trigger():
    trigger = AlphaTriggerModel.objects.create(
        trigger_id="trigger-ignore-1",
        trigger_type=AlphaTriggerModel.MANUAL_OVERRIDE,
        asset_code="600519.SH",
        asset_class="equity",
        confidence=0.95,
        status=AlphaTriggerModel.TRIGGERED,
    )
    candidate = AlphaCandidateModel.objects.create(
        candidate_id="cand-ignore-1",
        trigger_id=trigger.trigger_id,
        asset_code="600519.SH",
        asset_class="equity",
        confidence=0.95,
        status=AlphaCandidateModel.ACTIONABLE,
    )
    UnifiedRecommendationModel.objects.create(
        recommendation_id="urec_ignore_1",
        account_id="acct-1",
        security_code="600519.SH",
        side="HOLD",
        beta_gate_passed=False,
        alpha_model_score=0.95,
        composite_score=0.68,
        confidence=0.5,
        reason_codes=["ALPHA_HIGH", "BETA_GATE_BLOCKED"],
        human_rationale="legacy recommendation",
        fair_value=Decimal("0"),
        entry_price_low=Decimal("0"),
        entry_price_high=Decimal("0"),
        target_price_low=Decimal("0"),
        target_price_high=Decimal("0"),
        stop_loss_price=Decimal("0"),
        source_signal_ids=[candidate.candidate_id],
        source_candidate_ids=[candidate.candidate_id],
        user_action=UserDecisionAction.PENDING.value,
        user_action_note="",
    )

    dto = update_workspace_recommendation_action(
        recommendation_id="urec_ignore_1",
        action=UserDecisionAction.IGNORED,
        note="ignore noisy manual override",
        account_id="acct-1",
    )

    candidate.refresh_from_db()
    trigger.refresh_from_db()
    recommendation = UnifiedRecommendationModel.objects.get(
        recommendation_id="urec_ignore_1"
    )

    assert dto is not None
    assert dto.user_action == UserDecisionAction.IGNORED.value
    assert recommendation.user_action == UserDecisionAction.IGNORED.value
    assert recommendation.user_action_note == "ignore noisy manual override"
    assert recommendation.user_action_at is not None
    assert candidate.status == AlphaCandidateModel.CANCELLED
    assert trigger.status == AlphaTriggerModel.CANCELLED
