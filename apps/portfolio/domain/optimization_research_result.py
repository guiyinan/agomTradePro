"""Immutable governed R8 optimization research result evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from apps.portfolio.domain._optimization_canonical import (
    decimal_text,
    hash_components,
    require_aware,
    require_finite,
    require_sha256,
    require_text,
    require_token,
    require_unit_interval,
    utc_text,
)
from apps.portfolio.domain.constrained_optimization import (
    CandidateEvaluation,
    CandidateMetrics,
    OptimizationBlocker,
)
from apps.portfolio.domain.constrained_optimization_contracts import (
    CandidateKind,
    SolverConvergenceStatus,
)

EVIDENCE_WEIGHT_SUM_TOLERANCE = Decimal("0.000001")


class GovernedOptimizationResultStatus(str, Enum):
    """Research result state; neither state authorizes execution."""

    BLOCKED = "blocked"
    COMPLETED = "completed"


@dataclass(frozen=True)
class CandidateBlockerEvidence:
    """Stable blocker projected from a candidate evaluation."""

    code: str
    detail: str
    asset_code: str | None
    scenario_revision_id: str | None

    def __post_init__(self) -> None:
        require_token(self.code, "candidate blocker code")
        require_text(self.detail, "candidate blocker detail")
        if self.asset_code is not None:
            require_token(self.asset_code, "candidate blocker asset_code")
        if self.scenario_revision_id is not None:
            require_token(
                self.scenario_revision_id,
                "candidate blocker scenario_revision_id",
            )


@dataclass(frozen=True)
class CandidateMetricEvidence:
    """Every recomputed numerical metric used by the comparison."""

    expected_return: Decimal
    variance: Decimal
    transaction_cost: Decimal
    turnover: Decimal
    maximum_drawdown: Decimal
    scenario_losses: tuple[tuple[str, Decimal], ...]
    macro_factor_variance: Decimal
    macro_contribution_shares: tuple[tuple[str, Decimal], ...]
    macro_max_target_deviation: Decimal
    objective_value: Decimal

    @classmethod
    def from_metrics(cls, metrics: CandidateMetrics) -> CandidateMetricEvidence:
        """Copy a complete candidate metric set without dropping dimensions."""

        return cls(
            expected_return=metrics.expected_return,
            variance=metrics.variance,
            transaction_cost=metrics.transaction_cost,
            turnover=metrics.turnover,
            maximum_drawdown=metrics.drawdown_estimate,
            scenario_losses=metrics.scenario_losses,
            macro_factor_variance=metrics.macro_factor_variance,
            macro_contribution_shares=metrics.macro_contribution_shares,
            macro_max_target_deviation=metrics.macro_max_target_deviation,
            objective_value=metrics.objective_value,
        )

    def __post_init__(self) -> None:
        """Reject non-finite metrics and duplicate named dimensions."""

        for field_name, value in (
            ("expected_return", self.expected_return),
            ("variance", self.variance),
            ("transaction_cost", self.transaction_cost),
            ("turnover", self.turnover),
            ("maximum_drawdown", self.maximum_drawdown),
            ("macro_factor_variance", self.macro_factor_variance),
            ("macro_max_target_deviation", self.macro_max_target_deviation),
            ("objective_value", self.objective_value),
        ):
            require_finite(value, field_name)
        if self.variance < 0 or self.transaction_cost < 0 or self.turnover < 0:
            raise ValueError("candidate variance, cost, and turnover cannot be negative")
        require_unit_interval(self.maximum_drawdown, "maximum_drawdown")
        scenario_codes = tuple(item[0] for item in self.scenario_losses)
        if len(scenario_codes) != len(set(scenario_codes)):
            raise ValueError("candidate scenario losses must be unique")
        factor_codes = tuple(item[0] for item in self.macro_contribution_shares)
        if len(factor_codes) != len(set(factor_codes)):
            raise ValueError("candidate macro contribution shares must be unique")
        for code, value in (*self.scenario_losses, *self.macro_contribution_shares):
            require_token(code, "candidate metric code")
            require_finite(value, "candidate metric value")


@dataclass(frozen=True)
class GovernedCandidateEvidence:
    """Tamper-evident projection of one solver/baseline evaluation."""

    candidate_kind: CandidateKind
    eligible_for_comparison: bool
    weights: tuple[Decimal, ...]
    cash_weight: Decimal
    solver_status: SolverConvergenceStatus
    solver_iterations: int
    solver_residual: Decimal
    solver_detail: str
    metrics: CandidateMetricEvidence | None
    blockers: tuple[CandidateBlockerEvidence, ...]
    source_evaluation_hash: str
    content_hash: str

    @classmethod
    def from_evaluation(
        cls,
        evaluation: CandidateEvaluation,
    ) -> GovernedCandidateEvidence:
        """Seal all solver output, metrics and blocker fields."""

        blockers = tuple(_blocker_evidence(item) for item in evaluation.blockers)
        metrics = (
            None
            if evaluation.metrics is None
            else CandidateMetricEvidence.from_metrics(evaluation.metrics)
        )
        digest = governed_candidate_hash_values(
            candidate_kind=evaluation.candidate_kind,
            eligible_for_comparison=evaluation.eligible_for_comparison,
            weights=evaluation.weights,
            cash_weight=evaluation.cash_weight,
            solver_status=evaluation.solver_status,
            solver_iterations=evaluation.solver_iterations,
            solver_residual=evaluation.solver_residual,
            solver_detail=evaluation.solver_detail,
            metrics=metrics,
            blockers=blockers,
            source_evaluation_hash=evaluation.evidence_hash,
        )
        return cls(
            candidate_kind=evaluation.candidate_kind,
            eligible_for_comparison=evaluation.eligible_for_comparison,
            weights=evaluation.weights,
            cash_weight=evaluation.cash_weight,
            solver_status=evaluation.solver_status,
            solver_iterations=evaluation.solver_iterations,
            solver_residual=evaluation.solver_residual,
            solver_detail=evaluation.solver_detail,
            metrics=metrics,
            blockers=blockers,
            source_evaluation_hash=evaluation.evidence_hash,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Recompute full candidate evidence and its eligibility invariant."""

        if not isinstance(self.eligible_for_comparison, bool):
            raise ValueError("eligible_for_comparison must be a boolean")
        for weight in self.weights:
            require_unit_interval(weight, "candidate weight")
        require_unit_interval(self.cash_weight, "candidate cash_weight")
        if self.metrics is not None and not self.weights:
            raise ValueError("candidate metrics require a non-empty weight vector")
        if self.weights and (
            abs(sum(self.weights, start=Decimal("0")) + self.cash_weight - Decimal("1"))
            > EVIDENCE_WEIGHT_SUM_TOLERANCE
        ):
            raise ValueError("candidate asset and cash weights do not sum to one")
        if isinstance(self.solver_iterations, bool) or self.solver_iterations < 0:
            raise ValueError("solver_iterations cannot be negative")
        require_finite(self.solver_residual, "solver_residual")
        require_text(self.solver_detail, "solver_detail")
        require_sha256(self.source_evaluation_hash, "source_evaluation_hash")
        if self.eligible_for_comparison != (not self.blockers and self.metrics is not None):
            raise ValueError("candidate eligibility does not match blockers and metrics")
        require_sha256(self.content_hash, "candidate content_hash")
        if self.content_hash != governed_candidate_hash(self):
            raise ValueError("governed candidate content hash mismatch")


