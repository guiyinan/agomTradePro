"""Deterministic local-search adapter for constrained optimization research."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.portfolio.domain.constrained_optimization import (
    CandidateEvaluation,
    effective_weight_bounds,
    evaluate_solver_output,
)
from apps.portfolio.domain.constrained_optimization_contracts import (
    CandidateKind,
    OptimizationProblem,
    SolverConvergenceStatus,
    SolverOutput,
    build_solver_output,
)


class DeterministicConstrainedSearchAdapter:
    """Build two baselines and a bounded local candidate without randomness."""

    def equal_weight_baseline(self, problem: OptimizationProblem) -> SolverOutput:
        """Return a bound-projected equal-weight baseline or explicit infeasibility."""

        count = len(problem.assets)
        raw = tuple(problem.invested_weight / Decimal(count) for _ in problem.assets)
        weights = _project_to_effective_bounds(problem, raw)
        if weights is None:
            return _failed(
                CandidateKind.EQUAL_WEIGHT,
                SolverConvergenceStatus.INFEASIBLE,
                "equal-weight baseline cannot satisfy effective bounds",
            )
        return build_solver_output(
            candidate_kind=CandidateKind.EQUAL_WEIGHT,
            weights=weights,
            cash_weight=problem.target_cash_weight,
            status=SolverConvergenceStatus.BASELINE,
            iterations=0,
            residual=Decimal("0"),
            detail="deterministic bound-projected equal-weight baseline",
        )

    def asset_risk_parity_baseline(self, problem: OptimizationProblem) -> SolverOutput:
        """Return a deterministic constrained risk-contribution approximation."""

        diagonal = tuple(
            problem.covariance.values[index][index] for index in range(len(problem.assets))
        )
        if any(value <= 0 for value in diagonal):
            return _failed(
                CandidateKind.ASSET_RISK_PARITY,
                SolverConvergenceStatus.NUMERICAL_FAILURE,
                "asset-risk-parity baseline requires positive asset variances",
            )
        try:
            inverse_volatility = tuple(Decimal("1") / value.sqrt() for value in diagonal)
        except (InvalidOperation, ZeroDivisionError):
            return _failed(
                CandidateKind.ASSET_RISK_PARITY,
                SolverConvergenceStatus.NUMERICAL_FAILURE,
                "asset-risk-parity volatility calculation failed",
            )
        total = sum(inverse_volatility, start=Decimal("0"))
        weights = _project_to_effective_bounds(
            problem,
            tuple(problem.invested_weight * value / total for value in inverse_volatility),
        )
        if weights is None:
            return _failed(
                CandidateKind.ASSET_RISK_PARITY,
                SolverConvergenceStatus.INFEASIBLE,
                "asset-risk-parity baseline cannot satisfy effective bounds",
            )
        tolerance = problem.validation_policy.risk_parity_tolerance
        residual = Decimal("Infinity")
        for iteration in range(1, problem.validation_policy.risk_parity_max_iterations + 1):
            marginal = _matrix_vector(problem.covariance.values, weights)
            total_variance = sum(
                (
                    weight * marginal_value
                    for weight, marginal_value in zip(weights, marginal, strict=True)
                ),
                start=Decimal("0"),
            )
            contributions = tuple(
                weight * marginal_value
                for weight, marginal_value in zip(weights, marginal, strict=True)
            )
            if total_variance <= 0 or any(value <= 0 for value in contributions):
                return _failed(
                    CandidateKind.ASSET_RISK_PARITY,
                    SolverConvergenceStatus.NUMERICAL_FAILURE,
                    "asset-risk-parity contribution calculation became non-positive",
                    iterations=iteration,
                )
            target = total_variance / Decimal(len(weights))
            residual = max(
                abs(value / total_variance - Decimal("1") / Decimal(len(weights)))
                for value in contributions
            )
            if residual <= tolerance:
                return build_solver_output(
                    candidate_kind=CandidateKind.ASSET_RISK_PARITY,
                    weights=weights,
                    cash_weight=problem.target_cash_weight,
                    status=SolverConvergenceStatus.BASELINE,
                    iterations=iteration,
                    residual=residual,
                    detail=(
                        "deterministic constrained asset-risk-parity approximation; "
                        "not a global optimum"
                    ),
                )
            try:
                adjusted = tuple(
                    weight * (target / contribution).sqrt()
                    for weight, contribution in zip(weights, contributions, strict=True)
                )
            except (InvalidOperation, ZeroDivisionError):
                return _failed(
                    CandidateKind.ASSET_RISK_PARITY,
                    SolverConvergenceStatus.NUMERICAL_FAILURE,
                    "asset-risk-parity update failed",
                    iterations=iteration,
                )
            adjusted_total = sum(adjusted, start=Decimal("0"))
            projected = _project_to_effective_bounds(
                problem,
                tuple(problem.invested_weight * value / adjusted_total for value in adjusted),
            )
            if projected is None:
                return _failed(
                    CandidateKind.ASSET_RISK_PARITY,
                    SolverConvergenceStatus.INFEASIBLE,
                    "asset-risk-parity update cannot satisfy effective bounds",
                    iterations=iteration,
                )
            weights = projected
        return build_solver_output(
            candidate_kind=CandidateKind.ASSET_RISK_PARITY,
            weights=weights,
            cash_weight=problem.target_cash_weight,
            status=SolverConvergenceStatus.ITERATION_LIMIT,
            iterations=problem.validation_policy.risk_parity_max_iterations,
            residual=residual,
            detail="asset-risk-parity approximation reached its iteration limit",
        )

    def solve_candidate(self, problem: OptimizationProblem) -> SolverOutput:
        """Run deterministic coordinate transfers and report only local convergence."""

        current = tuple(asset.current_weight for asset in problem.assets)
        weights = _project_to_effective_bounds(problem, current)
        if weights is None:
            return _failed(
                CandidateKind.DETERMINISTIC_SEARCH,
                SolverConvergenceStatus.INFEASIBLE,
                "canonical starting weights cannot satisfy effective bounds",
            )
        current_evaluation = _evaluate_local_vector(problem, weights)
        if not current_evaluation.eligible_for_comparison:
            equal = self.equal_weight_baseline(problem)
            if equal.weights is None:
                return _failed(
                    CandidateKind.DETERMINISTIC_SEARCH,
                    SolverConvergenceStatus.INFEASIBLE,
                    "no feasible deterministic starting candidate was found",
                )
            equal_evaluation = evaluate_solver_output(problem, equal)
            if not equal_evaluation.eligible_for_comparison:
                return _failed(
                    CandidateKind.DETERMINISTIC_SEARCH,
                    SolverConvergenceStatus.INFEASIBLE,
                    "no feasible deterministic starting candidate was found",
                )
            weights = equal.weights
            current_evaluation = equal_evaluation
        assert current_evaluation.metrics is not None
        best_objective = current_evaluation.metrics.objective_value
        step = problem.validation_policy.solver_initial_step
        tolerance = problem.validation_policy.weight_tolerance
        for iteration in range(1, problem.validation_policy.solver_max_iterations + 1):
            best_neighbor: tuple[Decimal, ...] | None = None
            best_neighbor_objective = best_objective
            for source in range(len(weights)):
                for target in range(len(weights)):
                    if source == target:
                        continue
                    neighbor = list(weights)
                    neighbor[source] -= step
                    neighbor[target] += step
                    candidate_weights = tuple(neighbor)
                    evaluation = _evaluate_local_vector(problem, candidate_weights)
                    if evaluation.eligible_for_comparison and evaluation.metrics is not None:
                        objective = evaluation.metrics.objective_value
                        if objective < best_neighbor_objective - tolerance or (
                            abs(objective - best_neighbor_objective) <= tolerance
                            and best_neighbor is not None
                            and candidate_weights < best_neighbor
                        ):
                            best_neighbor = candidate_weights
                            best_neighbor_objective = objective
            if best_neighbor is not None:
                weights = best_neighbor
                best_objective = best_neighbor_objective
                continue
            step /= Decimal("2")
            if step < problem.validation_policy.solver_minimum_step:
                return build_solver_output(
                    candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
                    weights=weights,
                    cash_weight=problem.target_cash_weight,
                    status=SolverConvergenceStatus.LOCAL_STATIONARY,
                    iterations=iteration,
                    residual=step,
                    detail=(
                        "deterministic coordinate search found no improving local move; "
                        "not a global optimum"
                    ),
                )
        return build_solver_output(
            candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
            weights=weights,
            cash_weight=problem.target_cash_weight,
            status=SolverConvergenceStatus.ITERATION_LIMIT,
            iterations=problem.validation_policy.solver_max_iterations,
            residual=step,
            detail="deterministic coordinate search reached its iteration limit",
        )


def _evaluate_local_vector(
    problem: OptimizationProblem,
    weights: tuple[Decimal, ...],
) -> CandidateEvaluation:
    output = build_solver_output(
        candidate_kind=CandidateKind.DETERMINISTIC_SEARCH,
        weights=weights,
        cash_weight=problem.target_cash_weight,
        status=SolverConvergenceStatus.LOCAL_STATIONARY,
        iterations=0,
        residual=Decimal("0"),
        detail="internal deterministic feasibility evaluation",
    )
    return evaluate_solver_output(problem, output)


def _project_to_effective_bounds(
    problem: OptimizationProblem,
    raw_weights: tuple[Decimal, ...],
) -> tuple[Decimal, ...] | None:
    if len(raw_weights) != len(problem.assets):
        return None
    bounds = tuple(effective_weight_bounds(asset) for asset in problem.assets)
    target = problem.invested_weight
    tolerance = problem.validation_policy.weight_tolerance
    if (
        sum((lower for lower, _ in bounds), start=Decimal("0")) > target + tolerance
        or sum((upper for _, upper in bounds), start=Decimal("0")) < target - tolerance
    ):
        return None
    weights = [
        min(max(weight, lower), upper)
        for weight, (lower, upper) in zip(raw_weights, bounds, strict=True)
    ]
    for _ in range(len(weights) * 4 + 4):
        gap = target - sum(weights, start=Decimal("0"))
        if abs(gap) <= tolerance:
            weights[-1] += gap
            return tuple(weights)
        if gap > 0:
            candidates = [
                index for index, (_, upper) in enumerate(bounds) if weights[index] < upper
            ]
            if not candidates:
                return None
            share = gap / Decimal(len(candidates))
            for index in candidates:
                weights[index] += min(share, bounds[index][1] - weights[index])
        else:
            candidates = [
                index for index, (lower, _) in enumerate(bounds) if weights[index] > lower
            ]
            if not candidates:
                return None
            share = -gap / Decimal(len(candidates))
            for index in candidates:
                weights[index] -= min(share, weights[index] - bounds[index][0])
    return None


def _failed(
    kind: CandidateKind,
    status: SolverConvergenceStatus,
    detail: str,
    *,
    iterations: int = 0,
) -> SolverOutput:
    return build_solver_output(
        candidate_kind=kind,
        weights=None,
        cash_weight=None,
        status=status,
        iterations=iterations,
        residual=Decimal("0"),
        detail=detail,
    )


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


__all__ = ["DeterministicConstrainedSearchAdapter"]
