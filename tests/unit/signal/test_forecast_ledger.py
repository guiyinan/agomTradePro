from datetime import UTC, datetime, timedelta

import pytest

from apps.audit.infrastructure.forecast_scoreboard_repository import ForecastScoreboardRepository
from apps.signal.application.forecast_use_cases import (
    FinalizeForecastOutcomeUseCase,
    RecordForecastEvaluationUseCase,
    RecordForecastLedgerEntryUseCase,
)
from apps.signal.infrastructure.forecast_repositories import ForecastEvaluationRepository
from apps.signal.infrastructure.models import InvestmentSignalModel


@pytest.mark.django_db
def test_forecast_ledger_preserves_checks_and_scores_relative_return() -> None:
    repository = ForecastEvaluationRepository()
    published_at = datetime(2025, 1, 1, tzinfo=UTC)
    entry = RecordForecastLedgerEntryUseCase(repository).execute(
        entry_id="forecast-1",
        published_at=published_at,
        direction="LONG",
        asset_code="000001.SZ",
        horizon_end=published_at + timedelta(days=30),
        benchmark_asset="000300.SH",
        probability=0.8,
        invalidation_rule_version="rule-v1",
        decision_snapshot_id="decision-v1",
        pit_manifest_id="manifest-v1",
        strategy_version="strategy-v1",
        model_version="model-v1",
        prompt_version="prompt-v1",
        source="strategy",
        regime="recovery",
    )
    checked_at = published_at + timedelta(days=1)
    first = RecordForecastEvaluationUseCase(repository).execute(
        entry_id=entry.entry_id,
        checked_at=checked_at,
        data_version_ids=[1, 2],
        conditions=[{"name": "price_floor", "actual": 10, "threshold": 9, "triggered": False}],
    )
    repeated = RecordForecastEvaluationUseCase(repository).execute(
        entry_id=entry.entry_id,
        checked_at=checked_at,
        data_version_ids=[1, 2],
        conditions=[{"name": "price_floor", "actual": 10, "threshold": 9, "triggered": False}],
    )
    RecordForecastEvaluationUseCase(repository).execute(
        entry_id=entry.entry_id,
        checked_at=checked_at + timedelta(days=1),
        data_version_ids=[3],
        conditions=[
            {
                "name": "price_floor",
                "actual": 8,
                "threshold": 9,
                "triggered": True,
            }
        ],
    )
    outcome = FinalizeForecastOutcomeUseCase(repository).execute(
        entry_id=entry.entry_id,
        finalized_at=published_at + timedelta(days=30),
        outcome_type="expired",
        asset_return=0.10,
        benchmark_return=0.04,
        neutral_band=0.01,
    )

    assert first.evaluation_id == repeated.evaluation_id
    assert outcome.hit is True
    assert outcome.excess_return == pytest.approx(0.06)
    assert outcome.brier_score == pytest.approx(0.04)
    scoreboard = ForecastScoreboardRepository().summarize("source")
    assert scoreboard["results"][0]["hit_rate"] == 1.0
    assert scoreboard["results"][0]["sample_count"] == 1
    assert scoreboard["results"][0]["invalidation_rate"] == 1.0
    assert scoreboard["results"][0]["average_invalidation_hours"] == 48.0
    assert scoreboard["results"][0]["ranking_eligible"] is False


@pytest.mark.django_db
def test_forecast_ledger_rejects_idempotency_collisions() -> None:
    repository = ForecastEvaluationRepository()
    published_at = datetime(2025, 1, 1, tzinfo=UTC)
    payload = {
        "entry_id": "forecast-collision",
        "published_at": published_at,
        "direction": "LONG",
        "asset_code": "000001.SZ",
        "horizon_end": published_at + timedelta(days=30),
        "benchmark_asset": "000300.SH",
        "probability": 0.8,
        "invalidation_rule_version": "rule-v1",
        "decision_snapshot_id": "decision-v1",
        "pit_manifest_id": "manifest-v1",
        "source": "strategy",
    }
    RecordForecastLedgerEntryUseCase(repository).execute(**payload)

    with pytest.raises(ValueError, match="different evidence"):
        RecordForecastLedgerEntryUseCase(repository).execute(**{**payload, "probability": 0.9})


@pytest.mark.django_db
def test_scheduled_signal_check_is_recorded_and_cutover_fails_closed(settings) -> None:
    repository = ForecastEvaluationRepository()
    published_at = datetime(2025, 1, 1, tzinfo=UTC)
    signal = InvestmentSignalModel.objects.create(
        asset_code="000001.SZ",
        asset_class="a_share_growth",
        direction="LONG",
        logic_desc="PIT-linked signal",
        invalidation_logic="PMI falls below 50",
        invalidation_threshold=50,
        target_regime="Recovery",
        status="approved",
    )
    entry = RecordForecastLedgerEntryUseCase(repository).execute(
        entry_id="forecast-linked",
        signal_id=signal.id,
        published_at=published_at,
        direction="LONG",
        asset_code="000001.SZ",
        horizon_end=published_at + timedelta(days=30),
        benchmark_asset="000300.SH",
        probability=0.8,
        invalidation_rule_version="rule-v1",
        decision_snapshot_id="decision-v1",
        pit_manifest_id="manifest-v1",
        source="strategy",
    )

    evaluation = repository.record_evaluation_for_signal(
        signal_id=str(signal.id),
        checked_at=published_at + timedelta(days=1),
        data_version_ids=[],
        conditions=[{"indicator_code": "PMI", "triggered": False}],
        missing_reason="legacy_invalidation_source_has_no_pit_version_ids",
    )

    assert evaluation is not None
    assert evaluation.entry_id == entry.entry_id
    settings.SIGNAL_FORECAST_LEDGER_ENABLED = True
    with pytest.raises(ValueError, match="has no forecast ledger entry"):
        repository.record_evaluation_for_signal(
            signal_id="999999",
            checked_at=published_at + timedelta(days=1),
            data_version_ids=[],
            conditions=[],
            missing_reason="signal_not_linked",
        )