def _blocker_evidence(blocker: OptimizationBlocker) -> CandidateBlockerEvidence:
    return CandidateBlockerEvidence(
        code=blocker.code.value,
        detail=blocker.detail,
        asset_code=blocker.asset_code,
        scenario_revision_id=blocker.scenario_revision_id,
    )


def governed_candidate_hash(candidate: GovernedCandidateEvidence) -> str:
    """Recompute one candidate evidence digest."""

    return governed_candidate_hash_values(
        candidate_kind=candidate.candidate_kind,
        eligible_for_comparison=candidate.eligible_for_comparison,
        weights=candidate.weights,
        cash_weight=candidate.cash_weight,
        solver_status=candidate.solver_status,
        solver_iterations=candidate.solver_iterations,
        solver_residual=candidate.solver_residual,
        solver_detail=candidate.solver_detail,
        metrics=candidate.metrics,
        blockers=candidate.blockers,
        source_evaluation_hash=candidate.source_evaluation_hash,
    )


def governed_candidate_hash_values(
    *,
    candidate_kind: CandidateKind,
    eligible_for_comparison: bool,
    weights: tuple[Decimal, ...],
    cash_weight: Decimal,
    solver_status: SolverConvergenceStatus,
    solver_iterations: int,
    solver_residual: Decimal,
    solver_detail: str,
    metrics: CandidateMetricEvidence | None,
    blockers: tuple[CandidateBlockerEvidence, ...],
    source_evaluation_hash: str,
) -> str:
    """Hash all solver, metric and blocker fields."""

    metric_parts = (
        ()
        if metrics is None
        else (
            decimal_text(metrics.expected_return),
            decimal_text(metrics.variance),
            decimal_text(metrics.transaction_cost),
            decimal_text(metrics.turnover),
            decimal_text(metrics.maximum_drawdown),
            *(f"scenario:{code}|{decimal_text(value)}" for code, value in metrics.scenario_losses),
            decimal_text(metrics.macro_factor_variance),
            *(
                f"macro:{code}|{decimal_text(value)}"
                for code, value in metrics.macro_contribution_shares
            ),
            decimal_text(metrics.macro_max_target_deviation),
            decimal_text(metrics.objective_value),
        )
    )
    return hash_components(
        "governed-optimization-candidate.v1",
        candidate_kind.value,
        str(eligible_for_comparison),
        *(decimal_text(weight) for weight in weights),
        decimal_text(cash_weight),
        solver_status.value,
        str(solver_iterations),
        decimal_text(solver_residual),
        solver_detail,
        *metric_parts,
        *(
            f"{item.code}|{item.detail}|{item.asset_code or ''}|"
            f"{item.scenario_revision_id or ''}"
            for item in blockers
        ),
        source_evaluation_hash,
    )


