"""Deterministic factories for R4 rolling research unit tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from apps.macro_factor.domain.entities import SampleWindow, TemporalSplitSpec, WalkForwardFold
from apps.portfolio.domain.macro_factor_risk import (
    AssetAllocation,
    AssetMacroExposure,
    FactorCovarianceVersion,
    MacroExposureVersion,
    MacroFactorBeta,
    MacroRiskCandidateInput,
    MacroRiskCandidateKind,
    MacroRiskValidationPolicy,
    build_macro_risk_input_hash,
)
from apps.portfolio.domain.macro_risk_rolling_contracts import (
    R4CostTreatment,
    R4RollingStudyInput,
    R4RollingValidationPolicy,
    R4RollingWindowInput,
)
from apps.portfolio.domain.r4_rolling_evidence import (
    ExactR3PromotionAttestation,
    R4AssetCovarianceEvidence,
    R4AssetReturn,
    R4MacroExposureProjectionEvidence,
    R4OOSReturnPathEvidence,
    R4RegimeAssignmentEvidence,
    R4ReturnObservation,
)

UNIVERSE_HASH = "2" * 64
PIT_MANIFEST_HASH = "3" * 64
SOURCE_HASH = "4" * 64
FACTOR_ARTIFACT_HASH = "5" * 64
PROMOTION_DECISION_HASH = "6" * 64


def candidate_policy() -> MacroRiskValidationPolicy:
    """Return exact candidate-validation tolerances."""

    return MacroRiskValidationPolicy(
        version="r4-candidate-policy.v1",
        weight_sum_tolerance=Decimal("0.00000001"),
        covariance_symmetry_tolerance=Decimal("0.00000001"),
        covariance_psd_tolerance=Decimal("0.00000001"),
        contribution_identity_tolerance=Decimal("0.00000001"),
        minimum_r_squared=Decimal("0.2"),
        minimum_stability_score=Decimal("0.5"),
        maximum_turnover=Decimal("0.8"),
        maximum_expected_cost=Decimal("0.02"),
        macro_risk_parity_tolerance=Decimal("0.00000001"),
    )


def rolling_policy(*, minimum_regime_windows: int = 2) -> R4RollingValidationPolicy:
    """Return versioned benchmark and gross-cost semantics."""

    return R4RollingValidationPolicy(
        version="r4-rolling-policy.v1",
        cost_semantics_version="gross-cost-reported-separately.v1",
        cost_treatment=R4CostTreatment.REPORT_SEPARATELY_FROM_GROSS_RETURN,
        weight_tolerance=Decimal("0.00000001"),
        covariance_symmetry_tolerance=Decimal("0.00000001"),
        covariance_psd_tolerance=Decimal("0.00000001"),
        asset_risk_parity_tolerance=Decimal("0.00000001"),
        minimum_regime_windows=minimum_regime_windows,
    )


def fold(index: int) -> tuple[WalkForwardFold, datetime, datetime]:
    """Return one typed fold and its selection/evaluation cutoffs."""

    if index == 1:
        value = WalkForwardFold(
            "fold-1",
            SampleWindow(date(2026, 1, 1), date(2026, 1, 31)),
            SampleWindow(date(2026, 2, 2), date(2026, 2, 10)),
            SampleWindow(date(2026, 2, 12), date(2026, 2, 13)),
        )
        return value, datetime(2026, 2, 11, 12, tzinfo=UTC), datetime(2026, 2, 14, 12, tzinfo=UTC)
    value = WalkForwardFold(
        "fold-2",
        SampleWindow(date(2026, 2, 1), date(2026, 2, 28)),
        SampleWindow(date(2026, 3, 2), date(2026, 3, 10)),
        SampleWindow(date(2026, 3, 12), date(2026, 3, 13)),
    )
    return value, datetime(2026, 3, 11, 12, tzinfo=UTC), datetime(2026, 3, 14, 12, tzinfo=UTC)


def temporal_split() -> TemporalSplitSpec:
    """Return the exact two-fold walk-forward and embargo plan."""

    first, _, _ = fold(1)
    second, _, _ = fold(2)
    return TemporalSplitSpec(
        policy_version="r4-walk-forward.v1",
        training=first.training,
        validation=first.validation,
        out_of_sample=SampleWindow(first.out_of_sample.start, second.out_of_sample.end),
        walk_forward_folds=(first, second),
        embargo_days=1,
    )


def _exposure(selection: datetime, index: int) -> MacroExposureVersion:
    beta = Decimal("1") + Decimal(index - 1) / Decimal("10")
    return MacroExposureVersion(
        version_id=f"exposure-{index}",
        promoted_factor_version="macro-factor-v7",
        promotion_decision_id="r3-promotion-7",
        pit_manifest_id=f"factor-manifest-{index}",
        code_version="git:abc123",
        parameter_version="exposure-policy-v3",
        observed_at=selection - timedelta(days=1),
        valid_until=selection + timedelta(days=10),
        exposures=(
            AssetMacroExposure(
                "asset-a",
                (
                    MacroFactorBeta("growth", beta, Decimal("0.8"), Decimal("1.3")),
                    MacroFactorBeta("inflation", Decimal("0"), Decimal("-0.1"), Decimal("0.1")),
                ),
                Decimal("0.01"),
                Decimal("0.7"),
                Decimal("0.8"),
            ),
            AssetMacroExposure(
                "asset-b",
                (
                    MacroFactorBeta("growth", Decimal("0"), Decimal("-0.1"), Decimal("0.1")),
                    MacroFactorBeta("inflation", beta, Decimal("0.8"), Decimal("1.3")),
                ),
                Decimal("0.01"),
                Decimal("0.7"),
                Decimal("0.8"),
            ),
        ),
    )


def _factor_covariance(selection: datetime, index: int) -> FactorCovarianceVersion:
    return FactorCovarianceVersion(
        version_id=f"factor-covariance-{index}",
        factor_codes=("growth", "inflation"),
        values=((Decimal("0.04"), Decimal("0")), (Decimal("0"), Decimal("0.04"))),
        pit_manifest_id=f"factor-manifest-{index}",
        estimator_version="factor-covariance.v2",
        observed_at=selection - timedelta(days=1),
        valid_until=selection + timedelta(days=10),
    )


def _weights(kind: MacroRiskCandidateKind) -> tuple[Decimal, Decimal]:
    if kind is MacroRiskCandidateKind.ASSET_RISK_PARITY:
        return Decimal("0.25"), Decimal("0.75")
    return Decimal("0.5"), Decimal("0.5")


def build_candidate(
    *,
    kind: MacroRiskCandidateKind,
    selection: datetime,
    index: int,
    cost_model_version: str = "cost-model.v2",
) -> MacroRiskCandidateInput:
    """Build one exact method candidate."""

    exposure = _exposure(selection, index)
    covariance = _factor_covariance(selection, index)
    first_weight, second_weight = _weights(kind)
    allocations = (
        AssetAllocation(
            "asset-a",
            Decimal("0.5"),
            first_weight,
            Decimal("0"),
            Decimal("1"),
            Decimal("1"),
        ),
        AssetAllocation(
            "asset-b",
            Decimal("0.5"),
            second_weight,
            Decimal("0"),
            Decimal("1"),
            Decimal("1"),
        ),
    )
    expected_cost = (
        Decimal("0.002") if kind is MacroRiskCandidateKind.ASSET_RISK_PARITY else Decimal("0.001")
    )
    candidate_id = f"candidate-{index}-{kind.value}"
    digest = build_macro_risk_input_hash(
        candidate_id=candidate_id,
        kind=kind,
        canonical_portfolio_snapshot_id=f"snapshot-{index}",
        exposure_version=exposure,
        covariance_version=covariance,
        cost_model_version=cost_model_version,
        constraint_version=f"constraints-{index}",
        allocations=allocations,
        expected_cost=expected_cost,
        created_at=selection,
    )
    return MacroRiskCandidateInput(
        candidate_id,
        kind,
        f"snapshot-{index}",
        exposure,
        covariance,
        cost_model_version,
        f"constraints-{index}",
        allocations,
        expected_cost,
        selection,
        digest,
    )


def rebuild_candidate(
    candidate: MacroRiskCandidateInput,
    *,
    allocations: tuple[AssetAllocation, ...] | None = None,
    cost_model_version: str | None = None,
    created_at: datetime | None = None,
) -> MacroRiskCandidateInput:
    """Replace selected fields and recompute the candidate hash."""

    updated = replace(
        candidate,
        allocations=allocations or candidate.allocations,
        cost_model_version=cost_model_version or candidate.cost_model_version,
        created_at=created_at or candidate.created_at,
    )
    digest = build_macro_risk_input_hash(
        candidate_id=updated.candidate_id,
        kind=updated.kind,
        canonical_portfolio_snapshot_id=updated.canonical_portfolio_snapshot_id,
        exposure_version=updated.exposure_version,
        covariance_version=updated.covariance_version,
        cost_model_version=updated.cost_model_version,
        constraint_version=updated.constraint_version,
        allocations=updated.allocations,
        expected_cost=updated.expected_cost,
        created_at=updated.created_at,
    )
    return replace(updated, input_hash=digest)


def build_window(
    index: int,
    *,
    candidates: tuple[MacroRiskCandidateInput, ...] | None = None,
    regime_code: str = "custom-expansion-state",
    covariance_values: tuple[tuple[Decimal, ...], ...] | None = None,
    regime_available_at: datetime | None = None,
) -> R4RollingWindowInput:
    """Build one exact rolling window."""

    current_fold, selection, evaluation = fold(index)
    selected_candidates = candidates or tuple(
        build_candidate(kind=kind, selection=selection, index=index)
        for kind in (
            MacroRiskCandidateKind.EQUAL_WEIGHT,
            MacroRiskCandidateKind.ASSET_RISK_PARITY,
            MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,
        )
    )
    projection = R4MacroExposureProjectionEvidence.create(
        exposure_version=selected_candidates[0].exposure_version,
        factor_artifact_id="r3-factor-main",
        factor_artifact_version="macro-factor-v7",
        factor_artifact_content_hash=FACTOR_ARTIFACT_HASH,
        promotion_decision_id="r3-promotion-7",
        promotion_decision_version="decision.v1",
        promotion_decision_content_hash=PROMOTION_DECISION_HASH,
        available_at=selection - timedelta(hours=1),
        knowledge_as_of=selection,
    )
    covariance = R4AssetCovarianceEvidence.create(
        covariance_id=f"asset-covariance-{index}",
        covariance_version="covariance.v1",
        universe_id=f"pit-universe-{index}",
        universe_hash=UNIVERSE_HASH,
        asset_codes=("asset-a", "asset-b"),
        values=covariance_values
        or ((Decimal("0.09"), Decimal("0")), (Decimal("0"), Decimal("0.01"))),
        estimator_version="asset-covariance.v2",
        estimation_window=SampleWindow(current_fold.training.start, current_fold.validation.end),
        observed_at=selection - timedelta(days=1),
        available_at=selection - timedelta(hours=6),
        knowledge_as_of=selection,
        valid_until=selection + timedelta(days=10),
        pit_manifest_id=f"portfolio-formation-manifest-{index}",
        pit_manifest_hash=PIT_MANIFEST_HASH,
        source_content_hashes=(SOURCE_HASH,),
    )
    first_returns = (
        (Decimal("0.01"), Decimal("0.02")) if index == 1 else (Decimal("0.03"), Decimal("-0.01"))
    )
    second_returns = (
        (Decimal("-0.01"), Decimal("0")) if index == 1 else (Decimal("0"), Decimal("0.02"))
    )
    observations = (
        R4ReturnObservation(
            datetime.combine(current_fold.out_of_sample.start, datetime.min.time(), UTC),
            (
                R4AssetReturn("asset-a", first_returns[0]),
                R4AssetReturn("asset-b", first_returns[1]),
            ),
        ),
        R4ReturnObservation(
            datetime.combine(current_fold.out_of_sample.end, datetime.min.time(), UTC),
            (
                R4AssetReturn("asset-a", second_returns[0]),
                R4AssetReturn("asset-b", second_returns[1]),
            ),
        ),
    )
    path = R4OOSReturnPathEvidence.create(
        path_id=f"oos-path-{index}",
        path_version="path.v1",
        universe_id=f"pit-universe-{index}",
        universe_hash=UNIVERSE_HASH,
        out_of_sample=current_fold.out_of_sample,
        observations=observations,
        observed_at=evaluation - timedelta(hours=2),
        available_at=evaluation - timedelta(hours=1),
        knowledge_as_of=evaluation,
        valid_until=evaluation + timedelta(days=10),
        pit_manifest_id=f"portfolio-oos-manifest-{index}",
        pit_manifest_hash=PIT_MANIFEST_HASH,
        source_content_hashes=(SOURCE_HASH,),
    )
    regime_available = regime_available_at or selection - timedelta(hours=1)
    regime = R4RegimeAssignmentEvidence.create(
        assignment_id=f"regime-assignment-{index}",
        assignment_version="assignment.v1",
        taxonomy_version="custom-taxonomy.v3",
        regime_code=regime_code,
        effective_at=selection - timedelta(days=1),
        available_at=regime_available,
        knowledge_as_of=max(regime_available, selection),
        valid_until=max(regime_available, selection) + timedelta(days=10),
        pit_manifest_id=f"regime-manifest-{index}",
        pit_manifest_hash=PIT_MANIFEST_HASH,
        source_content_hash=SOURCE_HASH,
    )
    return R4RollingWindowInput.create(
        fold=current_fold,
        selection_as_of=selection,
        evaluation_as_of=evaluation,
        macro_projection=projection,
        candidates=selected_candidates,
        asset_covariance=covariance,
        return_path=path,
        regime_assignment=regime,
    )


def rebuild_window(
    window: R4RollingWindowInput,
    *,
    candidates: tuple[MacroRiskCandidateInput, ...] | None = None,
    asset_covariance: R4AssetCovarianceEvidence | None = None,
    regime_assignment: R4RegimeAssignmentEvidence | None = None,
) -> R4RollingWindowInput:
    """Replace selected window fields and recompute its hash."""

    selected_candidates = candidates or window.candidates
    projection = window.macro_projection
    if selected_candidates[0].exposure_version != projection.exposure_version:
        projection = R4MacroExposureProjectionEvidence.create(
            exposure_version=selected_candidates[0].exposure_version,
            factor_artifact_id=projection.factor_artifact_id,
            factor_artifact_version=projection.factor_artifact_version,
            factor_artifact_content_hash=projection.factor_artifact_content_hash,
            promotion_decision_id=projection.promotion_decision_id,
            promotion_decision_version=projection.promotion_decision_version,
            promotion_decision_content_hash=projection.promotion_decision_content_hash,
            available_at=projection.available_at,
            knowledge_as_of=projection.knowledge_as_of,
        )
    return R4RollingWindowInput.create(
        fold=window.fold,
        selection_as_of=window.selection_as_of,
        evaluation_as_of=window.evaluation_as_of,
        macro_projection=projection,
        candidates=selected_candidates,
        asset_covariance=asset_covariance or window.asset_covariance,
        return_path=window.return_path,
        regime_assignment=regime_assignment or window.regime_assignment,
    )


def build_study(
    *,
    windows: tuple[R4RollingWindowInput, ...] | None = None,
    minimum_regime_windows: int = 2,
    study_id: str = "r4-rolling-study-1",
    study_version: str = "study.v1",
) -> R4RollingStudyInput:
    """Build a two-fold typed study."""

    return R4RollingStudyInput.create(
        study_id=study_id,
        study_version=study_version,
        temporal_split=temporal_split(),
        candidate_policy=candidate_policy(),
        rolling_policy=rolling_policy(minimum_regime_windows=minimum_regime_windows),
        windows=windows or (build_window(1), build_window(2)),
    )


def promotion_attestation(
    *,
    valid_until: datetime = datetime(2026, 4, 1, tzinfo=UTC),
    retired_at: datetime | None = None,
) -> ExactR3PromotionAttestation:
    """Build exact active Research approval for the factor fixture."""

    return ExactR3PromotionAttestation.create(
        artifact_id="r3-factor-main",
        artifact_version="macro-factor-v7",
        artifact_content_hash=FACTOR_ARTIFACT_HASH,
        decision_id="r3-promotion-7",
        decision_version="decision.v1",
        decision_content_hash=PROMOTION_DECISION_HASH,
        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
        valid_until=valid_until,
        retired_at=retired_at,
    )


__all__ = [
    "build_candidate",
    "build_study",
    "build_window",
    "candidate_policy",
    "fold",
    "promotion_attestation",
    "rebuild_candidate",
    "rebuild_window",
    "rolling_policy",
    "temporal_split",
]
