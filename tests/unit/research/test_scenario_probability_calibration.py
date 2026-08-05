"""Unit coverage for fail-closed R7 scenario calibration research."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from apps.research.domain.scenario_probability_calibration import (
    evaluate_scenario_probability_calibration,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ResearchEvidenceStatus,
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
SET_REVISION = UUID("00000000-0000-0000-0000-000000000100")
REVISION_A = UUID("00000000-0000-0000-0000-000000000001")
REVISION_B = UUID("00000000-0000-0000-0000-000000000002")


def _scope() -> ScenarioResearchScope:
    return ScenarioResearchScope.create(
        scope_version="scenario-scope.v1",
        scenario_set_revision_id=SET_REVISION,
        scenario_revision_ids=(REVISION_B, REVISION_A),
        forecast_horizon=timedelta(days=1),
        censoring_rule_version="scenario-censoring.v1",
        path_horizon_periods=2,
        path_initial_state_revision_ids=(REVISION_A, REVISION_B),
    )


def _policy(
    *,
    minimum_forecasts: int = 2,
    minimum_resolved: int = 2,
    minimum_coverage: Decimal = Decimal("1"),
    minimum_binary_class: int = 1,
    minimum_multiclass_groups: int = 2,
    minimum_multiclass_class: int = 1,
    activated_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> ScenarioProbabilityResearchPolicy:
    return ScenarioProbabilityResearchPolicy.create(
        policy_version="scenario-calibration-policy.v1",
        activated_at=activated_at or NOW - timedelta(days=30),
        valid_until=valid_until or NOW + timedelta(days=30),
        sample_window_start=datetime(2026, 8, 1, tzinfo=UTC),
        sample_window_end=datetime(2026, 8, 4, tzinfo=UTC),
        forecast_horizon=timedelta(days=1),
        censoring_lag=timedelta(days=7),
        censoring_rule_version="scenario-censoring.v1",
        minimum_forecasts_per_revision=minimum_forecasts,
        minimum_resolved_outcomes_per_revision=minimum_resolved,
        minimum_outcome_coverage=minimum_coverage,
        minimum_binary_class_observations=minimum_binary_class,
        minimum_multiclass_groups=minimum_multiclass_groups,
        minimum_multiclass_class_observations=minimum_multiclass_class,
        maximum_outcome_evidence_age=timedelta(days=365),
        calibration_bin_edges=(Decimal("0"), Decimal("0.5"), Decimal("1")),
        probability_sum_tolerance=Decimal("0.000001"),
        minimum_historical_analogies=2,
        minimum_path_probability_observations=10,
        path_horizon_periods=2,
        require_all_path_initial_states=True,
        maximum_research_evidence_age=timedelta(days=90),
        invalidation_review_delay=timedelta(days=1),
        approved_by="research-owner",
    )


def _observation(
    *,
    entry_id: str,
    group_id: str,
    revision_id: UUID,
    subjective_probability: str,
    scenario_realized: bool | None,
    published_at: datetime,
    model_probability: str | None = None,
    outcome_valid_until: datetime | None = None,
    horizon: timedelta = timedelta(days=1),
) -> ForecastLedgerOutcomeObservation:
    binding = ScenarioForecastBinding.from_values(
        scenario_revision_id=revision_id,
        scenario_set_revision_id=SET_REVISION,
        subjective_probability=subjective_probability,
        subjective_probability_source_version="committee-v1",
        model_probability=model_probability,
        model_probability_source_version=(
            "promoted-model-v1" if model_probability is not None else None
        ),
        model_promotion_decision_id=(
            "promotion-model-v1" if model_probability is not None else None
        ),
    )
    horizon_end = published_at + horizon
    recorded_at = horizon_end + timedelta(hours=1) if scenario_realized is not None else None
    return ForecastLedgerOutcomeObservation.create(
        observation_version="ledger-observation.v1",
        entry_id=entry_id,
        forecast_group_id=group_id,
        binding=binding,
        pit_manifest_id=f"pit-{group_id}",
        pit_manifest_version="pit-manifest.v1",
        pit_manifest_hash=hashlib.sha256(f"pit-{group_id}".encode()).hexdigest(),
        censoring_rule_version="scenario-censoring.v1",
        published_at=published_at,
        horizon_end=horizon_end,
        scenario_realized=scenario_realized,
        outcome_recorded_at=recorded_at,
        outcome_evidence_valid_until=(
            outcome_valid_until if scenario_realized is not None else None
        )
        or (NOW + timedelta(days=30) if scenario_realized is not None else None),
    )


def _complete_observations(
    *,
    include_model: bool = False,
) -> tuple[ForecastLedgerOutcomeObservation, ...]:
    model_values = ("0.20", "0.80", "0.80", "0.20") if include_model else (None, None, None, None)
    return (
        _observation(
            entry_id="g1-a",
            group_id="g1",
            revision_id=REVISION_A,
            subjective_probability="0.70",
            model_probability=model_values[0],
            scenario_realized=True,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _observation(
            entry_id="g1-b",
            group_id="g1",
            revision_id=REVISION_B,
            subjective_probability="0.30",
            model_probability=model_values[1],
            scenario_realized=False,
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        _observation(
            entry_id="g2-a",
            group_id="g2",
            revision_id=REVISION_A,
            subjective_probability="0.40",
            model_probability=model_values[2],
            scenario_realized=False,
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
        _observation(
            entry_id="g2-b",
            group_id="g2",
            revision_id=REVISION_B,
            subjective_probability="0.60",
            model_probability=model_values[3],
            scenario_realized=True,
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
    )


def test_subjective_brier_multiclass_brier_and_bin_hits_are_revision_bound() -> None:
    report = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(),
        observations=_complete_observations(),
        evaluated_at=NOW,
    )

    assert report.subjective.status is ResearchEvidenceStatus.AVAILABLE
    assert report.trains_probability_model is False
    assert report.research_only is True
    assert len(report.content_hash) == 64
    metrics_a = next(
        metric
        for metric in report.subjective.revision_metrics
        if metric.scenario_revision_id == REVISION_A
    )
    assert metrics_a.mean_brier_score == Decimal("0.125")
    assert metrics_a.outcome_coverage == Decimal("1")
    assert tuple(bin_result.observed_hit_rate for bin_result in metrics_a.bins) == (
        Decimal("0"),
        Decimal("1"),
    )
    assert report.subjective.multiclass_metrics is not None
    assert report.subjective.multiclass_metrics.mean_multiclass_brier_score == Decimal("0.25")


def test_model_probability_metrics_never_overwrite_subjective_metrics() -> None:
    report = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(),
        observations=_complete_observations(include_model=True),
        evaluated_at=NOW,
    )

    subjective_a = next(
        metric
        for metric in report.subjective.revision_metrics
        if metric.scenario_revision_id == REVISION_A
    )
    model_a = next(
        metric
        for metric in report.model_inferred.revision_metrics
        if metric.scenario_revision_id == REVISION_A
    )
    assert subjective_a.mean_brier_score == Decimal("0.125")
    assert model_a.mean_brier_score == Decimal("0.64")
    assert report.model_inferred.multiclass_metrics is not None
    assert report.model_inferred.multiclass_metrics.mean_multiclass_brier_score == Decimal("1.28")
    assert subjective_a.probability_source_version == "committee-v1"
    assert model_a.probability_source_version == "promoted-model-v1"


def test_no_real_outcomes_returns_insufficient_evidence_without_metrics_or_model() -> None:
    rows = tuple(
        replace(
            row,
            scenario_realized=None,
            outcome_recorded_at=None,
            outcome_evidence_valid_until=None,
            content_hash=ForecastLedgerOutcomeObservation.create(
                observation_version=row.observation_version,
                entry_id=row.entry_id,
                forecast_group_id=row.forecast_group_id,
                binding=row.binding,
                pit_manifest_id=row.pit_manifest_id,
                pit_manifest_version=row.pit_manifest_version,
                pit_manifest_hash=row.pit_manifest_hash,
                censoring_rule_version=row.censoring_rule_version,
                published_at=row.published_at,
                horizon_end=row.horizon_end,
                scenario_realized=None,
                outcome_recorded_at=None,
                outcome_evidence_valid_until=None,
            ).content_hash,
        )
        for row in _complete_observations()
    )

    report = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(),
        observations=rows,
        evaluated_at=NOW,
    )

    assert report.subjective.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert report.subjective.revision_metrics == ()
    assert report.subjective.multiclass_metrics is None
    assert report.model_inferred.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert report.model_inferred.revision_metrics == ()
    assert report.trains_probability_model is False


def test_minimum_sample_coverage_and_class_support_are_policy_gated() -> None:
    rows = _complete_observations()[:2]
    report = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(
            minimum_forecasts=2,
            minimum_resolved=2,
            minimum_coverage=Decimal("1"),
            minimum_binary_class=1,
        ),
        observations=rows,
        evaluated_at=NOW,
    )

    codes = {blocker.reason_code for blocker in report.subjective.blockers}
    assert report.subjective.status is ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
    assert "scenario_calibration.sample.forecasts_insufficient" in codes
    assert "scenario_calibration.sample.binary_class_support_insufficient" in codes
    assert "scenario_calibration.multiclass.groups_insufficient" in codes
    assert report.subjective.revision_metrics == ()


def test_expired_policy_or_outcome_evidence_fails_closed() -> None:
    expired_row = _observation(
        entry_id="expired-a",
        group_id="expired",
        revision_id=REVISION_A,
        subjective_probability="0.50",
        scenario_realized=True,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        outcome_valid_until=NOW,
    )
    rows = (expired_row, *_complete_observations())
    report = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(),
        observations=rows,
        evaluated_at=NOW,
    )
    assert report.subjective.status is ResearchEvidenceStatus.BLOCKED
    assert any("expired" in item.reason_code for item in report.subjective.blockers)

    inactive = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(
            activated_at=NOW - timedelta(days=60),
            valid_until=NOW - timedelta(days=1),
        ),
        observations=_complete_observations(),
        evaluated_at=NOW,
    )
    assert inactive.subjective.status is ResearchEvidenceStatus.BLOCKED


def test_scope_mismatch_and_hash_tampering_are_rejected() -> None:
    row = _complete_observations()[0]
    wrong_scope = ScenarioResearchScope.create(
        scope_version="scenario-scope.v1",
        scenario_set_revision_id=UUID("00000000-0000-0000-0000-000000000999"),
        scenario_revision_ids=(REVISION_A, REVISION_B),
        forecast_horizon=timedelta(days=1),
        censoring_rule_version="scenario-censoring.v1",
        path_horizon_periods=2,
        path_initial_state_revision_ids=(REVISION_A, REVISION_B),
    )
    with pytest.raises(ValueError, match="scenario-set revision mismatch"):
        evaluate_scenario_probability_calibration(
            scope=wrong_scope,
            policy=_policy(),
            observations=(row,),
            evaluated_at=NOW,
        )
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(row, content_hash="0" * 64)


def test_exact_horizon_and_multiclass_group_identity_are_enforced() -> None:
    wrong_horizon = _observation(
        entry_id="wrong-horizon-a",
        group_id="wrong-horizon",
        revision_id=REVISION_A,
        subjective_probability="0.50",
        scenario_realized=True,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        horizon=timedelta(days=2),
    )
    with pytest.raises(ValueError, match="horizon does not match exact scope"):
        evaluate_scenario_probability_calibration(
            scope=_scope(),
            policy=_policy(),
            observations=(wrong_horizon,),
            evaluated_at=NOW,
        )

    rows = list(_complete_observations())
    rows[1] = _observation(
        entry_id="g1-b",
        group_id="g1",
        revision_id=REVISION_B,
        subjective_probability="0.30",
        scenario_realized=False,
        published_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
    )
    report = evaluate_scenario_probability_calibration(
        scope=_scope(),
        policy=_policy(),
        observations=tuple(rows),
        evaluated_at=NOW,
    )
    assert report.subjective.status is ResearchEvidenceStatus.BLOCKED
    assert any(
        blocker.reason_code == "scenario_calibration.multiclass.group_identity_mixed"
        for blocker in report.subjective.blockers
    )
