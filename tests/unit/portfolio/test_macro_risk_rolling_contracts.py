"""Contract tests for R4 rolling evidence, studies, and sealed outputs."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind
from apps.portfolio.domain.macro_risk_rolling_contracts import (
    R4MethodBacktestSummary,
    R4RegimeExposureSummary,
    R4RollingExposurePoint,
    R4RollingResearchArtifact,
    R4RollingStudyInput,
)
from apps.portfolio.domain.macro_risk_rolling_service import evaluate_r4_rolling_study
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    build_window,
    candidate_policy,
    promotion_attestation,
    rolling_policy,
    temporal_split,
)

EVALUATED_AT = datetime(2026, 3, 15, tzinfo=UTC)


def test_study_binds_typed_split_embargo_and_owner_projections() -> None:
    study = build_study()

    assert study.temporal_split.embargo_days == 1
    assert tuple(item.fold for item in study.windows) == study.temporal_split.walk_forward_folds
    assert len(study.split_contract_hash) == 64
    assert {item.macro_projection.owner for item in study.windows} == {"macro_factor"}
    assert {item.asset_covariance.owner for item in study.windows} == {"portfolio"}
    assert {item.return_path.owner for item in study.windows} == {"portfolio"}
    assert {item.regime_assignment.owner for item in study.windows} == {"regime"}


def test_study_rejects_windows_not_covering_exact_typed_folds() -> None:
    first = build_window(1)
    second = build_window(2)

    with pytest.raises(ValueError, match="typed split folds exactly"):
        R4RollingStudyInput.create(
            study_id="wrong-fold-order",
            study_version="study.v1",
            temporal_split=temporal_split(),
            candidate_policy=candidate_policy(),
            rolling_policy=rolling_policy(),
            windows=(second, first),
        )


def test_window_rejects_selection_before_validation_is_complete() -> None:
    window = build_window(1)

    with pytest.raises(ValueError, match="must follow the validation window"):
        replace(
            window,
            selection_as_of=datetime(2026, 2, 10, 12, tzinfo=UTC),
        )


def test_covariance_rejects_observation_before_estimation_window_end() -> None:
    covariance = build_window(1).asset_covariance

    with pytest.raises(ValueError, match="before its estimation window ends"):
        replace(
            covariance,
            observed_at=datetime(2026, 2, 9, 12, tzinfo=UTC),
        )


def test_regime_and_candidate_nested_tampering_are_rejected() -> None:
    window = build_window(1)

    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(window.regime_assignment, regime_code="tampered-state")

    equal = next(
        item for item in window.candidates if item.kind is MacroRiskCandidateKind.EQUAL_WEIGHT
    )
    tampered_allocations = (
        replace(equal.allocations[0], candidate_weight=Decimal("0.6")),
        replace(equal.allocations[1], candidate_weight=Decimal("0.4")),
    )
    tampered_candidate = replace(equal, allocations=tampered_allocations)
    candidates = tuple(
        tampered_candidate if item.kind is MacroRiskCandidateKind.EQUAL_WEIGHT else item
        for item in window.candidates
    )
    with pytest.raises(ValueError, match="non-canonical candidate"):
        replace(window, candidates=candidates)


def test_summary_exposure_and_artifact_eligibility_are_derived_and_sealed() -> None:
    artifact = evaluate_r4_rolling_study(
        build_study(),
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
    )

    assert artifact.evidence_complete is True
    assert artifact.eligible_for_research_comparison is True
    with pytest.raises(ValueError, match="eligibility must be derived"):
        replace(artifact, eligible_for_research_comparison=False)
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(
            artifact.exposure_points[0],
            beta=artifact.exposure_points[0].beta + Decimal("0.1"),
        )
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(
            artifact.regime_summaries[0],
            mean_residual_variance=(
                artifact.regime_summaries[0].mean_residual_variance + Decimal("0.001")
            ),
        )
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(
            artifact.method_summaries[0],
            total_expected_cost=artifact.method_summaries[0].total_expected_cost + Decimal("0.1"),
        )


def test_artifact_completeness_rejects_partial_exposure_and_regime_outputs() -> None:
    study = build_study()
    attestation = promotion_attestation()
    artifact = evaluate_r4_rolling_study(
        study,
        promotion_attestation=attestation,
        evaluated_at=EVALUATED_AT,
    )

    missing_exposure = R4RollingResearchArtifact.create(
        study=study,
        promotion_attestation=attestation,
        window_metrics=artifact.window_metrics,
        exposure_points=artifact.exposure_points[:-1],
        regime_summaries=artifact.regime_summaries,
        method_summaries=artifact.method_summaries,
        blockers=(),
        evaluated_at=EVALUATED_AT,
    )
    missing_regime = R4RollingResearchArtifact.create(
        study=study,
        promotion_attestation=attestation,
        window_metrics=artifact.window_metrics,
        exposure_points=artifact.exposure_points,
        regime_summaries=artifact.regime_summaries[:-1],
        method_summaries=artifact.method_summaries,
        blockers=(),
        evaluated_at=EVALUATED_AT,
    )

    assert missing_exposure.evidence_complete is False
    assert missing_exposure.eligible_for_research_comparison is False
    assert missing_regime.evidence_complete is False
    assert missing_regime.eligible_for_research_comparison is False


def test_artifact_completeness_recomputes_source_and_aggregate_values() -> None:
    study = build_study()
    attestation = promotion_attestation()
    artifact = evaluate_r4_rolling_study(
        study,
        promotion_attestation=attestation,
        evaluated_at=EVALUATED_AT,
    )
    target_points = tuple(
        item
        for item in artifact.exposure_points
        if item.asset_code == "asset-a" and item.factor_code == "growth"
    )
    forged_points = tuple(
        (
            R4RollingExposurePoint.create(
                fold_id=item.fold_id,
                regime_code=item.regime_code,
                asset_code=item.asset_code,
                factor_code=item.factor_code,
                beta=item.beta + Decimal("0.1"),
                confidence_low=item.confidence_low,
                confidence_high=item.confidence_high + Decimal("0.1"),
                residual_variance=item.residual_variance,
                r_squared=item.r_squared,
                stability_score=item.stability_score,
            )
            if item in target_points
            else item
        )
        for item in artifact.exposure_points
    )
    target_summary = next(
        item
        for item in artifact.regime_summaries
        if item.asset_code == "asset-a" and item.factor_code == "growth"
    )
    forged_summary = R4RegimeExposureSummary.create(
        regime_code=target_summary.regime_code,
        asset_code=target_summary.asset_code,
        factor_code=target_summary.factor_code,
        window_count=target_summary.window_count,
        mean_beta=target_summary.mean_beta + Decimal("0.1"),
        minimum_beta=target_summary.minimum_beta + Decimal("0.1"),
        maximum_beta=target_summary.maximum_beta + Decimal("0.1"),
        mean_residual_variance=target_summary.mean_residual_variance,
        mean_r_squared=target_summary.mean_r_squared,
        mean_stability_score=target_summary.mean_stability_score,
    )
    forged_regime_summaries = tuple(
        forged_summary if item is target_summary else item for item in artifact.regime_summaries
    )
    target_method = artifact.method_summaries[0]
    forged_method = R4MethodBacktestSummary.create(
        kind=target_method.kind,
        window_count=target_method.window_count,
        compounded_gross_return=target_method.compounded_gross_return,
        realized_variance=target_method.realized_variance,
        maximum_drawdown=target_method.maximum_drawdown,
        total_turnover=target_method.total_turnover,
        total_expected_cost=target_method.total_expected_cost + Decimal("0.1"),
        cost_semantics_version=target_method.cost_semantics_version,
    )

    forged_exposure_artifact = R4RollingResearchArtifact.create(
        study=study,
        promotion_attestation=attestation,
        window_metrics=artifact.window_metrics,
        exposure_points=forged_points,
        regime_summaries=forged_regime_summaries,
        method_summaries=artifact.method_summaries,
        blockers=(),
        evaluated_at=EVALUATED_AT,
    )
    forged_method_artifact = R4RollingResearchArtifact.create(
        study=study,
        promotion_attestation=attestation,
        window_metrics=artifact.window_metrics,
        exposure_points=artifact.exposure_points,
        regime_summaries=artifact.regime_summaries,
        method_summaries=(forged_method, *artifact.method_summaries[1:]),
        blockers=(),
        evaluated_at=EVALUATED_AT,
    )

    assert forged_exposure_artifact.evidence_complete is False
    assert forged_exposure_artifact.eligible_for_research_comparison is False
    assert forged_method_artifact.evidence_complete is False
    assert forged_method_artifact.eligible_for_research_comparison is False


def test_custom_regime_codes_are_preserved_without_hardcoded_taxonomy() -> None:
    study = build_study(
        windows=(
            build_window(1, regime_code="state-from-governed-taxonomy"),
            build_window(2, regime_code="state-from-governed-taxonomy"),
        )
    )
    artifact = evaluate_r4_rolling_study(
        study,
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
    )

    assert {item.regime_code for item in artifact.exposure_points} == {
        "state-from-governed-taxonomy"
    }
    assert artifact.eligible_for_research_comparison is True
