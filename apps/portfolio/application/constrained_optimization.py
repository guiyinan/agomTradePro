"""Application gate for research-only constrained multi-asset optimization."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

from apps.portfolio.application.optimizer_inputs import EvaluateOptimizerInputsUseCase
from apps.portfolio.domain.constrained_optimization import (
    CandidateEvaluation,
    OptimizationProblemAssessment,
    assess_optimization_problem,
    evaluate_solver_output,
)
from apps.portfolio.domain.constrained_optimization_contracts import (
    CandidateKind,
    OptimizationProblem,
    SolverOutput,
)
from apps.portfolio.domain.optimizer_inputs import (
    OptimizationEvidenceState,
    OptimizerInputReadiness,
)


class OptimizationResearchStatus(str, Enum):
    """Outcome of one gated R8 research run."""

    BLOCKED = "blocked"
    COMPLETED = "completed"


@dataclass(frozen=True)
class OptimizationResearchBlocker:
    """Stable application blocker from readiness or numerical validation."""

    reason_code: str
    detail: str


class OptimizationProblemProvider(Protocol):
    """Provide one immutable problem assembled from canonical owner data."""

    def get_problem(self, problem_id: str) -> OptimizationProblem | None:
        """Return the exact problem or ``None`` without synthesizing inputs."""


class ConstrainedOptimizationEngineProtocol(Protocol):
    """Deterministic engine boundary with explicit benchmark construction."""

    def current_configuration_baseline(self, problem: OptimizationProblem) -> SolverOutput:
        """Return observed canonical weights without feasibility projection."""

    def equal_weight_baseline(self, problem: OptimizationProblem) -> SolverOutput:
        """Build the deterministic equal-weight baseline."""

    def asset_risk_parity_baseline(self, problem: OptimizationProblem) -> SolverOutput:
        """Build a deterministic asset-risk-parity approximation."""

    def solve_candidate(self, problem: OptimizationProblem) -> SolverOutput:
        """Return a bounded local candidate without a global-optimum claim."""


@dataclass(frozen=True)
class OptimizationResearchReport:
    """Immutable comparison report that never authorizes portfolio execution."""

    report_version: str
    problem_id: str
    status: OptimizationResearchStatus
    input_readiness: OptimizerInputReadiness
    problem_assessment: OptimizationProblemAssessment | None
    current_configuration: CandidateEvaluation | None
    equal_weight: CandidateEvaluation | None
    asset_risk_parity: CandidateEvaluation | None
    candidate: CandidateEvaluation | None
    comparison_complete: bool
    lowest_objective_candidate: CandidateKind | None
    blockers: tuple[OptimizationResearchBlocker, ...]
    evaluated_at: datetime
    evidence_hash: str
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        """Reject reports that publish partial comparisons as executable output."""

        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("optimization report evaluated_at must be timezone-aware")
        if self.status is OptimizationResearchStatus.COMPLETED:
            if (
                self.current_configuration is None
                or self.equal_weight is None
                or self.asset_risk_parity is None
                or self.candidate is None
            ):
                raise ValueError("completed optimization report requires all comparisons")
        elif self.comparison_complete or self.lowest_objective_candidate is not None:
            raise ValueError("blocked optimization report cannot publish a winner")
        if self.comparison_complete and self.lowest_objective_candidate is None:
            raise ValueError("complete comparison requires a lowest-objective candidate")
        if (
            not self.research_only
            or not self.must_not_execute
            or not self.must_not_use_for_decision
        ):
            raise ValueError("optimization report must remain non-executable research")
        _require_sha256(self.evidence_hash)


class RunConstrainedOptimizationResearchUseCase:
    """Run solver research only after the existing R8 input gate succeeds."""

    def __init__(
        self,
        *,
        input_evaluator: EvaluateOptimizerInputsUseCase,
        problem_provider: OptimizationProblemProvider,
        engine: ConstrainedOptimizationEngineProtocol,
    ) -> None:
        self._input_evaluator = input_evaluator
        self._problem_provider = problem_provider
        self._engine = engine

    def execute(
        self,
        *,
        problem_id: str,
        bundle_id: str,
        portfolio_snapshot_id: str,
        decision_snapshot_id: str,
        universe_hash: str,
        evaluated_at: datetime,
    ) -> OptimizationResearchReport:
        """Gate, validate, solve, and compare without execution side effects."""

        readiness = self._input_evaluator.execute(
            bundle_id=bundle_id,
            portfolio_snapshot_id=portfolio_snapshot_id,
            decision_snapshot_id=decision_snapshot_id,
            universe_hash=universe_hash,
            evaluated_at=evaluated_at,
        )
        readiness_blockers = tuple(
            OptimizationResearchBlocker(item.reason_code, item.detail)
            for item in readiness.blockers
        )
        if not readiness.can_run_research_preview:
            return _build_report(
                problem_id=problem_id,
                readiness=readiness,
                problem_assessment=None,
                equal_weight=None,
                asset_risk_parity=None,
                candidate=None,
                blockers=readiness_blockers,
                evaluated_at=evaluated_at,
            )
        problem = self._problem_provider.get_problem(problem_id)
        if problem is None:
            return _build_report(
                problem_id=problem_id,
                readiness=readiness,
                problem_assessment=None,
                equal_weight=None,
                asset_risk_parity=None,
                candidate=None,
                blockers=(
                    OptimizationResearchBlocker(
                        "optimization_problem.missing",
                        "canonical numerical optimization problem is unavailable",
                    ),
                ),
                evaluated_at=evaluated_at,
            )
        identity_blockers = _validate_problem_identity(
            problem=problem,
            readiness=readiness,
            portfolio_snapshot_id=portfolio_snapshot_id,
            decision_snapshot_id=decision_snapshot_id,
            universe_hash=universe_hash,
        )
        assessment = assess_optimization_problem(problem, evaluated_at=evaluated_at)
        problem_blockers = tuple(
            OptimizationResearchBlocker(
                f"optimization_problem.{item.code.value}",
                item.detail,
            )
            for item in assessment.blockers
        )
        blockers = (*identity_blockers, *problem_blockers)
        if blockers or not assessment.ready_for_solver:
            return _build_report(
                problem_id=problem_id,
                readiness=readiness,
                problem_assessment=assessment,
                equal_weight=None,
                asset_risk_parity=None,
                candidate=None,
                blockers=blockers,
                evaluated_at=evaluated_at,
            )

        equal_weight = evaluate_solver_output(
            problem,
            self._engine.equal_weight_baseline(problem),
        )
        current_configuration = evaluate_solver_output(
            problem,
            self._engine.current_configuration_baseline(problem),
        )
        asset_risk_parity = evaluate_solver_output(
            problem,
            self._engine.asset_risk_parity_baseline(problem),
        )
        candidate = evaluate_solver_output(
            problem,
            self._engine.solve_candidate(problem),
        )
        evaluations = (
            current_configuration,
            equal_weight,
            asset_risk_parity,
            candidate,
        )
        comparison_complete = all(item.eligible_for_comparison for item in evaluations)
        lowest = (
            min(
                evaluations,
                key=lambda item: (
                    (
                        item.metrics.objective_value
                        if item.metrics is not None
                        else Decimal("Infinity")
                    ),
                    item.candidate_kind.value,
                ),
            ).candidate_kind
            if comparison_complete
            else None
        )
        comparison_blockers = tuple(
            OptimizationResearchBlocker(
                f"optimization_candidate.{evaluation.candidate_kind.value}.{blocker.code.value}",
                blocker.detail,
            )
            for evaluation in evaluations
            for blocker in evaluation.blockers
        )
        return _build_report(
            problem_id=problem_id,
            readiness=readiness,
            problem_assessment=assessment,
            current_configuration=current_configuration,
            equal_weight=equal_weight,
            asset_risk_parity=asset_risk_parity,
            candidate=candidate,
            blockers=comparison_blockers,
            evaluated_at=evaluated_at,
            comparison_complete=comparison_complete,
            lowest_objective_candidate=lowest,
        )


def _validate_problem_identity(
    *,
    problem: OptimizationProblem,
    readiness: OptimizerInputReadiness,
    portfolio_snapshot_id: str,
    decision_snapshot_id: str,
    universe_hash: str,
) -> tuple[OptimizationResearchBlocker, ...]:
    blockers: list[OptimizationResearchBlocker] = []
    if problem.canonical_snapshot.snapshot_id != portfolio_snapshot_id:
        blockers.append(
            OptimizationResearchBlocker(
                "optimization_problem.canonical_snapshot_mismatch",
                "problem does not match the gated canonical portfolio snapshot",
            )
        )
    if problem.decision_snapshot_id != decision_snapshot_id:
        blockers.append(
            OptimizationResearchBlocker(
                "optimization_problem.decision_snapshot_mismatch",
                "problem does not match the gated decision snapshot",
            )
        )
    if problem.universe_hash != universe_hash:
        blockers.append(
            OptimizationResearchBlocker(
                "optimization_problem.universe_hash_mismatch",
                "problem does not match the gated asset universe",
            )
        )
    ready_evidence = {item.kind: item for item in readiness.evidence}
    for binding in problem.evidence_bindings:
        evidence = ready_evidence.get(binding.kind)
        if evidence is None or evidence.state is not OptimizationEvidenceState.VERIFIED:
            blockers.append(
                OptimizationResearchBlocker(
                    f"optimization_problem.evidence.{binding.kind.value}.missing",
                    "problem input is absent from verified readiness evidence",
                )
            )
            continue
        if (
            evidence.version != binding.version
            or evidence.evidence_ref != binding.evidence_ref
            or evidence.content_hash != binding.content_hash
            or evidence.universe_hash != binding.universe_hash
        ):
            blockers.append(
                OptimizationResearchBlocker(
                    f"optimization_problem.evidence.{binding.kind.value}.mismatch",
                    "problem input does not match the exact gated evidence version",
                )
            )
    ready_promotions = {item.capability_key: item for item in readiness.promotions}
    for promotion in problem.promotions:
        ready = ready_promotions.get(promotion.capability_key)
        if ready != promotion:
            blockers.append(
                OptimizationResearchBlocker(
                    f"optimization_problem.promotion.{promotion.capability_key}.mismatch",
                    "problem promotion does not match the gated R3/R4/R5 reference",
                )
            )
    return tuple(blockers)


def _build_report(
    *,
    problem_id: str,
    readiness: OptimizerInputReadiness,
    problem_assessment: OptimizationProblemAssessment | None,
    equal_weight: CandidateEvaluation | None,
    asset_risk_parity: CandidateEvaluation | None,
    candidate: CandidateEvaluation | None,
    blockers: tuple[OptimizationResearchBlocker, ...],
    evaluated_at: datetime,
    current_configuration: CandidateEvaluation | None = None,
    comparison_complete: bool = False,
    lowest_objective_candidate: CandidateKind | None = None,
) -> OptimizationResearchReport:
    status = (
        OptimizationResearchStatus.COMPLETED
        if comparison_complete
        else OptimizationResearchStatus.BLOCKED
    )
    evidence_hash = _hash_components(
        "constrained-optimization-research-report.v1",
        problem_id,
        readiness.bundle_id,
        status.value,
        problem_assessment.evidence_hash if problem_assessment is not None else "",
        current_configuration.evidence_hash if current_configuration is not None else "",
        equal_weight.evidence_hash if equal_weight is not None else "",
        asset_risk_parity.evidence_hash if asset_risk_parity is not None else "",
        candidate.evidence_hash if candidate is not None else "",
        str(comparison_complete),
        lowest_objective_candidate.value if lowest_objective_candidate is not None else "",
        *(f"{item.reason_code}:{item.detail}" for item in blockers),
        evaluated_at.isoformat(),
    )
    return OptimizationResearchReport(
        report_version="constrained-optimization-research-report.v1",
        problem_id=problem_id,
        status=status,
        input_readiness=readiness,
        problem_assessment=problem_assessment,
        current_configuration=current_configuration,
        equal_weight=equal_weight,
        asset_risk_parity=asset_risk_parity,
        candidate=candidate,
        comparison_complete=comparison_complete,
        lowest_objective_candidate=lowest_objective_candidate,
        blockers=blockers,
        evaluated_at=evaluated_at,
        evidence_hash=evidence_hash,
        research_only=True,
        must_not_execute=True,
        must_not_use_for_decision=True,
    )


def _hash_components(*components: str) -> str:
    digest = hashlib.sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("evidence_hash must be a lowercase SHA-256 digest")
