"""Component coverage for the gated R8 constrained optimization use case."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.portfolio.application.constrained_optimization import (
    OptimizationResearchStatus,
    RunConstrainedOptimizationResearchUseCase,
)
from apps.portfolio.application.optimizer_inputs import EvaluateOptimizerInputsUseCase
from apps.portfolio.domain.constrained_optimization_contracts import OptimizationProblem
from apps.portfolio.domain.optimizer_inputs import (
    OptimizationEvidenceState,
    OptimizationInputEvidence,
    OptimizationInputKind,
    OptimizationInputRequirement,
    OptimizerInputContract,
    PromotionReference,
)
from apps.portfolio.infrastructure.deterministic_optimizer import (
    DeterministicConstrainedSearchAdapter,
)
from tests.unit.portfolio.test_constrained_optimization import _problem

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


class _ContractProvider:
    def get_active(self, *, evaluated_at: datetime) -> OptimizerInputContract:
        assert evaluated_at == NOW
        return OptimizerInputContract(
            contract_version="multi-asset-input.v2",
            methodology="constrained_multi_asset_research",
            requirements=tuple(
                OptimizationInputRequirement(kind, f"owner-{kind.value}")
                for kind in OptimizationInputKind
            ),
            required_promotion_keys=("r3", "r4", "r5"),
            activated_at=NOW - timedelta(days=1),
            valid_until=NOW + timedelta(days=30),
        )


class _EvidenceProvider:
    def __init__(
        self,
        problem: OptimizationProblem,
        *,
        omitted_kind: OptimizationInputKind | None = None,
        mismatched_kind: OptimizationInputKind | None = None,
        omitted_promotion: str | None = None,
    ) -> None:
        self._problem = problem
        self._omitted_kind = omitted_kind
        self._mismatched_kind = mismatched_kind
        self._omitted_promotion = omitted_promotion

    def collect_inputs(
        self,
        *,
        contract: OptimizerInputContract,
        portfolio_snapshot_id: str,
        universe_hash: str,
        evaluated_at: datetime,
    ) -> tuple[OptimizationInputEvidence, ...]:
        assert evaluated_at == NOW
        assert universe_hash == self._problem.universe_hash
        bindings = {item.kind: item for item in self._problem.evidence_bindings}
        return tuple(
            OptimizationInputEvidence(
                kind=requirement.kind,
                owner=requirement.canonical_owner,
                state=OptimizationEvidenceState.VERIFIED,
                observed_at=NOW - timedelta(hours=1),
                valid_until=NOW + timedelta(days=1),
                version=bindings[requirement.kind].version,
                evidence_ref=bindings[requirement.kind].evidence_ref,
                content_hash=(
                    "f" * 64
                    if requirement.kind is self._mismatched_kind
                    else bindings[requirement.kind].content_hash
                ),
                universe_hash=universe_hash,
            )
            for requirement in contract.requirements
            if requirement.kind is not self._omitted_kind
        )

    def collect_promotions(
        self,
        *,
        contract: OptimizerInputContract,
        evaluated_at: datetime,
    ) -> tuple[PromotionReference, ...]:
        assert evaluated_at == NOW
        return tuple(
            promotion
            for promotion in self._problem.promotions
            if promotion.capability_key != self._omitted_promotion
        )


class _ProblemProvider:
    def __init__(self, problem: OptimizationProblem) -> None:
        self.problem = problem
        self.calls = 0

    def get_problem(self, problem_id: str) -> OptimizationProblem | None:
        self.calls += 1
        assert problem_id == self.problem.problem_id
        return self.problem


class _Engine:
    def __init__(self) -> None:
        self.adapter = DeterministicConstrainedSearchAdapter()
        self.calls = 0

    def equal_weight_baseline(self, problem: OptimizationProblem):
        self.calls += 1
        return self.adapter.equal_weight_baseline(problem)

    def asset_risk_parity_baseline(self, problem: OptimizationProblem):
        self.calls += 1
        return self.adapter.asset_risk_parity_baseline(problem)

    def solve_candidate(self, problem: OptimizationProblem):
        self.calls += 1
        return self.adapter.solve_candidate(problem)


def _use_case(
    problem: OptimizationProblem,
    evidence_provider: _EvidenceProvider,
    problem_provider: _ProblemProvider,
    engine: _Engine,
) -> RunConstrainedOptimizationResearchUseCase:
    evaluator = EvaluateOptimizerInputsUseCase(
        contract_provider=_ContractProvider(),
        evidence_provider=evidence_provider,
    )
    return RunConstrainedOptimizationResearchUseCase(
        input_evaluator=evaluator,
        problem_provider=problem_provider,
        engine=engine,
    )


def _execute(
    use_case: RunConstrainedOptimizationResearchUseCase,
    problem: OptimizationProblem,
):
    return use_case.execute(
        problem_id=problem.problem_id,
        bundle_id="optimizer-bundle-r8-v1",
        portfolio_snapshot_id=problem.canonical_snapshot.snapshot_id,
        decision_snapshot_id=problem.decision_snapshot_id,
        universe_hash=problem.universe_hash,
        evaluated_at=NOW,
    )


def test_ready_inputs_compare_equal_weight_risk_parity_and_local_candidate() -> None:
    problem = _problem()
    provider = _ProblemProvider(problem)
    engine = _Engine()
    report = _execute(
        _use_case(problem, _EvidenceProvider(problem), provider, engine),
        problem,
    )

    assert report.status is OptimizationResearchStatus.COMPLETED
    assert report.equal_weight is not None
    assert report.asset_risk_parity is not None
    assert report.candidate is not None
    assert report.research_only is True
    assert report.must_not_execute is True
    assert report.must_not_use_for_decision is True
    assert provider.calls == 1
    assert engine.calls == 3


def test_missing_execution_feedback_or_r4_promotion_never_reaches_problem_or_solver() -> None:
    for evidence_provider in (
        _EvidenceProvider(
            _problem(),
            omitted_kind=OptimizationInputKind.EXECUTION_FEEDBACK,
        ),
        _EvidenceProvider(_problem(), omitted_promotion="r4"),
    ):
        problem = evidence_provider._problem
        provider = _ProblemProvider(problem)
        engine = _Engine()
        report = _execute(
            _use_case(problem, evidence_provider, provider, engine),
            problem,
        )

        assert report.status is OptimizationResearchStatus.BLOCKED
        assert provider.calls == 0
        assert engine.calls == 0


def test_exact_evidence_hash_mismatch_blocks_before_solver() -> None:
    problem = _problem()
    provider = _ProblemProvider(problem)
    engine = _Engine()
    report = _execute(
        _use_case(
            problem,
            _EvidenceProvider(
                problem,
                mismatched_kind=OptimizationInputKind.EXPECTED_RETURN,
            ),
            provider,
            engine,
        ),
        problem,
    )

    assert report.status is OptimizationResearchStatus.BLOCKED
    assert any("expected_return.mismatch" in item.reason_code for item in report.blockers)
    assert engine.calls == 0


def test_non_psd_problem_never_calls_solver() -> None:
    problem = _problem(
        covariance_values=(
            (Decimal("0.01"), Decimal("0.02")),
            (Decimal("0.02"), Decimal("0.01")),
        )
    )
    provider = _ProblemProvider(problem)
    engine = _Engine()
    report = _execute(
        _use_case(problem, _EvidenceProvider(problem), provider, engine),
        problem,
    )

    assert report.status is OptimizationResearchStatus.BLOCKED
    assert any("covariance_not_psd" in item.reason_code for item in report.blockers)
    assert engine.calls == 0
