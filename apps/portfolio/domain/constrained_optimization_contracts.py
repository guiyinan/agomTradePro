"""Immutable contracts for constrained multi-asset optimization research."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from apps.portfolio.domain.canonical_snapshots import CanonicalPortfolioSnapshot
from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateReport
from apps.portfolio.domain.optimizer_inputs import (
    OptimizationInputKind,
    PromotionReference,
)

REQUIRED_UPSTREAM_PROMOTIONS = frozenset({"r3", "r4", "r5"})
REQUIRED_OPTIMIZATION_INPUTS = frozenset(OptimizationInputKind)


class ManualRestriction(str, Enum):
    """Human restriction applied to one asset relative to canonical holdings."""

    NONE = "none"
    FIXED = "fixed"
    NO_BUY = "no_buy"
    NO_SELL = "no_sell"


class CandidateKind(str, Enum):
    """Deterministic candidates compared by the research report."""

    EQUAL_WEIGHT = "equal_weight"
    ASSET_RISK_PARITY = "asset_risk_parity"
    DETERMINISTIC_SEARCH = "deterministic_search"


class SolverConvergenceStatus(str, Enum):
    """Truthful status emitted by a deterministic optimization adapter."""

    BASELINE = "baseline"
    LOCAL_STATIONARY = "local_stationary"
    ITERATION_LIMIT = "iteration_limit"
    INFEASIBLE = "infeasible"
    NUMERICAL_FAILURE = "numerical_failure"


@dataclass(frozen=True)
class OptimizationEvidenceBinding:
    """Exact verified input version consumed by one numerical problem."""

    kind: OptimizationInputKind
    version: str
    evidence_ref: str
    content_hash: str
    universe_hash: str

    def __post_init__(self) -> None:
        """Reject an input binding without version, evidence, or strong hashes."""

        _require_token(self.version, "evidence version")
        _require_text(self.evidence_ref, "evidence_ref")
        _require_sha256(self.content_hash, "evidence content_hash")
        _require_sha256(self.universe_hash, "evidence universe_hash")


@dataclass(frozen=True)
class AssetOptimizationInput:
    """Versioned asset assumptions excluding canonical current weight."""

    asset_code: str
    expected_return: Decimal
    minimum_weight: Decimal
    maximum_weight: Decimal
    maximum_trade_weight: Decimal
    transaction_cost_rate: Decimal
    drawdown_loss: Decimal
    manual_restriction: ManualRestriction = ManualRestriction.NONE

    def __post_init__(self) -> None:
        """Validate one finite bounded asset assumption."""

        _require_token(self.asset_code, "asset_code")
        for field_name, asset_value in (
            ("expected_return", self.expected_return),
            ("minimum_weight", self.minimum_weight),
            ("maximum_weight", self.maximum_weight),
            ("maximum_trade_weight", self.maximum_trade_weight),
            ("transaction_cost_rate", self.transaction_cost_rate),
            ("drawdown_loss", self.drawdown_loss),
        ):
            _require_finite(asset_value, field_name)
        if not Decimal("0") <= self.minimum_weight <= self.maximum_weight <= Decimal("1"):
            raise ValueError("asset weight bounds must be ordered within [0, 1]")
        if self.maximum_trade_weight < 0 or self.maximum_trade_weight > 1:
            raise ValueError("maximum_trade_weight must be within [0, 1]")
        if self.transaction_cost_rate < 0:
            raise ValueError("transaction_cost_rate cannot be negative")
        if self.drawdown_loss < 0:
            raise ValueError("drawdown_loss cannot be negative")
        if not isinstance(self.manual_restriction, ManualRestriction):
            raise ValueError("manual_restriction is invalid")


@dataclass(frozen=True)
class AssetOptimizationConstraint:
    """Asset assumptions bound to current weight from a canonical snapshot."""

    asset_code: str
    current_weight: Decimal
    expected_return: Decimal
    minimum_weight: Decimal
    maximum_weight: Decimal
    maximum_trade_weight: Decimal
    transaction_cost_rate: Decimal
    drawdown_loss: Decimal
    manual_restriction: ManualRestriction


@dataclass(frozen=True)
class AssetCovarianceMatrix:
    """Versioned asset covariance aligned to the exact optimization universe."""

    version: str
    asset_codes: tuple[str, ...]
    values: tuple[tuple[Decimal, ...], ...]
    observed_at: datetime
    valid_until: datetime
    universe_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        version: str,
        asset_codes: tuple[str, ...],
        values: tuple[tuple[Decimal, ...], ...],
        observed_at: datetime,
        valid_until: datetime,
        universe_hash: str,
    ) -> AssetCovarianceMatrix:
        """Create a structurally valid matrix and freeze its content hash."""

        digest = asset_covariance_hash(
            version=version,
            asset_codes=asset_codes,
            values=values,
            observed_at=observed_at,
            valid_until=valid_until,
            universe_hash=universe_hash,
        )
        return cls(
            version=version,
            asset_codes=asset_codes,
            values=values,
            observed_at=observed_at,
            valid_until=valid_until,
            universe_hash=universe_hash,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Validate matrix shape, clocks, values, universe, and immutable hash."""

        _require_token(self.version, "covariance version")
        _require_aware(self.observed_at, "covariance observed_at")
        _require_aware(self.valid_until, "covariance valid_until")
        if self.valid_until <= self.observed_at:
            raise ValueError("covariance valid_until must follow observed_at")
        if not self.asset_codes or len(self.asset_codes) != len(set(self.asset_codes)):
            raise ValueError("covariance asset codes must be non-empty and unique")
        size = len(self.asset_codes)
        if len(self.values) != size or any(len(row) != size for row in self.values):
            raise ValueError("asset covariance matrix must be square")
        for row in self.values:
            for value in row:
                _require_finite(value, "covariance value")
        _require_sha256(self.universe_hash, "covariance universe_hash")
        _require_sha256(self.content_hash, "covariance content_hash")
        if self.content_hash != asset_covariance_hash(
            version=self.version,
            asset_codes=self.asset_codes,
            values=self.values,
            observed_at=self.observed_at,
            valid_until=self.valid_until,
            universe_hash=self.universe_hash,
        ):
            raise ValueError("asset covariance content_hash mismatch")


