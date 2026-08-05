"""Tests for the R6 simple-baseline shortfall evidence gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.application.state_model_baseline import (
    EvaluateSimpleBaselineShortfallUseCase,
)
from apps.research.domain.state_model_baseline import (
    BaselineEvaluationEvidence,
    BaselineEvaluationSpecification,
    BaselineEvidenceState,
    BaselineMetricCriterion,
    BaselineMetricObservation,
    BaselineShortfallDecision,
    ShortfallDirection,
    evaluate_baseline_shortfall,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _specification() -> BaselineEvaluationSpecification:
    return BaselineEvaluationSpecification(
        specification_version="regime-simple-shortfall.v1",
        baseline_key="regime.simple.pmi-cpi",
        baseline_version="regime-v2",
        pit_manifest_id="pit-regime-evaluation-v1",
        window_start=NOW - timedelta(days=365),
        window_end=NOW - timedelta(days=1),
        minimum_observations=100,
        criteria=(
            BaselineMetricCriterion(
                metric_key="transition_false_negative_rate",
                unit="ratio",
                direction=ShortfallDirection.ABOVE_MAXIMUM,
                threshold=Decimal("0.20"),
            ),
            BaselineMetricCriterion(
                metric_key="decision_loss_utility",
                unit="score",
                direction=ShortfallDirection.BELOW_MINIMUM,
                threshold=Decimal("0.70"),
            ),
        ),
        approved_by="research-owner",
        activated_at=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
    )


def _evidence(
    *,
    metrics: tuple[BaselineMetricObservation, ...] | None = None,
    observation_count: int = 120,
    state: BaselineEvidenceState = BaselineEvidenceState.VERIFIED,
    blocking_reason: str | None = None,
) -> BaselineEvaluationEvidence:
    specification = _specification()
    return BaselineEvaluationEvidence(
        evaluation_id="baseline-evaluation-v1",
        specification_version=specification.specification_version,
        baseline_key=specification.baseline_key,
        baseline_version=specification.baseline_version,
        pit_manifest_id=specification.pit_manifest_id,
        state=state,
        window_start=specification.window_start,
        window_end=specification.window_end,
        observation_count=observation_count,
        evaluated_at=NOW - timedelta(hours=1),
        valid_until=(NOW + timedelta(days=7) if state is BaselineEvidenceState.VERIFIED else None),
        metrics=(
            metrics
            if metrics is not None
            else (
                BaselineMetricObservation(
                    "transition_false_negative_rate",
                    "ratio",
                    Decimal("0.25"),
                ),
                BaselineMetricObservation(
                    "decision_loss_utility",
                    "score",
                    Decimal("0.60"),
                ),
            )
        ),
        evidence_refs=("pit://regime-evaluation-v1",),
        blocking_reason=blocking_reason,
    )


def test_complete_pit_evidence_can_prove_simple_baseline_shortfall() -> None:
    report = evaluate_baseline_shortfall(
        specification=_specification(),
        evidence=_evidence(),
        evaluated_at=NOW,
    )

    assert report.decision is BaselineShortfallDecision.PROVEN
    assert report.can_propose_advanced_model_research is True
    assert report.blockers == ()
    assert report.baseline_key == "regime.simple.pmi-cpi"
    assert report.baseline_version == "regime-v2"
    assert report.pit_manifest_id == "pit-regime-evaluation-v1"
    assert report.window_start == _specification().window_start
    assert report.metrics == _evidence().metrics
    assert report.content_hash == report.calculated_content_hash


def test_shortfall_report_hash_seals_raw_metrics_and_evidence_identity() -> None:
    report = evaluate_baseline_shortfall(
        specification=_specification(),
        evidence=_evidence(),
        evaluated_at=NOW,
    )

    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(
            report,
            metrics=(
                replace(report.metrics[0], value=Decimal("0.99")),
                *report.metrics[1:],
            ),
        )
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(report, pit_manifest_id="pit-rewritten")


def test_metrics_below_shortfall_boundaries_do_not_justify_advanced_model() -> None:
    evidence = _evidence(
        metrics=(
            BaselineMetricObservation(
                "transition_false_negative_rate",
                "ratio",
                Decimal("0.10"),
            ),
            BaselineMetricObservation(
                "decision_loss_utility",
                "score",
                Decimal("0.80"),
            ),
        )
    )

    report = evaluate_baseline_shortfall(
        specification=_specification(),
        evidence=evidence,
        evaluated_at=NOW,
    )

    assert report.decision is BaselineShortfallDecision.NOT_PROVEN
    assert report.can_propose_advanced_model_research is False
    assert report.metric_results == (
        ("transition_false_negative_rate", False),
        ("decision_loss_utility", False),
    )


def test_incomplete_or_small_sample_evidence_fails_closed() -> None:
    report = evaluate_baseline_shortfall(
        specification=_specification(),
        evidence=_evidence(
            observation_count=20,
            state=BaselineEvidenceState.UNVERIFIED,
            blocking_reason="PIT evaluation run is awaiting review",
        ),
        evaluated_at=NOW,
    )

    assert report.decision is BaselineShortfallDecision.BLOCKED
    assert report.can_propose_advanced_model_research is False
    assert {item.reason_code for item in report.blockers} == {
        "state_model_baseline.evidence.unverified",
        "state_model_baseline.sample.insufficient",
    }


def test_missing_metric_and_unit_drift_are_not_silently_accepted() -> None:
    missing = _evidence(
        metrics=(
            BaselineMetricObservation(
                "transition_false_negative_rate",
                "ratio",
                Decimal("0.25"),
            ),
        )
    )
    missing_report = evaluate_baseline_shortfall(
        specification=_specification(),
        evidence=missing,
        evaluated_at=NOW,
    )
    assert missing_report.decision is BaselineShortfallDecision.BLOCKED
    assert missing_report.blockers[0].metric_key == "decision_loss_utility"

    wrong_unit = _evidence(
        metrics=(
            BaselineMetricObservation(
                "transition_false_negative_rate",
                "percent",
                Decimal("0.25"),
            ),
            BaselineMetricObservation(
                "decision_loss_utility",
                "score",
                Decimal("0.60"),
            ),
        )
    )
    with pytest.raises(ValueError, match="unit mismatch"):
        evaluate_baseline_shortfall(
            specification=_specification(),
            evidence=wrong_unit,
            evaluated_at=NOW,
        )


def test_evidence_cannot_switch_manifest_or_baseline_version() -> None:
    evidence = _evidence()
    mismatched = BaselineEvaluationEvidence(
        **{
            **evidence.__dict__,
            "pit_manifest_id": "future-revised-manifest",
        }
    )

    with pytest.raises(ValueError, match="does not match"):
        evaluate_baseline_shortfall(
            specification=_specification(),
            evidence=mismatched,
            evaluated_at=NOW,
        )


class _SpecificationProvider:
    def get_active(
        self,
        *,
        baseline_key: str,
        evaluated_at: datetime,
    ) -> BaselineEvaluationSpecification:
        assert baseline_key == "regime.simple.pmi-cpi"
        assert evaluated_at == NOW
        return _specification()


class _EvidenceProvider:
    def get_latest(
        self,
        *,
        specification: BaselineEvaluationSpecification,
        evaluated_at: datetime,
    ) -> BaselineEvaluationEvidence:
        assert specification == _specification()
        assert evaluated_at == NOW
        return _evidence()


def test_application_uses_versioned_specification_and_frozen_evidence() -> None:
    report = EvaluateSimpleBaselineShortfallUseCase(
        specification_provider=_SpecificationProvider(),
        evidence_provider=_EvidenceProvider(),
    ).execute(
        baseline_key="regime.simple.pmi-cpi",
        evaluated_at=NOW,
    )

    assert report.can_propose_advanced_model_research is True