@dataclass(frozen=True)
class GovernedOptimizationResearchResult:
    """Append-only comparison result bound to one trusted assembly."""

    result_id: str
    result_version: str
    run_key: str
    run_version: str
    assembly_hash: str
    problem_id: str
    problem_hash: str
    input_set_id: str
    input_set_hash: str
    status: GovernedOptimizationResultStatus
    candidates: tuple[GovernedCandidateEvidence, ...]
    selected_candidate: CandidateKind | None
    problem_blockers: tuple[tuple[str, str], ...]
    evaluated_at: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    @classmethod
    def create(
        cls,
        *,
        run_key: str,
        run_version: str,
        assembly_hash: str,
        problem_id: str,
        problem_hash: str,
        input_set_id: str,
        input_set_hash: str,
        candidate_evaluations: tuple[CandidateEvaluation, ...],
        problem_blockers: tuple[tuple[str, str], ...],
        evaluated_at: datetime,
        valid_until: datetime,
    ) -> GovernedOptimizationResearchResult:
        """Create a complete or blocked immutable research result."""

        candidates = tuple(
            sorted(
                (GovernedCandidateEvidence.from_evaluation(item) for item in candidate_evaluations),
                key=lambda item: tuple(CandidateKind).index(item.candidate_kind),
            )
        )
        status, selected = _derive_result_outcome(candidates, problem_blockers)
        digest = governed_result_hash_values(
            result_version="governed-optimization-result.v1",
            run_key=run_key,
            run_version=run_version,
            assembly_hash=assembly_hash,
            problem_id=problem_id,
            problem_hash=problem_hash,
            input_set_id=input_set_id,
            input_set_hash=input_set_hash,
            status=status,
            candidates=candidates,
            selected_candidate=selected,
            problem_blockers=problem_blockers,
            evaluated_at=evaluated_at,
            valid_until=valid_until,
        )
        return cls(
            result_id=f"governed_optimization_result:{digest[:24]}",
            result_version="governed-optimization-result.v1",
            run_key=run_key,
            run_version=run_version,
            assembly_hash=assembly_hash,
            problem_id=problem_id,
            problem_hash=problem_hash,
            input_set_id=input_set_id,
            input_set_hash=input_set_hash,
            status=status,
            candidates=candidates,
            selected_candidate=selected,
            problem_blockers=problem_blockers,
            evaluated_at=evaluated_at,
            valid_until=valid_until,
            content_hash=digest,
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )

    def __post_init__(self) -> None:
        """Recompute every result field and enforce comparison completeness."""

        for field_name, value in (
            ("result_id", self.result_id),
            ("result_version", self.result_version),
            ("run_key", self.run_key),
            ("run_version", self.run_version),
            ("problem_id", self.problem_id),
            ("input_set_id", self.input_set_id),
        ):
            require_token(value, field_name)
        for field_name, value in (
            ("assembly_hash", self.assembly_hash),
            ("problem_hash", self.problem_hash),
            ("input_set_hash", self.input_set_hash),
            ("content_hash", self.content_hash),
        ):
            require_sha256(value, field_name)
        require_aware(self.evaluated_at, "result evaluated_at")
        require_aware(self.valid_until, "result valid_until")
        if self.valid_until <= self.evaluated_at:
            raise ValueError("result valid_until must follow evaluated_at")
        kinds = tuple(item.candidate_kind.value for item in self.candidates)
        if len(kinds) != len(set(kinds)) or tuple(
            tuple(CandidateKind).index(item.candidate_kind) for item in self.candidates
        ) != tuple(
            sorted(tuple(CandidateKind).index(item.candidate_kind) for item in self.candidates)
        ):
            raise ValueError("result candidate kinds must be unique and canonically ordered")
        expected_status, expected_selected = _derive_result_outcome(
            self.candidates,
            self.problem_blockers,
        )
        if self.status is not expected_status:
            raise ValueError("result status does not match comparison completeness")
        if self.selected_candidate is not expected_selected:
            raise ValueError("result selected candidate does not match the objective argmin")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("governed optimization result must remain research-only")
        if self.content_hash != governed_result_hash(self):
            raise ValueError("governed optimization result content hash mismatch")
        if self.result_id != f"governed_optimization_result:{self.content_hash[:24]}":
            raise ValueError("governed optimization result id mismatch")


