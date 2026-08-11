"""Deterministic TDD contract for the R4 three-candidate optimizer."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.domain.macro_factor_risk import (
    FactorCovarianceVersion,
    MacroRiskCandidateKind,
)
from apps.portfolio.domain.macro_factor_risk_optimizer import (
    MacroRiskAssetConstraint,
    MacroRiskCandidateFamilySource,
    MacroRiskOptimizationBlockerCode,
    MacroRiskOptimizationStatus,
    MacroRiskSolverMethod,
    MacroRiskSolverPolicy,
    build_macro_risk_candidate_family,
)
from apps.portfolio.domain.r4_rolling_evidence import R4AssetCovarianceEvidence
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_window,
    candidate_policy,
)


def _source(*, transaction_cost_rate: Decimal = Decimal("0.002")) -> MacroRiskCandidateFamilySource:
    window = build_window(1)
    first = window.candidates[0]
    return MacroRiskCandidateFamilySource.create(
        source_id="r4-family-source-1",
        source_version="r4-family-source.v1",
        canonical_portfolio_snapshot_id=first.canonical_portfolio_snapshot_id,
        exposure_version=first.exposure_version,
        factor_covariance_version=first.covariance_version,
        asset_covariance=window.asset_covariance,
        cost_model_version="linear-turnover-cost.v1",
        constraint_version="constraints-1",
        constraints=tuple(
            MacroRiskAssetConstraint(
                asset_code=allocation.asset_code,
                current_weight=allocation.current_weight,
                minimum_weight=allocation.minimum_weight,
                maximum_weight=allocation.maximum_weight,
                maximum_trade_weight=allocation.maximum_trade_weight,
                transaction_cost_rate=transaction_cost_rate,
            )
            for allocation in first.allocations
        ),
        selection_as_of=window.selection_as_of,
        valid_until=window.selection_as_of + timedelta(days=5),
    )


def _policy(*, maximum_expected_cost: Decimal = Decimal("0.02")) -> MacroRiskSolverPolicy:
    validation = replace(candidate_policy(), maximum_expected_cost=maximum_expected_cost)
    return MacroRiskSolverPolicy.create(
        policy_id="r4-solver-policy",
        policy_version="r4-solver-policy.v1",
        method=MacroRiskSolverMethod.DETERMINISTIC_COORDINATE_TRANSFER,
        method_version="coordinate-transfer.v1",
        tolerance=Decimal("0.00000001"),
        max_iterations=200,
        validation_policy=validation,
        activated_at=datetime(2026, 2, 1, tzinfo=UTC),
        valid_until=datetime(2026, 3, 1, tzinfo=UTC),
    )


def test_builds_all_three_candidates_from_one_sealed_source() -> None:
    source = _source()
    result = build_macro_risk_candidate_family(
        source=source,
        policy=_policy(),
        evaluated_at=source.selection_as_of,
    )

    assert result.status is MacroRiskOptimizationStatus.READY
    assert result.blockers == ()
    assert tuple(solution.candidate.kind for solution in result.solutions) == tuple(
        MacroRiskCandidateKind
    )
    weights = {
        solution.candidate.kind: tuple(
            allocation.candidate_weight for allocation in solution.candidate.allocations
        )
        for solution in result.solutions
    }
    assert weights[MacroRiskCandidateKind.EQUAL_WEIGHT] == (Decimal("0.5"), Decimal("0.5"))
    assert weights[MacroRiskCandidateKind.ASSET_RISK_PARITY] == (
        Decimal("0.25"),
        Decimal("0.75"),
    )
    assert weights[MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY] == (
        Decimal("0.5"),
        Decimal("0.5"),
    )
    asset_rp = result.solutions[1]
    macro_rp = result.solutions[2]
    assert asset_rp.candidate.expected_cost == Decimal("0.001")
    target = Decimal("1") / Decimal(len(macro_rp.report.contributions))
    assert (
        max(
            abs(contribution.contribution_share - target)
            for contribution in macro_rp.report.contributions
        )
        <= _policy().tolerance
    )
    assert macro_rp.convergence_error <= _policy().tolerance
    assert all(solution.report.eligible_for_research_comparison for solution in result.solutions)
    assert all(solution.usage_scope == "research_only" for solution in result.solutions)
    assert result.usage_scope == "research_only"
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True


def test_source_contract_cannot_accept_prefilled_optimized_weights() -> None:
    source_fields = {field.name for field in fields(MacroRiskCandidateFamilySource)}
    constraint_fields = {field.name for field in fields(MacroRiskAssetConstraint)}

    assert "optimized_weights" not in source_fields
    assert "candidate_weight" not in source_fields
    assert "candidate_weight" not in constraint_fields


@pytest.mark.parametrize("payload_kind", ["exposure", "factor_covariance"])
def test_same_version_id_payload_substitution_fails_live_source_seal(
    payload_kind: str,
) -> None:
    source = _source()
    if payload_kind == "exposure":
        first_exposure = source.exposure_version.exposures[0]
        first_beta = replace(first_exposure.betas[0], beta=Decimal("0.9"))
        substituted_exposure = replace(
            first_exposure,
            betas=(first_beta, *first_exposure.betas[1:]),
        )
        substituted = replace(
            source.exposure_version,
            exposures=(substituted_exposure, *source.exposure_version.exposures[1:]),
        )
        object.__setattr__(source, "exposure_version", substituted)
    else:
        substituted_covariance = replace(
            source.factor_covariance_version,
            values=(
                (Decimal("0.05"), Decimal("0")),
                (Decimal("0"), Decimal("0.04")),
            ),
        )
        object.__setattr__(source, "factor_covariance_version", substituted_covariance)

    with pytest.raises(ValueError, match="source content_hash mismatch"):
        build_macro_risk_candidate_family(
            source=source,
            policy=_policy(),
            evaluated_at=source.selection_as_of,
        )


def test_instance_noop_validator_cannot_bypass_domain_live_seal() -> None:
    source = _source()
    object.__setattr__(source, "content_hash", "f" * 64)
    object.__setattr__(source, "__post_init__", lambda: None)

    with pytest.raises(ValueError, match="source content_hash mismatch"):
        build_macro_risk_candidate_family(
            source=source,
            policy=_policy(),
            evaluated_at=source.selection_as_of,
        )


def test_factor_covariance_not_psd_is_stably_blocked() -> None:
    source = _source()
    covariance = FactorCovarianceVersion(
        version_id=source.factor_covariance_version.version_id,
        factor_codes=source.factor_covariance_version.factor_codes,
        values=(
            (Decimal("0.04"), Decimal("0.05")),
            (Decimal("0.05"), Decimal("0.04")),
        ),
        pit_manifest_id=source.factor_covariance_version.pit_manifest_id,
        estimator_version=source.factor_covariance_version.estimator_version,
        observed_at=source.factor_covariance_version.observed_at,
        valid_until=source.factor_covariance_version.valid_until,
    )
    blocked_source = MacroRiskCandidateFamilySource.create(
        source_id=source.source_id,
        source_version=source.source_version,
        canonical_portfolio_snapshot_id=source.canonical_portfolio_snapshot_id,
        exposure_version=source.exposure_version,
        factor_covariance_version=covariance,
        asset_covariance=source.asset_covariance,
        cost_model_version=source.cost_model_version,
        constraint_version=source.constraint_version,
        constraints=source.constraints,
        selection_as_of=source.selection_as_of,
        valid_until=source.valid_until,
    )

    result = build_macro_risk_candidate_family(
        source=blocked_source,
        policy=_policy(),
        evaluated_at=source.selection_as_of,
    )

    assert result.status is MacroRiskOptimizationStatus.BLOCKED
    assert MacroRiskOptimizationBlockerCode.FACTOR_COVARIANCE_NOT_PSD in tuple(
        blocker.code for blocker in result.blockers
    )


@pytest.mark.parametrize("bad_iterations", [True, 2.5, Decimal("2")])
def test_solver_policy_requires_an_exact_builtin_integer(bad_iterations: object) -> None:
    with pytest.raises(ValueError, match="max_iterations must be an exact built-in integer"):
        MacroRiskSolverPolicy.create(
            policy_id="r4-solver-policy",
            policy_version="r4-solver-policy.v1",
            method=MacroRiskSolverMethod.DETERMINISTIC_COORDINATE_TRANSFER,
            method_version="coordinate-transfer.v1",
            tolerance=Decimal("0.00000001"),
            max_iterations=bad_iterations,  # type: ignore[arg-type]
            validation_policy=candidate_policy(),
            activated_at=datetime(2026, 2, 1, tzinfo=UTC),
            valid_until=datetime(2026, 3, 1, tzinfo=UTC),
        )


def test_rank_deficient_asset_covariance_is_stably_blocked() -> None:
    source = _source()
    original = source.asset_covariance
    covariance = R4AssetCovarianceEvidence.create(
        covariance_id=original.covariance_id,
        covariance_version=original.covariance_version,
        universe_id=original.universe_id,
        universe_hash=original.universe_hash,
        asset_codes=original.asset_codes,
        values=original.values,
        estimator_version=original.estimator_version,
        condition_number=original.condition_number,
        matrix_rank=1,
        expected_observation_count=original.expected_observation_count,
        missing_observation_count=original.missing_observation_count,
        missing_value_policy_version=original.missing_value_policy_version,
        estimation_window=original.estimation_window,
        observed_at=original.observed_at,
        available_at=original.available_at,
        knowledge_as_of=original.knowledge_as_of,
        valid_until=original.valid_until,
        pit_manifest_id=original.pit_manifest_id,
        pit_manifest_hash=original.pit_manifest_hash,
        source_content_hashes=original.source_content_hashes,
    )
    blocked_source = MacroRiskCandidateFamilySource.create(
        source_id=source.source_id,
        source_version=source.source_version,
        canonical_portfolio_snapshot_id=source.canonical_portfolio_snapshot_id,
        exposure_version=source.exposure_version,
        factor_covariance_version=source.factor_covariance_version,
        asset_covariance=covariance,
        cost_model_version=source.cost_model_version,
        constraint_version=source.constraint_version,
        constraints=source.constraints,
        selection_as_of=source.selection_as_of,
        valid_until=source.valid_until,
    )

    result = build_macro_risk_candidate_family(
        source=blocked_source,
        policy=_policy(),
        evaluated_at=source.selection_as_of,
    )

    assert result.status is MacroRiskOptimizationStatus.BLOCKED
    assert MacroRiskOptimizationBlockerCode.ASSET_COVARIANCE_RANK_DEFICIENT in tuple(
        blocker.code for blocker in result.blockers
    )


def test_infeasible_weight_bounds_are_stably_blocked() -> None:
    source = _source()
    constraints = tuple(replace(item, minimum_weight=Decimal("0.6")) for item in source.constraints)
    blocked_source = MacroRiskCandidateFamilySource.create(
        source_id=source.source_id,
        source_version=source.source_version,
        canonical_portfolio_snapshot_id=source.canonical_portfolio_snapshot_id,
        exposure_version=source.exposure_version,
        factor_covariance_version=source.factor_covariance_version,
        asset_covariance=source.asset_covariance,
        cost_model_version=source.cost_model_version,
        constraint_version=source.constraint_version,
        constraints=constraints,
        selection_as_of=source.selection_as_of,
        valid_until=source.valid_until,
    )

    result = build_macro_risk_candidate_family(
        source=blocked_source,
        policy=_policy(),
        evaluated_at=source.selection_as_of,
    )

    assert result.status is MacroRiskOptimizationStatus.BLOCKED
    assert tuple(blocker.code for blocker in result.blockers) == (
        MacroRiskOptimizationBlockerCode.WEIGHT_BOUNDS_CONFLICT,
    )
    assert result.solutions == ()


def test_cost_conflict_is_stably_blocked_after_server_side_costing() -> None:
    source = _source(transaction_cost_rate=Decimal("1"))
    result = build_macro_risk_candidate_family(
        source=source,
        policy=_policy(maximum_expected_cost=Decimal("0.01")),
        evaluated_at=source.selection_as_of,
    )

    assert result.status is MacroRiskOptimizationStatus.BLOCKED
    assert MacroRiskOptimizationBlockerCode.COST_CONFLICT in tuple(
        blocker.code for blocker in result.blockers
    )


def test_liquidity_limits_can_make_otherwise_feasible_bounds_infeasible() -> None:
    source = _source()
    constraints = tuple(
        replace(
            item,
            current_weight=Decimal("0.4"),
            maximum_trade_weight=Decimal("0.05"),
        )
        for item in source.constraints
    )
    blocked_source = MacroRiskCandidateFamilySource.create(
        source_id=source.source_id,
        source_version=source.source_version,
        canonical_portfolio_snapshot_id=source.canonical_portfolio_snapshot_id,
        exposure_version=source.exposure_version,
        factor_covariance_version=source.factor_covariance_version,
        asset_covariance=source.asset_covariance,
        cost_model_version=source.cost_model_version,
        constraint_version=source.constraint_version,
        constraints=constraints,
        selection_as_of=source.selection_as_of,
        valid_until=source.valid_until,
    )

    result = build_macro_risk_candidate_family(
        source=blocked_source,
        policy=_policy(),
        evaluated_at=source.selection_as_of,
    )

    assert sum((item.minimum_weight for item in constraints), Decimal("0")) <= Decimal("1")
    assert sum((item.maximum_weight for item in constraints), Decimal("0")) >= Decimal("1")
    assert MacroRiskOptimizationBlockerCode.LIQUIDITY_CONFLICT in tuple(
        blocker.code for blocker in result.blockers
    )


def test_server_computed_risk_parity_is_blocked_by_global_turnover_budget() -> None:
    source = _source()
    validation = replace(candidate_policy(), maximum_turnover=Decimal("0.1"))
    policy = MacroRiskSolverPolicy.create(
        policy_id="r4-turnover-policy",
        policy_version="r4-turnover-policy.v1",
        method=MacroRiskSolverMethod.DETERMINISTIC_COORDINATE_TRANSFER,
        method_version="coordinate-transfer.v1",
        tolerance=Decimal("0.00000001"),
        max_iterations=200,
        validation_policy=validation,
        activated_at=datetime(2026, 2, 1, tzinfo=UTC),
        valid_until=datetime(2026, 3, 1, tzinfo=UTC),
    )

    result = build_macro_risk_candidate_family(
        source=source,
        policy=policy,
        evaluated_at=source.selection_as_of,
    )

    assert result.status is MacroRiskOptimizationStatus.BLOCKED
    assert MacroRiskOptimizationBlockerCode.TURNOVER_CONFLICT in tuple(
        blocker.code for blocker in result.blockers
    )


def test_source_and_policy_use_exclusive_valid_until() -> None:
    source = _source()
    policy = _policy()
    boundary_policy = MacroRiskSolverPolicy.create(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        method=policy.method,
        method_version=policy.method_version,
        tolerance=policy.tolerance,
        max_iterations=policy.max_iterations,
        validation_policy=policy.validation_policy,
        activated_at=policy.activated_at,
        valid_until=source.selection_as_of,
    )

    source_boundary = build_macro_risk_candidate_family(
        source=source,
        policy=policy,
        evaluated_at=source.valid_until,
    )
    policy_boundary = build_macro_risk_candidate_family(
        source=source,
        policy=boundary_policy,
        evaluated_at=source.selection_as_of,
    )

    assert source_boundary.status is MacroRiskOptimizationStatus.BLOCKED
    assert source_boundary.blockers[0].code is MacroRiskOptimizationBlockerCode.SOURCE_NOT_ACTIVE
    assert policy_boundary.status is MacroRiskOptimizationStatus.BLOCKED
    assert policy_boundary.blockers[0].code is MacroRiskOptimizationBlockerCode.POLICY_NOT_ACTIVE