@dataclass(frozen=True)
class ScenarioLossConstraint:
    """Maximum acceptable loss for one versioned scenario revision."""

    scenario_revision_id: str
    scenario_version: str
    asset_codes: tuple[str, ...]
    loss_rates: tuple[Decimal, ...]
    maximum_portfolio_loss: Decimal
    evidence_hash: str

    def __post_init__(self) -> None:
        """Validate aligned finite losses and an explicit scenario evidence hash."""

        _require_token(self.scenario_revision_id, "scenario_revision_id")
        _require_token(self.scenario_version, "scenario_version")
        if not self.asset_codes or len(self.asset_codes) != len(set(self.asset_codes)):
            raise ValueError("scenario loss asset codes must be non-empty and unique")
        if len(self.loss_rates) != len(self.asset_codes):
            raise ValueError("scenario loss rates must align with asset codes")
        for loss_rate in self.loss_rates:
            _require_finite(loss_rate, "scenario loss rate")
            if loss_rate < 0:
                raise ValueError("scenario loss rates cannot be negative")
        _require_finite(self.maximum_portfolio_loss, "maximum_portfolio_loss")
        if not Decimal("0") <= self.maximum_portfolio_loss <= Decimal("1"):
            raise ValueError("maximum_portfolio_loss must be within [0, 1]")
        _require_sha256(self.evidence_hash, "scenario evidence_hash")


