"""Pure validation and objective calculations for R8 optimization research."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from apps.portfolio.domain.constrained_optimization_contracts import (
    AssetOptimizationConstraint,
    CandidateKind,
    ManualRestriction,
    OptimizationProblem,
    SolverConvergenceStatus,
    SolverOutput,
)


class OptimizationBlockerCode(str, Enum):
    """Stable fail-closed reasons for problem and candidate research."""

    POLICY_INACTIVE = "policy_inactive"
    PROBLEM_EXPIRED = "problem_expired"
    COVARIANCE_EXPIRED = "covariance_expired"
    COVARIANCE_NOT_SYMMETRIC = "covariance_not_symmetric"
    COVARIANCE_NOT_PSD = "covariance_not_psd"
    BOUNDS_INFEASIBLE = "bounds_infeasible"
    SOLVER_NO_CANDIDATE = "solver_no_candidate"
    SOLVER_NOT_CONVERGED = "solver_not_converged"
    WEIGHT_COUNT_MISMATCH = "weight_count_mismatch"
    WEIGHT_SUM_INVALID = "weight_sum_invalid"
    CASH_REQUIREMENT_BREACHED = "cash_requirement_breached"
    POSITION_BOUND_BREACHED = "position_bound_breached"
    LIQUIDITY_BREACHED = "liquidity_breached"
    MANUAL_RESTRICTION_BREACHED = "manual_restriction_breached"
    TURNOVER_BREACHED = "turnover_breached"
    COST_BUDGET_BREACHED = "cost_budget_breached"
    SCENARIO_LOSS_BREACHED = "scenario_loss_breached"
    DRAWDOWN_BUDGET_BREACHED = "drawdown_budget_breached"


@dataclass(frozen=True)
class OptimizationBlocker:
    """One deterministic blocker with optional asset or scenario context."""

    code: OptimizationBlockerCode
    detail: str
    asset_code: str | None = None
    scenario_revision_id: str | None = None


@dataclass(frozen=True)
class OptimizationProblemAssessment:
    """Fail-closed numerical readiness for one immutable problem."""

    problem_id: str
    ready_for_solver: bool
    blockers: tuple[OptimizationBlocker, ...]
    evaluated_at: datetime
    evidence_hash: str
    research_only: bool = True
    must_not_execute: bool = True


@dataclass(frozen=True)
class CandidateMetrics:
    """Reproducible objective and constraint metrics for one weight vector."""

    expected_return: Decimal
    variance: Decimal
    transaction_cost: Decimal
    turnover: Decimal
    drawdown_estimate: Decimal
    scenario_losses: tuple[tuple[str, Decimal], ...]
    objective_value: Decimal


@dataclass(frozen=True)
class CandidateEvaluation:
    """Research-only assessment of one deterministic baseline or local candidate."""

    candidate_kind: CandidateKind
    eligible_for_comparison: bool
    weights: tuple[Decimal, ...]
    cash_weight: Decimal
    solver_status: SolverConvergenceStatus
    solver_iterations: int
    solver_residual: Decimal
    solver_detail: str
    metrics: CandidateMetrics | None
    blockers: tuple[OptimizationBlocker, ...]
    evidence_hash: str
    declares_global_optimum: bool = False
    research_only: bool = True
    must_not_execute: bool = True


def assess_optimization_problem(
    problem: OptimizationProblem,
    *,
    evaluated_at: datetime,
) -> OptimizationProblemAssessment:
    """Validate clocks, covariance, and deterministic feasibility before solving."""

    _require_aware(evaluated_at, "evaluated_at")
    policy = problem.validation_policy
    blockers: list[OptimizationBlocker] = []
    if not policy.activated_at <= evaluated_at < policy.valid_until:
        blockers.append(
            _block(
                OptimizationBlockerCode.POLICY_INACTIVE,
                "optimization validation policy is not active",
            )
        )
    if problem.valid_until <= evaluated_at:
        blockers.append(
            _block(
                OptimizationBlockerCode.PROBLEM_EXPIRED,
                "optimization problem evidence has expired",
            )
        )
    if problem.created_at > evaluated_at:
        raise ValueError("optimization problem cannot be evaluated before creation")
    if problem.covariance.observed_at > evaluated_at:
        raise ValueError("asset covariance cannot be observed in the future")
    if problem.covariance.valid_until <= evaluated_at:
        blockers.append(
            _block(
                OptimizationBlockerCode.COVARIANCE_EXPIRED,
                "asset covariance evidence has expired",
            )
        )
    if not _is_symmetric(
        problem.covariance.values,
        policy.covariance_symmetry_tolerance,
    ):
        blockers.append(
            _block(
                OptimizationBlockerCode.COVARIANCE_NOT_SYMMETRIC,
                "asset covariance matrix is not symmetric within policy tolerance",
            )
        )
    elif not _is_positive_semidefinite(
        problem.covariance.values,
        policy.covariance_psd_tolerance,
    ):
        blockers.append(
            _block(
                OptimizationBlockerCode.COVARIANCE_NOT_PSD,
                "asset covariance matrix is not positive semidefinite",
            )
        )
    effective_bounds = tuple(effective_weight_bounds(asset) for asset in problem.assets)
    lower_total = sum(
        (bounds[0] for bounds in effective_bounds),
        start=Decimal("0"),
    )
    upper_total = sum(
        (bounds[1] for bounds in effective_bounds),
        start=Decimal("0"),
    )
    if (
        any(lower > upper for lower, upper in effective_bounds)
        or lower_total > problem.invested_weight + policy.weight_tolerance
        or upper_total < problem.invested_weight - policy.weight_tolerance
    ):
        blockers.append(
            _block(
                OptimizationBlockerCode.BOUNDS_INFEASIBLE,
                "effective bounds cannot satisfy the fixed invested weight",
            )
        )
    evidence_hash = _hash_components(
        "optimization-problem-assessment.v1",
        problem.content_hash,
        evaluated_at.isoformat(),
        *(f"{item.code.value}:{item.detail}" for item in blockers),
    )
    return OptimizationProblemAssessment(
        problem_id=problem.problem_id,
        ready_for_solver=not blockers,
        blockers=tuple(blockers),
        evaluated_at=evaluated_at,
        evidence_hash=evidence_hash,
    )


def evaluate_solver_output(
    problem: OptimizationProblem,
    output: SolverOutput,
) -> CandidateEvaluation:
    """Recompute objective and every constraint from one deterministic output."""

    blockers: list[OptimizationBlocker] = []
    if output.weights is None or output.cash_weight is None:
        blockers.append(
            _block(
                OptimizationBlockerCode.SOLVER_NO_CANDIDATE,
                "solver did not produce a candidate weight vector",
            )
        )
        return _candidate_report(problem=problem, output=output, blockers=blockers, metrics=None)
    if output.status not in {
        SolverConvergenceStatus.BASELINE,
        SolverConvergenceStatus.LOCAL_STATIONARY,
    }:
        blockers.append(
            _block(
                OptimizationBlockerCode.SOLVER_NOT_CONVERGED,
                "solver status is not eligible for research comparison",
            )
        )
    weights = output.weights
    if len(weights) != len(problem.assets):
        blockers.append(
            _block(
                OptimizationBlockerCode.WEIGHT_COUNT_MISMATCH,
                "candidate weights do not align with the asset universe",
            )
        )
        return _candidate_report(problem=problem, output=output, blockers=blockers, metrics=None)
    for weight in weights:
        _require_finite(weight, "candidate weight")
    _require_finite(output.cash_weight, "candidate cash_weight")
    tolerance = problem.validation_policy.weight_tolerance
    if abs(sum(weights, start=Decimal("0")) + output.cash_weight - Decimal("1")) > tolerance:
        blockers.append(
            _block(
                OptimizationBlockerCode.WEIGHT_SUM_INVALID,
                "asset and cash weights do not sum to one",
            )
        )
    if (
        output.cash_weight < problem.minimum_cash_weight - tolerance
        or abs(output.cash_weight - problem.target_cash_weight) > tolerance
    ):
        blockers.append(
            _block(
                OptimizationBlockerCode.CASH_REQUIREMENT_BREACHED,
                "candidate cash weight breaches the governed target or minimum",
            )
        )
    for asset, weight in zip(problem.assets, weights, strict=True):
        lower, upper = effective_weight_bounds(asset)
        if weight < lower - tolerance or weight > upper + tolerance:
            code = (
                OptimizationBlockerCode.MANUAL_RESTRICTION_BREACHED
                if asset.manual_restriction is not ManualRestriction.NONE
                else OptimizationBlockerCode.POSITION_BOUND_BREACHED
            )
            blockers.append(
                OptimizationBlocker(
                    code=code,
                    detail="candidate weight breaches its effective asset bounds",
                    asset_code=asset.asset_code,
                )
            )
        if abs(weight - asset.current_weight) > asset.maximum_trade_weight + tolerance:
            blockers.append(
                OptimizationBlocker(
                    code=OptimizationBlockerCode.LIQUIDITY_BREACHED,
                    detail="candidate trade exceeds versioned liquidity capacity",
                    asset_code=asset.asset_code,
                )
            )
    metrics = calculate_candidate_metrics(
        problem,
        weights=weights,
        cash_weight=output.cash_weight,
    )
    if metrics.turnover > problem.maximum_turnover + tolerance:
        blockers.append(
            _block(
                OptimizationBlockerCode.TURNOVER_BREACHED,
                "candidate turnover exceeds the versioned budget",
            )
        )
    if metrics.transaction_cost > problem.maximum_transaction_cost + tolerance:
        blockers.append(
            _block(
                OptimizationBlockerCode.COST_BUDGET_BREACHED,
                "candidate transaction cost exceeds the versioned budget",
            )
        )
    for scenario_id, loss in metrics.scenario_losses:
        limit = next(
            item.maximum_portfolio_loss
            for item in problem.scenario_losses
            if item.scenario_revision_id == scenario_id
        )
        if loss > limit + tolerance:
            blockers.append(
                OptimizationBlocker(
                    code=OptimizationBlockerCode.SCENARIO_LOSS_BREACHED,
                    detail="candidate exceeds a governed scenario loss limit",
                    scenario_revision_id=scenario_id,
                )
            )
    if metrics.drawdown_estimate > problem.maximum_drawdown + tolerance:
        blockers.append(
            _block(
                OptimizationBlockerCode.DRAWDOWN_BUDGET_BREACHED,
                "candidate drawdown estimate exceeds the versioned budget",
            )
        )
    return _candidate_report(problem=problem, output=output, blockers=blockers, metrics=metrics)


def calculate_candidate_metrics(
    problem: OptimizationProblem,
    *,
    weights: tuple[Decimal, ...],
    cash_weight: Decimal,
) -> CandidateMetrics:
    """Recompute objective inputs without trusting solver-provided metrics."""

    if len(weights) != len(problem.assets):
        raise ValueError("candidate weights do not align with problem assets")
    expected_return = sum(
        (
            weight * asset.expected_return
            for weight, asset in zip(weights, problem.assets, strict=True)
        ),
        start=Decimal("0"),
    )
    covariance_times_weights = _matrix_vector(problem.covariance.values, weights)
    variance = sum(
        (
            weight * marginal
            for weight, marginal in zip(weights, covariance_times_weights, strict=True)
        ),
        start=Decimal("0"),
    )
    transaction_cost = sum(
        (
            abs(weight - asset.current_weight) * asset.transaction_cost_rate
            for weight, asset in zip(weights, problem.assets, strict=True)
        ),
        start=Decimal("0"),
    )
    current_cash = _current_cash_weight(problem)
    turnover = (
        sum(
            (
                abs(weight - asset.current_weight)
                for weight, asset in zip(weights, problem.assets, strict=True)
            ),
            start=Decimal("0"),
        )
        + abs(cash_weight - current_cash)
    ) / Decimal("2")
    drawdown = sum(
        (
            weight * asset.drawdown_loss
            for weight, asset in zip(weights, problem.assets, strict=True)
        ),
        start=Decimal("0"),
    )
    scenario_losses = tuple(
        (
            scenario.scenario_revision_id,
            sum(
                (weight * loss for weight, loss in zip(weights, scenario.loss_rates, strict=True)),
                start=Decimal("0"),
            ),
        )
        for scenario in problem.scenario_losses
    )
    objective = problem.objective
    objective_value = (
        objective.variance_penalty * variance
        + objective.transaction_cost_penalty * transaction_cost
        - objective.expected_return_weight * expected_return
    )
    return CandidateMetrics(
        expected_return=expected_return,
        variance=variance,
        transaction_cost=transaction_cost,
        turnover=turnover,
        drawdown_estimate=drawdown,
        scenario_losses=scenario_losses,
        objective_value=objective_value,
    )


def effective_weight_bounds(
    asset: AssetOptimizationConstraint,
) -> tuple[Decimal, Decimal]:
    """Return asset bounds after liquidity and manual restrictions are applied."""

    current_weight = asset.current_weight
    minimum_weight = asset.minimum_weight
    maximum_weight = asset.maximum_weight
    maximum_trade_weight = asset.maximum_trade_weight
    restriction = asset.manual_restriction
    lower = max(minimum_weight, current_weight - maximum_trade_weight)
    upper = min(maximum_weight, current_weight + maximum_trade_weight)
    if restriction is ManualRestriction.FIXED:
        return current_weight, current_weight
    if restriction is ManualRestriction.NO_BUY:
        upper = min(upper, current_weight)
    elif restriction is ManualRestriction.NO_SELL:
        lower = max(lower, current_weight)
    return lower, upper


def _candidate_report(
    *,
    problem: OptimizationProblem,
    output: SolverOutput,
    blockers: list[OptimizationBlocker],
    metrics: CandidateMetrics | None,
) -> CandidateEvaluation:
    weights = output.weights or ()
    cash_weight = output.cash_weight if output.cash_weight is not None else Decimal("0")
    evidence_hash = _hash_components(
        "optimization-candidate-evaluation.v1",
        problem.content_hash,
        output.content_hash,
        *(str(weight) for weight in weights),
        str(cash_weight),
        str(metrics.objective_value if metrics is not None else ""),
        *(
            f"{item.code.value}:{item.asset_code or ''}:{item.scenario_revision_id or ''}"
            for item in blockers
        ),
    )
    return CandidateEvaluation(
        candidate_kind=output.candidate_kind,
        eligible_for_comparison=not blockers,
        weights=weights,
        cash_weight=cash_weight,
        solver_status=output.status,
        solver_iterations=output.iterations,
        solver_residual=output.residual,
        solver_detail=output.detail,
        metrics=metrics,
        blockers=tuple(blockers),
        evidence_hash=evidence_hash,
    )


def _current_cash_weight(problem: OptimizationProblem) -> Decimal:
    total_value = problem.canonical_snapshot.cash_balance + sum(
        (position.market_value_base for position in problem.canonical_snapshot.positions),
        start=Decimal("0"),
    )
    return problem.canonical_snapshot.cash_balance / total_value


def _is_symmetric(matrix: tuple[tuple[Decimal, ...], ...], tolerance: Decimal) -> bool:
    return all(
        abs(matrix[row][column] - matrix[column][row]) <= tolerance
        for row in range(len(matrix))
        for column in range(row + 1, len(matrix))
    )


def _is_positive_semidefinite(
    matrix: tuple[tuple[Decimal, ...], ...],
    tolerance: Decimal,
) -> bool:
    size = len(matrix)
    lower = [[Decimal("0") for _ in range(size)] for _ in range(size)]
    diagonal = [Decimal("0") for _ in range(size)]
    for row in range(size):
        diagonal[row] = matrix[row][row] - sum(
            (lower[row][index] * lower[row][index] * diagonal[index] for index in range(row)),
            start=Decimal("0"),
        )
        if diagonal[row] < -tolerance:
            return False
        if abs(diagonal[row]) <= tolerance:
            diagonal[row] = Decimal("0")
        for below in range(row + 1, size):
            numerator = matrix[below][row] - sum(
                (lower[below][index] * lower[row][index] * diagonal[index] for index in range(row)),
                start=Decimal("0"),
            )
            if diagonal[row] == 0:
                if abs(numerator) > tolerance:
                    return False
                lower[below][row] = Decimal("0")
            else:
                lower[below][row] = numerator / diagonal[row]
    return True


def _matrix_vector(
    matrix: tuple[tuple[Decimal, ...], ...],
    vector: tuple[Decimal, ...],
) -> tuple[Decimal, ...]:
    return tuple(
        sum(
            (value * vector[index] for index, value in enumerate(row)),
            start=Decimal("0"),
        )
        for row in matrix
    )


def _block(code: OptimizationBlockerCode, detail: str) -> OptimizationBlocker:
    return OptimizationBlocker(code=code, detail=detail)


def _hash_components(*components: str) -> str:
    digest = hashlib.sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
