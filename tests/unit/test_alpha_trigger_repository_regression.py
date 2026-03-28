from datetime import datetime, timezone

import pytest

from apps.alpha_trigger.application.use_cases import (
    CreateAlphaTriggerUseCase,
    CreateTriggerRequest,
    EvaluateAlphaTriggerUseCase,
    EvaluateTriggerRequest,
)
from apps.alpha_trigger.domain.entities import (
    AlphaCandidate,
    CandidateStatus,
    SignalStrength,
    TriggerStatus,
    TriggerType,
)
from apps.alpha_trigger.infrastructure.repositories import AlphaCandidateRepository, AlphaTriggerRepository


@pytest.mark.django_db
def test_alpha_candidate_repository_does_not_depend_on_custom_manager_methods():
    repo = AlphaCandidateRepository()

    actionable = AlphaCandidate(
        candidate_id="cand-actionable-001",
        trigger_id="trigger-actionable-001",
        asset_code="000333.SZ",
        asset_class="EQUITY",
        direction="LONG",
        strength=SignalStrength.VERY_STRONG,
        confidence=0.95,
        thesis="Momentum breakout confirmed",
        invalidation="Price breaks below support",
        time_window_start=datetime(2026, 3, 29, tzinfo=timezone.utc).date(),
        time_window_end=datetime(2026, 6, 27, tzinfo=timezone.utc).date(),
        time_horizon=90,
        expected_asymmetry="HIGH",
        risk_level="HIGH",
        status=CandidateStatus.ACTIONABLE,
        created_at=datetime(2026, 3, 29, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 29, tzinfo=timezone.utc),
        audit_trail=["seeded for regression test"],
    )
    watch = AlphaCandidate(
        candidate_id="cand-watch-001",
        trigger_id="trigger-watch-001",
        asset_code="600519.SH",
        asset_class="EQUITY",
        direction="LONG",
        strength=SignalStrength.MODERATE,
        confidence=0.7,
        thesis="Watch for confirmation",
        invalidation="PMI falls below 50",
        time_window_start=datetime(2026, 3, 29, tzinfo=timezone.utc).date(),
        time_window_end=datetime(2026, 6, 27, tzinfo=timezone.utc).date(),
        time_horizon=90,
        expected_asymmetry="MED",
        risk_level="MEDIUM",
        status=CandidateStatus.WATCH,
        created_at=datetime(2026, 3, 29, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 29, tzinfo=timezone.utc),
        audit_trail=["seeded for regression test"],
    )

    repo.save(actionable)
    repo.save(watch)

    actionable_list = repo.get_actionable()
    watch_list = repo.get_watch_list()
    by_asset = repo.get_by_asset("000333.SZ")
    by_trigger = repo.get_by_trigger_id("trigger-actionable-001")

    assert any(candidate.candidate_id == actionable.candidate_id for candidate in actionable_list)
    assert any(candidate.candidate_id == watch.candidate_id for candidate in watch_list)
    assert len(by_asset) == 1
    assert by_asset[0].candidate_id == actionable.candidate_id
    assert by_trigger is not None
    assert by_trigger.candidate_id == actionable.candidate_id


@pytest.mark.django_db
def test_alpha_trigger_repository_normalizes_domain_enums_for_persistence():
    repo = AlphaTriggerRepository()
    create_use_case = CreateAlphaTriggerUseCase(repo)
    evaluate_use_case = EvaluateAlphaTriggerUseCase(repo)

    created = create_use_case.execute(
        CreateTriggerRequest(
            trigger_type=TriggerType.MANUAL_OVERRIDE,
            asset_code="600519.SH",
            asset_class="EQUITY",
            direction="LONG",
            trigger_condition={"source": "regression"},
            invalidation_conditions=[{"condition_type": "time_decay", "max_holding_days": 30}],
            confidence=0.95,
            thesis="Regression seed",
            expires_in_days=30,
        )
    )

    assert created.success is True
    assert created.trigger is not None
    assert created.trigger.trigger_type == TriggerType.MANUAL_OVERRIDE
    assert created.trigger.status == TriggerStatus.ACTIVE

    evaluated = evaluate_use_case.execute(
        EvaluateTriggerRequest(trigger_id=created.trigger.trigger_id, current_data={})
    )

    assert evaluated.success is True
    assert evaluated.should_trigger is True

    persisted = repo.get_by_id(created.trigger.trigger_id)
    assert persisted is not None
    assert persisted.trigger_type == TriggerType.MANUAL_OVERRIDE
    assert persisted.status == TriggerStatus.TRIGGERED