@dataclass(frozen=True)
class OptimizationObjective:
    """Versioned objective weights for expected return, variance, and costs."""

    objective_version: str
    expected_return_weight: Decimal
    variance_penalty: Decimal
    transaction_cost_penalty: Decimal

    def __post_init__(self) -> None:
        """Require finite non-negative objective coefficients."""

        _require_token(self.objective_version, "objective_version")
        for field_name, objective_value in (
            ("expected_return_weight", self.expected_return_weight),
            ("variance_penalty", self.variance_penalty),
            ("transaction_cost_penalty", self.transaction_cost_penalty),
        ):
            _require_finite(objective_value, field_name)
            if objective_value < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.expected_return_weight == self.variance_penalty == 0:
            raise ValueError("objective requires return or variance weight")


@dataclass(frozen=True)
class OptimizationValidationPolicy:
    """Versioned numerical tolerances and deterministic solver limits."""

    policy_version: str
    activated_at: datetime
    valid_until: datetime
    weight_tolerance: Decimal
    covariance_symmetry_tolerance: Decimal
    covariance_psd_tolerance: Decimal
    solver_max_iterations: int
    solver_initial_step: Decimal
    solver_minimum_step: Decimal
    risk_parity_max_iterations: int
    risk_parity_tolerance: Decimal

    def __post_init__(self) -> None:
        """Validate all policy clocks, tolerances, and iteration budgets."""

        _require_token(self.policy_version, "policy_version")
        _require_aware(self.activated_at, "policy activated_at")
        _require_aware(self.valid_until, "policy valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("optimization policy valid_until must follow activated_at")
        for field_name, policy_tolerance in (
            ("weight_tolerance", self.weight_tolerance),
            ("covariance_symmetry_tolerance", self.covariance_symmetry_tolerance),
            ("covariance_psd_tolerance", self.covariance_psd_tolerance),
            ("solver_initial_step", self.solver_initial_step),
            ("solver_minimum_step", self.solver_minimum_step),
            ("risk_parity_tolerance", self.risk_parity_tolerance),
        ):
            _require_finite(policy_tolerance, field_name)
            if policy_tolerance <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.solver_minimum_step > self.solver_initial_step:
            raise ValueError("solver_minimum_step cannot exceed solver_initial_step")
        for field_name, iteration_count in (
            ("solver_max_iterations", self.solver_max_iterations),
            ("risk_parity_max_iterations", self.risk_parity_max_iterations),
        ):
            if (
                isinstance(iteration_count, bool)
                or not isinstance(iteration_count, int)
                or iteration_count < 1
            ):
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class OptimizationProblem:
    """Fully bound, immutable research optimization problem."""

    problem_id: str
    problem_version: str
    canonical_snapshot: CanonicalPortfolioSnapshot
    decision_snapshot_id: str
    universe_hash: str
    assets: tuple[AssetOptimizationConstraint, ...]
    covariance: AssetCovarianceMatrix
    scenario_losses: tuple[ScenarioLossConstraint, ...]
    minimum_cash_weight: Decimal
    target_cash_weight: Decimal
    maximum_turnover: Decimal
    maximum_transaction_cost: Decimal
    maximum_drawdown: Decimal
    execution_feedback_hash: str
    objective: OptimizationObjective
    validation_policy: OptimizationValidationPolicy
    evidence_bindings: tuple[OptimizationEvidenceBinding, ...]
    promotions: tuple[PromotionReference, ...]
    macro_risk_report: MacroRiskCandidateReport
    created_at: datetime
    valid_until: datetime
    content_hash: str

    def __post_init__(self) -> None:
        """Validate identity, canonical snapshot binding, lineage, and problem hash."""

        for field_name, value in (
            ("problem_id", self.problem_id),
            ("problem_version", self.problem_version),
            ("decision_snapshot_id", self.decision_snapshot_id),
        ):
            _require_token(value, field_name)
        _require_sha256(self.universe_hash, "universe_hash")
        _require_sha256(self.execution_feedback_hash, "execution_feedback_hash")
        _require_sha256(self.content_hash, "problem content_hash")
        _require_aware(self.created_at, "problem created_at")
        _require_aware(self.valid_until, "problem valid_until")
        if self.valid_until <= self.created_at:
            raise ValueError("problem valid_until must follow created_at")
        if self.canonical_snapshot.as_of > self.created_at:
            raise ValueError("optimization problem cannot predate its canonical snapshot")
        asset_codes = tuple(asset.asset_code for asset in self.assets)
        if not asset_codes or len(asset_codes) != len(set(asset_codes)):
            raise ValueError("optimization assets must be non-empty and unique")
        if asset_codes != tuple(sorted(asset_codes)):
            raise ValueError("optimization assets must use canonical ordering")
        snapshot_codes = tuple(
            sorted(position.asset_code for position in self.canonical_snapshot.positions)
        )
        if asset_codes != snapshot_codes:
            raise ValueError("optimization universe must match canonical snapshot positions")
        if self.universe_hash != build_asset_universe_hash(asset_codes):
            raise ValueError("optimization universe_hash mismatch")
        if self.covariance.asset_codes != asset_codes:
            raise ValueError("covariance asset universe mismatch")
        if self.covariance.universe_hash != self.universe_hash:
            raise ValueError("covariance universe_hash mismatch")
        if any(scenario.asset_codes != asset_codes for scenario in self.scenario_losses):
            raise ValueError("scenario loss universe mismatch")
        if not self.scenario_losses:
            raise ValueError("optimization problem requires scenario loss evidence")
        _validate_asset_constraints(self.assets)
        _validate_problem_limits(self)
        _validate_current_weights(self)
        _validate_evidence_bindings(self)
        _validate_promotions(self.promotions)
        if (
            not self.macro_risk_report.eligible_for_research_comparison
            or self.macro_risk_report.blockers
            or self.macro_risk_report.usage_scope != "research_only"
            or not self.macro_risk_report.must_not_use_for_decision
            or not self.macro_risk_report.must_not_execute
        ):
            raise ValueError("optimization problem requires verified research-only macro risk")
        if self.macro_risk_report.evaluated_at > self.created_at:
            raise ValueError("macro risk evidence cannot postdate optimization problem")
        macro_binding = _binding_by_kind(self)[OptimizationInputKind.MACRO_EXPOSURE]
        if macro_binding.content_hash != self.macro_risk_report.evidence_hash:
            raise ValueError("macro risk evidence hash mismatch")
        if self.content_hash != optimization_problem_hash(self):
            raise ValueError("optimization problem content_hash mismatch")

    @property
    def invested_weight(self) -> Decimal:
        """Return the fixed non-cash weight used by deterministic candidates."""

        return Decimal("1") - self.target_cash_weight


@dataclass(frozen=True)
class SolverOutput:
    """Deterministic solver output that explicitly denies global optimality."""

    candidate_kind: CandidateKind
    weights: tuple[Decimal, ...] | None
    cash_weight: Decimal | None
    status: SolverConvergenceStatus
    iterations: int
    residual: Decimal
    detail: str
    declares_global_optimum: bool
    content_hash: str

    def __post_init__(self) -> None:
        """Validate convergence evidence and prohibit global-optimum claims."""

        if isinstance(self.iterations, bool) or self.iterations < 0:
            raise ValueError("solver iterations cannot be negative")
        _require_finite(self.residual, "solver residual")
        if self.residual < 0:
            raise ValueError("solver residual cannot be negative")
        _require_text(self.detail, "solver detail")
        if self.declares_global_optimum:
            raise ValueError("deterministic research solver cannot claim global optimality")
        if (self.weights is None) != (self.cash_weight is None):
            raise ValueError("solver weights and cash_weight must be present together")
        if self.weights is not None:
            for weight in self.weights:
                _require_finite(weight, "solver weight")
            assert self.cash_weight is not None
            _require_finite(self.cash_weight, "solver cash_weight")
        _require_sha256(self.content_hash, "solver output content_hash")
        if self.content_hash != solver_output_hash(
            candidate_kind=self.candidate_kind,
            weights=self.weights,
            cash_weight=self.cash_weight,
            status=self.status,
            iterations=self.iterations,
            residual=self.residual,
            detail=self.detail,
        ):
            raise ValueError("solver output content_hash mismatch")


def build_solver_output(
    *,
    candidate_kind: CandidateKind,
    weights: tuple[Decimal, ...] | None,
    cash_weight: Decimal | None,
    status: SolverConvergenceStatus,
    iterations: int,
    residual: Decimal,
    detail: str,
) -> SolverOutput:
    """Build one immutable solver output with no global-optimum declaration."""

    return SolverOutput(
        candidate_kind=candidate_kind,
        weights=weights,
        cash_weight=cash_weight,
        status=status,
        iterations=iterations,
        residual=residual,
        detail=detail,
        declares_global_optimum=False,
        content_hash=solver_output_hash(
            candidate_kind=candidate_kind,
            weights=weights,
            cash_weight=cash_weight,
            status=status,
            iterations=iterations,
            residual=residual,
            detail=detail,
        ),
    )


def build_asset_universe_hash(asset_codes: tuple[str, ...]) -> str:
    """Return the canonical hash for an ordered asset universe."""

    return _hash_components("asset-universe.v1", *asset_codes)


def build_optimization_problem(
    *,
    problem_id: str,
    problem_version: str,
    canonical_snapshot: CanonicalPortfolioSnapshot,
    decision_snapshot_id: str,
    asset_inputs: tuple[AssetOptimizationInput, ...],
    covariance: AssetCovarianceMatrix,
    scenario_losses: tuple[ScenarioLossConstraint, ...],
    minimum_cash_weight: Decimal,
    target_cash_weight: Decimal,
    maximum_turnover: Decimal,
    maximum_transaction_cost: Decimal,
    maximum_drawdown: Decimal,
    execution_feedback_hash: str,
    objective: OptimizationObjective,
    validation_policy: OptimizationValidationPolicy,
    evidence_bindings: tuple[OptimizationEvidenceBinding, ...],
    promotions: tuple[PromotionReference, ...],
    macro_risk_report: MacroRiskCandidateReport,
    created_at: datetime,
    valid_until: datetime,
) -> OptimizationProblem:
    """Build a problem whose current weights come only from the canonical snapshot."""

    total_value = canonical_snapshot.cash_balance + sum(
        (position.market_value_base for position in canonical_snapshot.positions),
        start=Decimal("0"),
    )
    if total_value <= 0:
        raise ValueError("canonical snapshot total value must be positive")
    positions = {position.asset_code: position for position in canonical_snapshot.positions}
    ordered_inputs = tuple(sorted(asset_inputs, key=lambda item: item.asset_code))
    if set(positions) != {item.asset_code for item in ordered_inputs}:
        raise ValueError("asset inputs must match canonical snapshot positions")
    assets = tuple(
        AssetOptimizationConstraint(
            asset_code=item.asset_code,
            current_weight=positions[item.asset_code].market_value_base / total_value,
            expected_return=item.expected_return,
            minimum_weight=item.minimum_weight,
            maximum_weight=item.maximum_weight,
            maximum_trade_weight=item.maximum_trade_weight,
            transaction_cost_rate=item.transaction_cost_rate,
            drawdown_loss=item.drawdown_loss,
            manual_restriction=item.manual_restriction,
        )
        for item in ordered_inputs
    )
    universe_hash = build_asset_universe_hash(tuple(asset.asset_code for asset in assets))
    digest = _optimization_problem_hash_values(
        problem_id=problem_id,
        problem_version=problem_version,
        canonical_snapshot=canonical_snapshot,
        decision_snapshot_id=decision_snapshot_id,
        universe_hash=universe_hash,
        assets=assets,
        covariance=covariance,
        scenario_losses=scenario_losses,
        minimum_cash_weight=minimum_cash_weight,
        target_cash_weight=target_cash_weight,
        maximum_turnover=maximum_turnover,
        maximum_transaction_cost=maximum_transaction_cost,
        maximum_drawdown=maximum_drawdown,
        execution_feedback_hash=execution_feedback_hash,
        objective=objective,
        validation_policy=validation_policy,
        evidence_bindings=evidence_bindings,
        promotions=promotions,
        macro_risk_report=macro_risk_report,
        created_at=created_at,
        valid_until=valid_until,
    )
    return OptimizationProblem(
        problem_id=problem_id,
        problem_version=problem_version,
        canonical_snapshot=canonical_snapshot,
        decision_snapshot_id=decision_snapshot_id,
        universe_hash=universe_hash,
        assets=assets,
        covariance=covariance,
        scenario_losses=scenario_losses,
        minimum_cash_weight=minimum_cash_weight,
        target_cash_weight=target_cash_weight,
        maximum_turnover=maximum_turnover,
        maximum_transaction_cost=maximum_transaction_cost,
        maximum_drawdown=maximum_drawdown,
        execution_feedback_hash=execution_feedback_hash,
        objective=objective,
        validation_policy=validation_policy,
        evidence_bindings=evidence_bindings,
        promotions=promotions,
        macro_risk_report=macro_risk_report,
        created_at=created_at,
        valid_until=valid_until,
        content_hash=digest,
    )


def asset_covariance_hash(
    *,
    version: str,
    asset_codes: tuple[str, ...],
    values: tuple[tuple[Decimal, ...], ...],
    observed_at: datetime,
    valid_until: datetime,
    universe_hash: str,
) -> str:
    """Return the canonical covariance evidence hash."""

    return _hash_components(
        "asset-covariance.v1",
        version,
        *asset_codes,
        *("|".join(str(value) for value in row) for row in values),
        observed_at.isoformat(),
        valid_until.isoformat(),
        universe_hash,
    )


def solver_output_hash(
    *,
    candidate_kind: CandidateKind,
    weights: tuple[Decimal, ...] | None,
    cash_weight: Decimal | None,
    status: SolverConvergenceStatus,
    iterations: int,
    residual: Decimal,
    detail: str,
) -> str:
    """Return the canonical digest for deterministic convergence evidence."""

    return _hash_components(
        "optimization-solver-output.v1",
        candidate_kind.value,
        *(str(weight) for weight in (weights or ())),
        str(cash_weight if cash_weight is not None else ""),
        status.value,
        str(iterations),
        str(residual),
        detail,
        "not_global_optimum",
    )


def optimization_problem_hash(problem: OptimizationProblem) -> str:
    """Return the canonical hash of every numerical input and evidence binding."""

    return _optimization_problem_hash_values(
        problem_id=problem.problem_id,
        problem_version=problem.problem_version,
        canonical_snapshot=problem.canonical_snapshot,
        decision_snapshot_id=problem.decision_snapshot_id,
        universe_hash=problem.universe_hash,
        assets=problem.assets,
        covariance=problem.covariance,
        scenario_losses=problem.scenario_losses,
        minimum_cash_weight=problem.minimum_cash_weight,
        target_cash_weight=problem.target_cash_weight,
        maximum_turnover=problem.maximum_turnover,
        maximum_transaction_cost=problem.maximum_transaction_cost,
        maximum_drawdown=problem.maximum_drawdown,
        execution_feedback_hash=problem.execution_feedback_hash,
        objective=problem.objective,
        validation_policy=problem.validation_policy,
        evidence_bindings=problem.evidence_bindings,
        promotions=problem.promotions,
        macro_risk_report=problem.macro_risk_report,
        created_at=problem.created_at,
        valid_until=problem.valid_until,
    )


def _optimization_problem_hash_values(
    *,
    problem_id: str,
    problem_version: str,
    canonical_snapshot: CanonicalPortfolioSnapshot,
    decision_snapshot_id: str,
    universe_hash: str,
    assets: tuple[AssetOptimizationConstraint, ...],
    covariance: AssetCovarianceMatrix,
    scenario_losses: tuple[ScenarioLossConstraint, ...],
    minimum_cash_weight: Decimal,
    target_cash_weight: Decimal,
    maximum_turnover: Decimal,
    maximum_transaction_cost: Decimal,
    maximum_drawdown: Decimal,
    execution_feedback_hash: str,
    objective: OptimizationObjective,
    validation_policy: OptimizationValidationPolicy,
    evidence_bindings: tuple[OptimizationEvidenceBinding, ...],
    promotions: tuple[PromotionReference, ...],
    macro_risk_report: MacroRiskCandidateReport,
    created_at: datetime,
    valid_until: datetime,
) -> str:

    asset_parts = tuple(
        "|".join(
            (
                asset.asset_code,
                str(asset.current_weight),
                str(asset.expected_return),
                str(asset.minimum_weight),
                str(asset.maximum_weight),
                str(asset.maximum_trade_weight),
                str(asset.transaction_cost_rate),
                str(asset.drawdown_loss),
                asset.manual_restriction.value,
            )
        )
        for asset in assets
    )
    scenario_parts = tuple(
        "|".join(
            (
                scenario.scenario_revision_id,
                scenario.scenario_version,
                *scenario.asset_codes,
                *(str(loss) for loss in scenario.loss_rates),
                str(scenario.maximum_portfolio_loss),
                scenario.evidence_hash,
            )
        )
        for scenario in scenario_losses
    )
    evidence_parts = tuple(
        f"{item.kind.value}|{item.version}|{item.evidence_ref}|"
        f"{item.content_hash}|{item.universe_hash}"
        for item in evidence_bindings
    )
    promotion_parts = tuple(
        f"{item.capability_key}|{item.version}|{item.decision_ref}|"
        f"{item.approved_at.isoformat()}|{item.valid_until.isoformat()}"
        for item in promotions
    )
    return _hash_components(
        "constrained-optimization-problem.v1",
        problem_id,
        problem_version,
        canonical_snapshot.snapshot_id,
        canonical_snapshot.content_hash,
        decision_snapshot_id,
        universe_hash,
        *asset_parts,
        covariance.content_hash,
        *scenario_parts,
        str(minimum_cash_weight),
        str(target_cash_weight),
        str(maximum_turnover),
        str(maximum_transaction_cost),
        str(maximum_drawdown),
        execution_feedback_hash,
        objective.objective_version,
        str(objective.expected_return_weight),
        str(objective.variance_penalty),
        str(objective.transaction_cost_penalty),
        validation_policy.policy_version,
        validation_policy.activated_at.isoformat(),
        validation_policy.valid_until.isoformat(),
        str(validation_policy.weight_tolerance),
        str(validation_policy.covariance_symmetry_tolerance),
        str(validation_policy.covariance_psd_tolerance),
        str(validation_policy.solver_max_iterations),
        str(validation_policy.solver_initial_step),
        str(validation_policy.solver_minimum_step),
        str(validation_policy.risk_parity_max_iterations),
        str(validation_policy.risk_parity_tolerance),
        *evidence_parts,
        *promotion_parts,
        macro_risk_report.evidence_hash,
        created_at.isoformat(),
        valid_until.isoformat(),
    )


def _validate_problem_limits(problem: OptimizationProblem) -> None:
    for field_name, value in (
        ("minimum_cash_weight", problem.minimum_cash_weight),
        ("target_cash_weight", problem.target_cash_weight),
        ("maximum_turnover", problem.maximum_turnover),
        ("maximum_transaction_cost", problem.maximum_transaction_cost),
        ("maximum_drawdown", problem.maximum_drawdown),
    ):
        _require_finite(value, field_name)
        if not Decimal("0") <= value <= Decimal("1"):
            raise ValueError(f"{field_name} must be within [0, 1]")
    if problem.target_cash_weight < problem.minimum_cash_weight:
        raise ValueError("target_cash_weight cannot breach the cash requirement")


def _validate_asset_constraints(
    assets: tuple[AssetOptimizationConstraint, ...],
) -> None:
    for asset in assets:
        for field_name, value in (
            ("current_weight", asset.current_weight),
            ("expected_return", asset.expected_return),
            ("minimum_weight", asset.minimum_weight),
            ("maximum_weight", asset.maximum_weight),
            ("maximum_trade_weight", asset.maximum_trade_weight),
            ("transaction_cost_rate", asset.transaction_cost_rate),
            ("drawdown_loss", asset.drawdown_loss),
        ):
            _require_finite(value, field_name)
        if not Decimal("0") <= asset.current_weight <= Decimal("1"):
            raise ValueError("asset current_weight must be within [0, 1]")
        if not Decimal("0") <= asset.minimum_weight <= asset.maximum_weight <= Decimal("1"):
            raise ValueError("asset weight bounds must be ordered within [0, 1]")
        if not Decimal("0") <= asset.maximum_trade_weight <= Decimal("1"):
            raise ValueError("asset maximum_trade_weight must be within [0, 1]")
        if asset.transaction_cost_rate < 0 or asset.drawdown_loss < 0:
            raise ValueError("asset cost and drawdown inputs cannot be negative")
        if not isinstance(asset.manual_restriction, ManualRestriction):
            raise ValueError("asset manual_restriction is invalid")


def _validate_current_weights(problem: OptimizationProblem) -> None:
    total_value = problem.canonical_snapshot.cash_balance + sum(
        (position.market_value_base for position in problem.canonical_snapshot.positions),
        start=Decimal("0"),
    )
    if total_value <= 0:
        raise ValueError("canonical snapshot total value must be positive")
    positions = {position.asset_code: position for position in problem.canonical_snapshot.positions}
    for asset in problem.assets:
        expected = positions[asset.asset_code].market_value_base / total_value
        if asset.current_weight != expected:
            raise ValueError("asset current_weight does not match canonical snapshot")


def _validate_evidence_bindings(problem: OptimizationProblem) -> None:
    kinds = tuple(binding.kind for binding in problem.evidence_bindings)
    if len(kinds) != len(set(kinds)) or set(kinds) != REQUIRED_OPTIMIZATION_INPUTS:
        raise ValueError("optimization problem requires every canonical input binding exactly once")
    if any(binding.universe_hash != problem.universe_hash for binding in problem.evidence_bindings):
        raise ValueError("optimization evidence universe_hash mismatch")
    by_kind = _binding_by_kind(problem)
    if by_kind[OptimizationInputKind.ASSET_COVARIANCE].content_hash != (
        problem.covariance.content_hash
    ):
        raise ValueError("covariance evidence binding hash mismatch")
    if by_kind[OptimizationInputKind.EXECUTION_FEEDBACK].content_hash != (
        problem.execution_feedback_hash
    ):
        raise ValueError("execution feedback evidence binding hash mismatch")


def _binding_by_kind(
    problem: OptimizationProblem,
) -> dict[OptimizationInputKind, OptimizationEvidenceBinding]:
    return {binding.kind: binding for binding in problem.evidence_bindings}


def _validate_promotions(promotions: tuple[PromotionReference, ...]) -> None:
    keys = tuple(item.capability_key for item in promotions)
    if len(keys) != len(set(keys)) or set(keys) != REQUIRED_UPSTREAM_PROMOTIONS:
        raise ValueError("optimization problem requires exact R3/R4/R5 promotions")


def _hash_components(*components: str) -> str:
    digest = hashlib.sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def _require_token(value: str, field_name: str) -> None:
    if not value or len(value) > 160 or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_text(value: str, field_name: str) -> None:
    if not value.strip() or len(value) > 512:
        raise ValueError(f"{field_name} must be bounded non-blank text")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