def _derive_result_outcome(
    candidates: tuple[GovernedCandidateEvidence, ...],
    problem_blockers: tuple[tuple[str, str], ...],
) -> tuple[GovernedOptimizationResultStatus, CandidateKind | None]:
    """Derive status and selection from the complete four-way comparison only."""

    candidate_by_kind = {item.candidate_kind: item for item in candidates}
    completed = (
        not problem_blockers
        and len(candidates) == len(CandidateKind)
        and set(candidate_by_kind) == set(CandidateKind)
        and all(item.eligible_for_comparison for item in candidates)
    )
    if not completed:
        return GovernedOptimizationResultStatus.BLOCKED, None
    selected = min(
        candidates,
        key=lambda item: (
            item.metrics.objective_value if item.metrics is not None else Decimal("Infinity"),
            tuple(CandidateKind).index(item.candidate_kind),
        ),
    )
    return GovernedOptimizationResultStatus.COMPLETED, selected.candidate_kind


def governed_result_hash(result: GovernedOptimizationResearchResult) -> str:
    """Recompute a complete result digest."""

    return governed_result_hash_values(
        result_version=result.result_version,
        run_key=result.run_key,
        run_version=result.run_version,
        assembly_hash=result.assembly_hash,
        problem_id=result.problem_id,
        problem_hash=result.problem_hash,
        input_set_id=result.input_set_id,
        input_set_hash=result.input_set_hash,
        status=result.status,
        candidates=result.candidates,
        selected_candidate=result.selected_candidate,
        problem_blockers=result.problem_blockers,
        evaluated_at=result.evaluated_at,
        valid_until=result.valid_until,
    )


def governed_result_hash_values(
    *,
    result_version: str,
    run_key: str,
    run_version: str,
    assembly_hash: str,
    problem_id: str,
    problem_hash: str,
    input_set_id: str,
    input_set_hash: str,
    status: GovernedOptimizationResultStatus,
    candidates: tuple[GovernedCandidateEvidence, ...],
    selected_candidate: CandidateKind | None,
    problem_blockers: tuple[tuple[str, str], ...],
    evaluated_at: datetime,
    valid_until: datetime,
) -> str:
    """Hash lineage, candidates, blockers, status and validity window."""

    return hash_components(
        result_version,
        run_key,
        run_version,
        assembly_hash,
        problem_id,
        problem_hash,
        input_set_id,
        input_set_hash,
        status.value,
        *(f"{item.candidate_kind.value}|{item.content_hash}" for item in candidates),
        selected_candidate.value if selected_candidate is not None else "",
        *(f"{code}|{detail}" for code, detail in problem_blockers),
        utc_text(evaluated_at),
        utc_text(valid_until),
        "research_only",
        "must_not_execute",
        "must_not_use_for_decision",
    )


__all__ = [
    "CandidateBlockerEvidence",
    "CandidateMetricEvidence",
    "GovernedCandidateEvidence",
    "GovernedOptimizationResearchResult",
    "GovernedOptimizationResultStatus",
    "governed_candidate_hash",
    "governed_result_hash",
]
