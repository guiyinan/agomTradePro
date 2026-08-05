"""Unit coverage for constrained R8 optimization contracts and local adapter."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.domain.canonical_snapshots import (
    CanonicalPosition,
    SnapshotEvidenceKind,
    SnapshotSourceEvidence,
    build_canonical_portfolio_snapshot,
)
from apps.portfolio.domain.constrained_optimization import (
    OptimizationBlockerCode,
    assess_optimization_problem,
    evaluate_solver_output,
)
from apps.portfolio.domain.constrained_optimization_contracts import (
    AssetCovarianceMatrix,
    AssetOptimizationInput,
    CandidateKind,
    ManualRestriction,
    OptimizationEvidenceBinding,
    OptimizationObjective,
    OptimizationValidationPolicy,
    ScenarioLossConstraint,
    SolverConvergenceStatus,
    build_asset_universe_hash,
    build_optimization_problem,
    build_solver_output,
)
from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateReport
from apps.portfolio.domain.optimizer_inputs import (
    OptimizationInputKind,
    PromotionReference,
)
from apps.portfolio.infrastructure.deterministic_optimizer import (
    DeterministicConstrainedSearchAdapter,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
EXECUTION_HASH = hashlib.sha256(b"execution-feedback-v1").hexdigest()
MACRO_HASH = hashlib.sha256(b"macro-risk-v1").hexdigest()


def _snapshot():
    observed_at = NOW - timedelta(days=2)
    return build_canonical_portfolio_snapshot(
        account_ref="account-r8",
        base_currency="CNY",
        cash_balance=Decimal("20"),
        cash_version="cash-v1",
        positions_version="positions-v1",
        positions=(
            CanonicalPosition(
                asset_code="asset-a",
                quantity=Decimal("40"),
                available_quantity=Decimal("40"),
                market_value_base=Decimal("40"),
                position_source_ref="position-a-v1",
                position_observed_at=observed_at,
                valuation_source_ref="valuation-a-v1",
                valuation_observed_at=observed_at,
            ),
            CanonicalPosition(
                asset_code="asset-b",
                quantity=Decimal("40"),
                available_quantity=Decimal("40"),
                market_value_base=Decimal("40"),
                position_source_ref="position-b-v1",
                position_observed_at=observed_at,
                valuation_source_ref="valuation-b-v1",
                valuation_observed_at=observed_at,
            ),
        ),
        source_evidence=(
            SnapshotSourceEvidence(
                SnapshotEvidenceKind.CASH,
                "portfolio",
                "cash-evidence-v1",
                "cash-v1",
                observed_at,
                "a" * 64,
            ),
            SnapshotSourceEvidence(
                SnapshotEvidenceKind.POSITIONS,
                "portfolio",
                "position-evidence-v1",
                "positions-v1",
                observed_at,
                "b" * 64,
            ),
        ),
    )


def _policy() -> OptimizationValidationPolicy:
    return OptimizationValidationPolicy(
        policy_version="optimizer-validation-v1",
        activated_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
        weight_tolerance=Decimal("0.000001"),
        covariance_symmetry_tolerance=Decimal("0.000001"),
        covariance_psd_tolerance=Decimal("0.000001"),
        solver_max_iterations=30,
        solver_initial_step=Decimal("0.05"),
        solver_minimum_step=Decimal("0.001"),
        risk_parity_max_iterations=50,
        risk_parity_tolerance=Decimal("0.01"),
    )


def _promotions() -> tuple[PromotionReference, ...]:
    return tuple(
        PromotionReference(
            capability_key=key,
            version=f"{key}-promoted-v1",
            decision_ref=f"promotion:{key}:v1",
            approved_at=NOW - timedelta(days=2),
            valid_until=NOW + timedelta(days=30),
        )
        for key in ("r3", "r4", "r5")
    )


def _macro_report() -> MacroRiskCandidateReport:
    return MacroRiskCandidateReport(
        candidate_id="macro-risk-current-v1",
        eligible_for_research_comparison=True,
        factor_variance=Decimal("0.02"),
        residual_variance=Decimal("0.01"),
        total_variance=Decimal("0.03"),
        turnover=Decimal("0"),
        contributions=(),
        blockers=(),
        evaluated_at=NOW - timedelta(hours=1),
        policy_version="macro-risk-policy-v1",
        evidence_hash=MACRO_HASH,
    )


def _asset_inputs(
    *,
    minimum_weight: Decimal = Decimal("0.1"),
    restriction: ManualRestriction = ManualRestriction.NONE,
) -> tuple[AssetOptimizationInput, ...]:
    return (
        AssetOptimizationInput(
            "asset-a",
            Decimal("0.08"),
            minimum_weight,
            Decimal("0.7"),
            Decimal("0.4"),
            Decimal("0.001"),
            Decimal("0.20"),
            restriction,
        ),
        AssetOptimizationInput(
            "asset-b",
            Decimal("0.04"),
            minimum_weight,
            Decimal("0.7"),
            Decimal("0.4"),
            Decimal("0.001"),
            Decimal("0.10"),
        ),
    )


def _problem(
    *,
    covariance_values: tuple[tuple[Decimal, ...], ...] | None = None,
    asset_inputs: tuple[AssetOptimizationInput, ...] | None = None,
):
    snapshot = _snapshot()
    codes = ("asset-a", "asset-b")
    universe_hash = build_asset_universe_hash(codes)
    covariance = AssetCovarianceMatrix.create(
        version="asset-covariance-v1",
        asset_codes=codes,
        values=covariance_values
        or (
            (Decimal("0.04"), Decimal("0.01")),
            (Decimal("0.01"), Decimal("0.09")),
        ),
        observed_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=10),
        universe_hash=universe_hash,
    )
    evidence_bindings = tuple(
        OptimizationEvidenceBinding(
            kind=kind,
            version=f"{kind.value}-v1",
            evidence_ref=f"evidence:{kind.value}:v1",
            content_hash=(
                covariance.content_hash
                if kind is OptimizationInputKind.ASSET_COVARIANCE
                else (
                    MACRO_HASH
                    if kind is OptimizationInputKind.MACRO_EXPOSURE
                    else (
                        EXECUTION_HASH
                        if kind is OptimizationInputKind.EXECUTION_FEEDBACK
                        else hashlib.sha256(kind.value.encode()).hexdigest()
                    )
                )
            ),
            universe_hash=universe_hash,
        )
        for kind in OptimizationInputKind
    )
    return build_optimization_problem(
        problem_id="optimization-problem-r8-v1",
        problem_version="constrained-multi-asset-v1",
        canonical_snapshot=snapshot,
        decision_snapshot_id="decision-snapshot-r8-v1",
        asset_inputs=asset_inputs or _asset_inputs(),
        covariance=covariance,
        scenario_losses=(
            ScenarioLossConstraint(
                scenario_revision_id="scenario-revision-tail-v1",
                scenario_version="tail-loss-v1",
                asset_codes=codes,
                loss_rates=(Decimal("0.20"), Decimal("0.10")),
                maximum_portfolio_loss=Decimal("0.18"),
                evidence_hash="c" * 64,
            ),
        ),
        minimum_cash_weight=Decimal("0.10"),
        target_cash_weight=Decimal("0.20"),
        maximum_turnover=Decimal("0.50"),
        maximum_transaction_cost=Decimal("0.01"),
        maximum_drawdown=Decimal("0.18"),
        execution_feedback_hash=EXECUTION_HASH,
        objective=OptimizationObjective(
            "mean-variance-cost-v1",
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
        ),
        validation_policy=_policy(),
        evidence_bindings=evidence_bindings,
        promotions=_promotions(),
        macro_risk_report=_macro_report(),
        created_at=NOW,
        valid_until=NOW + timedelta(days=10),
    )


def test_problem_and_deterministic_comparisons_are_reproducible_and_non_executable() -> None:
    problem = _problem()
    assessment = assess_optimization_problem(problem, evaluated_at=NOW)
    adapter = DeterministicConstrainedSearchAdapter()
    outputs = (
        adapter.equal_weight_baseline(problem),
        adapter.asset_risk_parity_baseline(problem),
        adapter.solve_candidate(problem),
    )
    evaluations = tuple(evaluate_solver_output(problem, output) for output in outputs)

    assert assessment.ready_for_solver is True
    assert assessment.must_not_execute is True
    assert all(output.declares_global_optimum is False for output in outputs)
    assert all(evaluation.research_only is True for evaluation in evaluations)
    assert all(evaluation.must_not_execute is True for evaluation in evaluations)
    assert evaluations[0].candidate_kind is CandidateKind.EQUAL_WEIGHT
    assert evaluations[1].candidate_kind is CandidateKind.ASSET_RISK_PARITY
    assert evaluations[2].candidate_kind is CandidateKind.DETERMINISTIC_SEARCH
    assert outputs[2].status in {
        SolverConvergenceStatus.LOCAL_STATIONARY,
        SolverConvergenceStatus.ITERATION_LIMIT,
    }


def test_non_psd_covariance_and_infeasible_bounds_block_before_solver() -> None:
    non_psd = _problem(
        covariance_values=(
            (Decimal("0.01"), Decimal("0.02")),
            (Decimal("0.02"), Decimal("0.01")),
        )
    )
    non_psd_assessment = assess_optimization_problem(non_psd, evaluated_at=NOW)
    assert OptimizationBlockerCode.COVARIANCE_NOT_PSD in {
        blocker.code for blocker in non_psd_assessment.blockers
    }

    infeasible = _problem(asset_inputs=_asset_inputs(minimum_weight=Decimal("0.5")))
    infeasible_assessment = assess_optimization_problem(infeasible, evaluated_at=NOW)
    assert OptimizationBlockerCode.BOUNDS_INFEASIBLE in {
        blocker.code for blocker in infeasible_assessment.blockers
    }


def test_candidate_constraint_breaches_are_recomputed_not_trusted() -> None:
    problem = _problem(asset_inputs=_asset_inputs(restriction=ManualRestriction.NO_BUY))
    output = build_solver_output(
        candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
        weights=(Decimal("0.85"), Decimal("-0.05")),
        cash_weight=Decimal("0.20"),
        status=SolverConvergenceStatus.LOCAL_STATIONARY,
        iterations=3,
        residual=Decimal("0.001"),
        detail="test local candidate",
    )
    evaluation = evaluate_solver_output(problem, output)
    codes = {blocker.code for blocker in evaluation.blockers}

    assert evaluation.eligible_for_comparison is False
    assert OptimizationBlockerCode.MANUAL_RESTRICTION_BREACHED in codes
    assert OptimizationBlockerCode.LIQUIDITY_BREACHED in codes
    assert evaluation.metrics is not None


def test_problem_hash_universe_and_execution_feedback_bindings_are_immutable() -> None:
    problem = _problem()
    with pytest.raises(ValueError, match="content_hash mismatch"):
        replace(problem, content_hash="0" * 64)
    with pytest.raises(ValueError, match="universe_hash mismatch"):
        replace(problem, universe_hash="0" * 64)
    bindings = tuple(
        (
            replace(binding, content_hash="f" * 64)
            if binding.kind is OptimizationInputKind.EXECUTION_FEEDBACK
            else binding
        )
        for binding in problem.evidence_bindings
    )
    with pytest.raises(ValueError, match="execution feedback evidence binding hash mismatch"):
        replace(problem, evidence_bindings=bindings)


def test_solver_output_cannot_claim_global_optimality() -> None:
    output = build_solver_output(
        candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
        weights=(Decimal("0.4"), Decimal("0.4")),
        cash_weight=Decimal("0.2"),
        status=SolverConvergenceStatus.LOCAL_STATIONARY,
        iterations=1,
        residual=Decimal("0.001"),
        detail="local only",
    )
    with pytest.raises(ValueError, match="global optimality"):
        replace(output, declares_global_optimum=True)
