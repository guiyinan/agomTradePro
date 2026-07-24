"""Alpha Trigger repository lifecycle, filtering, and statistics contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.alpha_trigger.domain.entities import (
    AlphaCandidate,
    AlphaTrigger,
    CandidateStatus,
    InvalidationCondition,
    InvalidationType,
    SignalStrength,
    TriggerStatus,
    TriggerType,
)
from apps.alpha_trigger.infrastructure.repositories import (
    AlphaCandidateRepository,
    AlphaTriggerRepository,
)


def _trigger() -> AlphaTrigger:
    return AlphaTrigger(
        trigger_id="trigger-repository-contract",
        trigger_type=TriggerType.MOMENTUM_SIGNAL,
        asset_code="000001.SZ",
        asset_class="a_股票",
        direction="LONG",
        trigger_condition={"momentum_pct": 0.05},
        invalidation_conditions=[
            InvalidationCondition(
                condition_type=InvalidationType.THRESHOLD_CROSS,
                indicator_code="PMI",
                threshold_value=50.0,
                cross_direction="below",
            )
        ],
        strength=SignalStrength.STRONG,
        confidence=0.8,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        status=TriggerStatus.ACTIVE,
        source_signal_id="signal-1",
        related_regime="Recovery",
        thesis="repository contract",
    )


def _candidate() -> AlphaCandidate:
    return AlphaCandidate(
        candidate_id="candidate-repository-contract",
        trigger_id="trigger-repository-contract",
        asset_code="000001.SZ",
        asset_class="a_股票",
        direction="LONG",
        strength=SignalStrength.STRONG,
        confidence=0.8,
        thesis="repository contract",
        time_window_start=date.today(),
        time_window_end=date.today() + timedelta(days=30),
        status=CandidateStatus.WATCH,
    )


@pytest.mark.django_db
def test_trigger_repository_round_trip_filters_status_statistics_and_delete() -> None:
    """Trigger repository preserves domain fields across its complete lifecycle."""
    repo = AlphaTriggerRepository()
    saved = repo.save(_trigger())
    assert saved.trigger_id == "trigger-repository-contract"
    assert repo.get_by_id(saved.trigger_id) is not None
    assert repo.get_by_signal_id("signal-1") is not None
    assert len(repo.get_active(asset_code="000001.SZ", min_strength=SignalStrength.MODERATE)) == 1
    assert len(repo.get_by_asset("000001.SZ")) == 1
    assert len(repo.get_by_regime("Recovery")) == 1
    assert len(repo.get_by_type(TriggerType.MOMENTUM_SIGNAL)) == 1
    assert repo.count_all() == 1
    assert repo.get_trigger_type_choices()
    expired = replace(
        _trigger(),
        trigger_id="trigger-expired-contract",
        source_signal_id="signal-2",
        created_at=datetime.now(UTC) - timedelta(days=2),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    repo.save(expired)
    assert len(repo.get_expired()) == 1
    assert len(repo.list_active_models(limit=10)) == 1
    assert len(repo.list_models_by_statuses(["ACTIVE"], limit=10)) == 1

    triggered = repo.update_status(
        saved.trigger_id,
        TriggerStatus.TRIGGERED,
        triggered_at=datetime.now(UTC),
    )
    assert triggered.status == TriggerStatus.TRIGGERED
    assert repo.get_statistics()["total"] == 2
    assert repo.delete(saved.trigger_id) is True
    assert repo.delete(saved.trigger_id) is True
    assert repo.delete(expired.trigger_id) is True


@pytest.mark.django_db
def test_candidate_repository_round_trip_status_execution_and_statistics() -> None:
    """Candidate status and decision linkage updates remain queryable and idempotent."""
    trigger_repo = AlphaTriggerRepository()
    trigger_repo.save(_trigger())
    repo = AlphaCandidateRepository()
    saved = repo.save(_candidate())
    assert repo.get_by_id(saved.candidate_id) is not None
    assert repo.get_by_trigger_id(saved.trigger_id) is not None
    assert len(repo.get_by_asset("000001.SZ")) == 1
    assert len(repo.get_watch_list()) == 1
    assert repo.count_by_status("WATCH") == 1

    actionable = repo.update_status(saved.candidate_id, CandidateStatus.ACTIONABLE)
    assert actionable.status == CandidateStatus.ACTIONABLE.value
    assert len(repo.get_actionable()) == 1
    assert repo.update_last_decision_request_id(saved.candidate_id, "request-1") is True
    assert repo.update_status_to_rejected(saved.candidate_id) is True
    assert repo.update_status_to_executed(saved.candidate_id) is True
    assert repo.update_execution_status_to_failed(saved.candidate_id) is True
    assert repo.get_statistics()["total"] == 1
    assert repo.delete(saved.candidate_id) is True
    assert repo.delete(saved.candidate_id) is True
