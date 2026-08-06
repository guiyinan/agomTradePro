"""Pure service tests for rolling R4 comparison and regime exposure."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind
from apps.portfolio.domain.macro_risk_rolling_contracts import (
    R4CostTreatment,
    R4RollingBlockerCode,
    R4RollingResearchArtifact,
)
from apps.portfolio.domain.macro_risk_rolling_service import evaluate_r4_rolling_study
from apps.portfolio.domain.r4_rolling_evidence import R4AssetCovarianceEvidence
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    build_window,
    promotion_attestation,
    rebuild_candidate,
    rebuild_window,
)

EVALUATED_AT = datetime(2026, 3, 15, tzinfo=UTC)


def _codes(artifact: R4RollingResearchArtifact) -> set[R4RollingBlockerCode]:
    return {item.code for item in artifact.blockers}


def test_happy_path_recomputes_three_methods_on_each_exact_oos_path() -> None:
    study = build_study()
    artifact = evaluate_r4_rolling_study(
        study,
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
    )

    assert artifact.evidence_complete is True
    assert artifact.eligible_for_research_comparison is True
    assert len(artifact.window_metrics) == 6
    assert len(artifact.method_summaries) == 3
    assert len(artifact.exposure_points) == 8
    assert len(artifact.regime_summaries) == 4
    assert artifact.blockers == ()
    assert artifact.usage_scope == "research_only"
    assert artifact.must_not_use_for_decision is True
    assert artifact.must_not_execute is True
    assert study.rolling_policy.cost_treatment is (
        R4CostTreatment.REPORT_SEPARATELY_FROM_GROSS_RETURN
    )
    equal_fold_one = next(
        item
        for item in artifact.window_metrics
        if item.fold_id == "fold-1" and item.kind is MacroRiskCandidateKind.EQUAL_WEIGHT
    )
    assert equal_fold_one.period_returns == (Decimal("0.015"), Decimal("-0.005"))
    assert equal_fold_one.gross_return == Decimal("0.009925")
    assert equal_fold_one.expected_cost == Decimal("0.001")
    assert equal_fold_one.cost_semantics_version == "gross-cost-reported-separately.v1"


def test_missing_method_blocks_the_entire_study_and_marks_output_incomplete() -> None:
    first = build_window(1)
    incomplete = rebuild_window(
        first,
        candidates=tuple(
            item
            for item in first.candidates
            if item.kind is not MacroRiskCandidateKind.ASSET_RISK_PARITY
        ),
    )
    artifact = evaluate_r4_rolling_study(
        build_study(windows=(incomplete, build_window(2))),
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
    )

    assert artifact.evidence_complete is False
    assert artifact.eligible_for_research_comparison is False
    assert R4RollingBlockerCode.METHOD_FAMILY_INCOMPLETE in _codes(artifact)
    assert R4RollingBlockerCode.STUDY_INCOMPLETE in _codes(artifact)


def test_methods_must_share_snapshot_formation_cost_and_constraint_inputs() -> None:
    first = build_window(1)
    changed = tuple(
        (
            rebuild_candidate(item, cost_model_version="different-cost.v9")
            if item.kind is MacroRiskCandidateKind.ASSET_RISK_PARITY
            else item
        )
        for item in first.candidates
    )
    artifact = evaluate_r4_rolling_study(
        build_study(windows=(rebuild_window(first, candidates=changed), build_window(2))),
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
    )

    assert artifact.evidence_complete is True
    assert artifact.eligible_for_research_comparison is False
    assert R4RollingBlockerCode.METHOD_INPUT_MISMATCH in _codes(artifact)


def test_equal_weight_and_asset_risk_parity_are_recomputed_not_caller_claimed() -> None:
    first = build_window(1)
    changed = []
    for candidate in first.candidates:
        if candidate.kind is MacroRiskCandidateKind.EQUAL_WEIGHT:
            allocations = (
                replace(candidate.allocations[0], candidate_weight=Decimal("0.6")),
                replace(candidate.allocations[1], candidate_weight=Decimal("0.4")),
            )
            changed.append(rebuild_candidate(candidate, allocations=allocations))
        elif candidate.kind is MacroRiskCandidateKind.ASSET_RISK_PARITY:
            allocations = (
                replace(candidate.allocations[0], candidate_weight=Decimal("0.5")),
                replace(candidate.allocations[1], candidate_weight=Decimal("0.5")),
            )
            changed.append(rebuild_candidate(candidate, allocations=allocations))
        else:
            changed.append(candidate)
    artifact = evaluate_r4_rolling_study(
        build_study(
            windows=(
                rebuild_window(first, candidates=tuple(changed)),
                build_window(2),
            )
        ),
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
    )

    assert R4RollingBlockerCode.EQUAL_WEIGHT_MISMATCH in _codes(artifact)
    assert R4RollingBlockerCode.ASSET_RISK_PARITY_MISMATCH in _codes(artifact)
    assert artifact.eligible_for_research_comparison is False


def test_non_psd_asset_covariance_fails_closed() -> None:
    first = build_window(1)
    covariance = R4AssetCovarianceEvidence.create(
        covariance_id=first.asset_covariance.covariance_id,
        covariance_version=first.asset_covariance.covariance_version,
        universe_id=first.asset_covariance.universe_id,
        universe_hash=first.asset_covariance.universe_hash,
        asset_codes=first.asset_covariance.asset_codes,
        values=((Decimal("0.01"), Decimal("0.02")), (Decimal("0.02"), Decimal("0.01"))),
        estimator_version=first.asset_covariance.estimator_version,
        estimation_window=first.asset_covariance.estimation_window,
        observed_at=first.asset_covariance.observed_at,
        available_at=first.asset_covariance.available_at,
        knowledge_as_of=first.asset_covariance.knowledge_as_of,
        valid_until=first.asset_covariance.valid_until,
        pit_manifest_id=first.asset_covariance.pit_manifest_id,
        pit_manifest_hash=first.asset_covariance.pit_manifest_hash,
        source_content_hashes=first.asset_covariance.source_content_hashes,
    )
    artifact = evaluate_r4_rolling_study(
        build_study(
            windows=(
                rebuild_window(first, asset_covariance=covariance),
                build_window(2),
            )
        ),
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
    )

    assert R4RollingBlockerCode.ASSET_COVARIANCE_INVALID in _codes(artifact)
    assert artifact.eligible_for_research_comparison is False


def test_future_regime_assignment_and_insufficient_regime_samples_block() -> None:
    first = build_window(
        1,
        regime_code="state-a",
        regime_available_at=datetime(2026, 2, 11, 13, tzinfo=UTC),
    )
    second = build_window(2, regime_code="state-b")
    artifact = evaluate_r4_rolling_study(
        build_study(windows=(first, second), minimum_regime_windows=2),
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
    )

    assert R4RollingBlockerCode.REGIME_EVIDENCE_INVALID in _codes(artifact)
    assert R4RollingBlockerCode.REGIME_SAMPLE_INSUFFICIENT in _codes(artifact)
    assert artifact.eligible_for_research_comparison is False


def test_expired_or_wrong_r3_attestation_is_a_stable_domain_blocker() -> None:
    expired = promotion_attestation(valid_until=datetime(2026, 3, 1, tzinfo=UTC))
    artifact = evaluate_r4_rolling_study(
        build_study(),
        promotion_attestation=expired,
        evaluated_at=EVALUATED_AT,
    )

    assert R4RollingBlockerCode.R3_PROMOTION_INVALID in _codes(artifact)
    assert artifact.eligible_for_research_comparison is False

    retired = promotion_attestation(retired_at=EVALUATED_AT - timedelta(days=1))
    retired_artifact = evaluate_r4_rolling_study(
        build_study(),
        promotion_attestation=retired,
        evaluated_at=EVALUATED_AT,
    )
    assert R4RollingBlockerCode.R3_PROMOTION_INVALID in _codes(retired_artifact)
