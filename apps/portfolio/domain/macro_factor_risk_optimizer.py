"""Deterministic, research-only construction of the R4 candidate family.

The module owns no persistence and accepts no caller-provided optimized weights.
Every candidate is derived from one sealed exposure/covariance/constraint snapshot.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from apps.portfolio.domain.macro_factor_risk import (
    AssetAllocation,
    FactorCovarianceVersion,
    MacroExposureVersion,
    MacroRiskBlockerCode,
    MacroRiskCandidateInput,
    MacroRiskCandidateKind,
    MacroRiskCandidateReport,
    MacroRiskValidationPolicy,
    build_macro_risk_input_hash,
    evaluate_macro_risk_candidate,
)
from apps.portfolio.domain.r4_rolling_evidence import R4AssetCovarianceEvidence


def _require_text(value: str, field_name: str, *, maximum: int = 160) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_utc(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field_name} must be UTC")


def _require_hash(value: str, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be a sha256 digest")
    if any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class MacroRiskSolverMethod(StrEnum):
    """Versioned deterministic method supported by this research slice."""

    DETERMINISTIC_COORDINATE_TRANSFER = "deterministic_coordinate_transfer"


class MacroRiskOptimizationStatus(StrEnum):
    """Fail-closed family construction status."""

    READY = "ready"
    BLOCKED = "blocked"


class MacroRiskOptimizationBlockerCode(StrEnum):
    """Stable reasons why a complete three-method family was not produced."""

    SOURCE_NOT_ACTIVE = "source_not_active"
    POLICY_NOT_ACTIVE = "policy_not_active"
    COVARIANCE_NOT_SYMMETRIC = "covariance_not_symmetric"
    FACTOR_COVARIANCE_NOT_PSD = "factor_covariance_not_psd"
    FACTOR_COVARIANCE_RANK_DEFICIENT = "factor_covariance_rank_deficient"
    ASSET_COVARIANCE_NOT_PSD = "asset_covariance_not_psd"
    ASSET_COVARIANCE_RANK_DEFICIENT = "asset_covariance_rank_deficient"
    WEIGHT_BOUNDS_CONFLICT = "weight_bounds_conflict"
    TURNOVER_CONFLICT = "turnover_conflict"
    LIQUIDITY_CONFLICT = "liquidity_conflict"
    COST_CONFLICT = "cost_conflict"
    ASSET_RISK_PARITY_NOT_CONVERGED = "asset_risk_parity_not_converged"
    MACRO_RISK_PARITY_NOT_CONVERGED = "macro_risk_parity_not_converged"
    CANDIDATE_VALIDATION_FAILED = "candidate_validation_failed"


@dataclass(frozen=True)
class MacroRiskAssetConstraint:
    """Current weight, hard bounds, liquidity, and linear cost for one asset."""

    asset_code: str
    current_weight: Decimal
    minimum_weight: Decimal
    maximum_weight: Decimal
    maximum_trade_weight: Decimal
    transaction_cost_rate: Decimal

    def __post_init__(self) -> None:
        _require_text(self.asset_code, "asset_code", maximum=80)
        for field_name, value in (
            ("current_weight", self.current_weight),
            ("minimum_weight", self.minimum_weight),
            ("maximum_weight", self.maximum_weight),
            ("maximum_trade_weight", self.maximum_trade_weight),
            ("transaction_cost_rate", self.transaction_cost_rate),
        ):
            _require_decimal(value, field_name)
        if not Decimal("0") <= self.current_weight <= Decimal("1"):
            raise ValueError("current_weight must be within [0, 1]")
        if not Decimal("0") <= self.minimum_weight <= self.maximum_weight <= Decimal("1"):
            raise ValueError("weight bounds must be ordered within [0, 1]")
        if self.maximum_trade_weight < 0:
            raise ValueError("maximum_trade_weight cannot be negative")
        if self.transaction_cost_rate < 0:
            raise ValueError("transaction_cost_rate cannot be negative")


def _exposure_payload(exposure: MacroExposureVersion) -> dict[str, object]:
    return {
        "version_id": exposure.version_id,
        "promoted_factor_version": exposure.promoted_factor_version,
        "promotion_decision_id": exposure.promotion_decision_id,
        "pit_manifest_id": exposure.pit_manifest_id,
        "code_version": exposure.code_version,
        "parameter_version": exposure.parameter_version,
        "observed_at": _time_text(exposure.observed_at),
        "valid_until": _time_text(exposure.valid_until),
        "exposures": [
            {
                "asset_code": item.asset_code,
                "residual_variance": _decimal_text(item.residual_variance),
                "r_squared": _decimal_text(item.r_squared),
                "stability_score": _decimal_text(item.stability_score),
                "betas": [
                    {
                        "factor_code": beta.factor_code,
                        "beta": _decimal_text(beta.beta),
                        "confidence_low": _decimal_text(beta.confidence_low),
                        "confidence_high": _decimal_text(beta.confidence_high),
                    }
                    for beta in item.betas
                ],
            }
            for item in exposure.exposures
        ],
    }


def _factor_covariance_payload(covariance: FactorCovarianceVersion) -> dict[str, object]:
    return {
        "version_id": covariance.version_id,
        "factor_codes": list(covariance.factor_codes),
        "values": [[_decimal_text(value) for value in row] for row in covariance.values],
        "pit_manifest_id": covariance.pit_manifest_id,
        "estimator_version": covariance.estimator_version,
        "observed_at": _time_text(covariance.observed_at),
        "valid_until": _time_text(covariance.valid_until),
    }


def _source_hash(
    *,
    source_id: str,
    source_version: str,
    canonical_portfolio_snapshot_id: str,
    exposure_version: MacroExposureVersion,
    factor_covariance_version: FactorCovarianceVersion,
    asset_covariance: R4AssetCovarianceEvidence,
    cost_model_version: str,
    constraint_version: str,
    constraints: tuple[MacroRiskAssetConstraint, ...],
    selection_as_of: datetime,
    valid_until: datetime,
) -> str:
    return _digest(
        {
            "schema": "r4-macro-risk-candidate-family-source.v1",
            "source_id": source_id,
            "source_version": source_version,
            "canonical_portfolio_snapshot_id": canonical_portfolio_snapshot_id,
            "exposure_version": _exposure_payload(exposure_version),
            "factor_covariance_version": _factor_covariance_payload(factor_covariance_version),
            "asset_covariance_hash": asset_covariance.content_hash.lower(),
            "cost_model_version": cost_model_version,
            "constraint_version": constraint_version,
            "constraints": [
                {
                    "asset_code": item.asset_code,
                    "current_weight": _decimal_text(item.current_weight),
                    "minimum_weight": _decimal_text(item.minimum_weight),
                    "maximum_weight": _decimal_text(item.maximum_weight),
                    "maximum_trade_weight": _decimal_text(item.maximum_trade_weight),
                    "transaction_cost_rate": _decimal_text(item.transaction_cost_rate),
                }
                for item in constraints
            ],
            "selection_as_of": _time_text(selection_as_of),
            "valid_until": _time_text(valid_until),
        }
    )


@dataclass(frozen=True)
class MacroRiskCandidateFamilySource:
    """Full sealed evidence from which all three candidates must be computed."""

    source_id: str
    source_version: str
    canonical_portfolio_snapshot_id: str
    exposure_version: MacroExposureVersion
    factor_covariance_version: FactorCovarianceVersion
    asset_covariance: R4AssetCovarianceEvidence
    cost_model_version: str
    constraint_version: str
    constraints: tuple[MacroRiskAssetConstraint, ...]
    selection_as_of: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        source_version: str,
        canonical_portfolio_snapshot_id: str,
        exposure_version: MacroExposureVersion,
        factor_covariance_version: FactorCovarianceVersion,
        asset_covariance: R4AssetCovarianceEvidence,
        cost_model_version: str,
        constraint_version: str,
        constraints: tuple[MacroRiskAssetConstraint, ...],
        selection_as_of: datetime,
        valid_until: datetime,
    ) -> MacroRiskCandidateFamilySource:
        """Create and canonically seal one complete optimizer source."""

        digest = _source_hash(
            source_id=source_id,
            source_version=source_version,
            canonical_portfolio_snapshot_id=canonical_portfolio_snapshot_id,
            exposure_version=exposure_version,
            factor_covariance_version=factor_covariance_version,
            asset_covariance=asset_covariance,
            cost_model_version=cost_model_version,
            constraint_version=constraint_version,
            constraints=constraints,
            selection_as_of=selection_as_of,
            valid_until=valid_until,
        )
        return cls(
            source_id=source_id,
            source_version=source_version,
            canonical_portfolio_snapshot_id=canonical_portfolio_snapshot_id,
            exposure_version=exposure_version,
            factor_covariance_version=factor_covariance_version,
            asset_covariance=asset_covariance,
            cost_model_version=cost_model_version,
            constraint_version=constraint_version,
            constraints=constraints,
            selection_as_of=selection_as_of,
            valid_until=valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("canonical_portfolio_snapshot_id", self.canonical_portfolio_snapshot_id),
            ("cost_model_version", self.cost_model_version),
            ("constraint_version", self.constraint_version),
        ):
            _require_text(value, field_name)
        _require_utc(self.selection_as_of, "selection_as_of")
        _require_utc(self.valid_until, "valid_until")
        if self.valid_until <= self.selection_as_of:
            raise ValueError("valid_until must follow selection_as_of")
        if type(self.exposure_version) is not MacroExposureVersion:  # noqa: E721
            raise ValueError("exposure_version must be the exact domain type")
        if type(self.factor_covariance_version) is not FactorCovarianceVersion:  # noqa: E721
            raise ValueError("factor_covariance_version must be the exact domain type")
        if type(self.asset_covariance) is not R4AssetCovarianceEvidence:  # noqa: E721
            raise ValueError("asset_covariance must be the exact domain type")
        if not self.constraints or any(
            type(item) is not MacroRiskAssetConstraint for item in self.constraints
        ):
            raise ValueError("constraints cannot be empty")
        asset_codes = tuple(item.asset_code for item in self.constraints)
        if asset_codes != tuple(sorted(set(asset_codes))):
            raise ValueError("constraint assets must be unique and canonically ordered")
        exposure_assets = tuple(item.asset_code for item in self.exposure_version.exposures)
        if exposure_assets != asset_codes or self.asset_covariance.asset_codes != asset_codes:
            raise ValueError("exposure, asset covariance, and constraints must share asset order")
        if self.exposure_version.factor_codes != self.factor_covariance_version.factor_codes:
            raise ValueError("exposure and factor covariance must share factor order")
        if self.exposure_version.pit_manifest_id != self.factor_covariance_version.pit_manifest_id:
            raise ValueError("exposure and factor covariance must share PIT manifest")
        if (
            self.exposure_version.observed_at > self.selection_as_of
            or self.factor_covariance_version.observed_at > self.selection_as_of
            or self.asset_covariance.knowledge_as_of > self.selection_as_of
        ):
            raise ValueError("source cannot include evidence unknown at selection_as_of")
        _require_hash(self.content_hash, "content_hash")
        expected = _source_hash(
            source_id=self.source_id,
            source_version=self.source_version,
            canonical_portfolio_snapshot_id=self.canonical_portfolio_snapshot_id,
            exposure_version=self.exposure_version,
            factor_covariance_version=self.factor_covariance_version,
            asset_covariance=self.asset_covariance,
            cost_model_version=self.cost_model_version,
            constraint_version=self.constraint_version,
            constraints=self.constraints,
            selection_as_of=self.selection_as_of,
            valid_until=self.valid_until,
        )
        if self.content_hash.lower() != expected:
            raise ValueError("source content_hash mismatch")


def _validation_policy_payload(policy: MacroRiskValidationPolicy) -> dict[str, str]:
    return {
        "version": policy.version,
        "weight_sum_tolerance": _decimal_text(policy.weight_sum_tolerance),
        "covariance_symmetry_tolerance": _decimal_text(policy.covariance_symmetry_tolerance),
        "covariance_psd_tolerance": _decimal_text(policy.covariance_psd_tolerance),
        "contribution_identity_tolerance": _decimal_text(policy.contribution_identity_tolerance),
        "minimum_r_squared": _decimal_text(policy.minimum_r_squared),
        "minimum_stability_score": _decimal_text(policy.minimum_stability_score),
        "maximum_turnover": _decimal_text(policy.maximum_turnover),
        "maximum_expected_cost": _decimal_text(policy.maximum_expected_cost),
        "macro_risk_parity_tolerance": _decimal_text(policy.macro_risk_parity_tolerance),
    }


def _policy_hash(
    *,
    policy_id: str,
    policy_version: str,
    method: MacroRiskSolverMethod,
    method_version: str,
    tolerance: Decimal,
    max_iterations: int,
    validation_policy: MacroRiskValidationPolicy,
    activated_at: datetime,
    valid_until: datetime,
) -> str:
    return _digest(
        {
            "schema": "r4-macro-risk-solver-policy.v1",
            "policy_id": policy_id,
            "policy_version": policy_version,
            "method": method.value,
            "method_version": method_version,
            "tolerance": _decimal_text(tolerance),
            "max_iterations": max_iterations,
            "validation_policy": _validation_policy_payload(validation_policy),
            "activated_at": _time_text(activated_at),
            "valid_until": _time_text(valid_until),
        }
    )


@dataclass(frozen=True)
class MacroRiskSolverPolicy:
    """Sealed solver identity, convergence policy, and validation thresholds."""

    policy_id: str
    policy_version: str
    method: MacroRiskSolverMethod
    method_version: str
    tolerance: Decimal
    max_iterations: int
    validation_policy: MacroRiskValidationPolicy
    activated_at: datetime
    valid_until: datetime
    policy_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        method: MacroRiskSolverMethod,
        method_version: str,
        tolerance: Decimal,
        max_iterations: int,
        validation_policy: MacroRiskValidationPolicy,
        activated_at: datetime,
        valid_until: datetime,
    ) -> MacroRiskSolverPolicy:
        """Create and canonically seal one explicit solver policy."""

        if type(max_iterations) is not int:  # noqa: E721 - exact built-in contract
            raise ValueError("max_iterations must be an exact built-in integer")
        digest = _policy_hash(
            policy_id=policy_id,
            policy_version=policy_version,
            method=method,
            method_version=method_version,
            tolerance=tolerance,
            max_iterations=max_iterations,
            validation_policy=validation_policy,
            activated_at=activated_at,
            valid_until=valid_until,
        )
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            method=method,
            method_version=method_version,
            tolerance=tolerance,
            max_iterations=max_iterations,
            validation_policy=validation_policy,
            activated_at=activated_at,
            valid_until=valid_until,
            policy_hash=digest,
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("method_version", self.method_version),
        ):
            _require_text(value, field_name)
        if not isinstance(self.method, MacroRiskSolverMethod):
            raise ValueError("method is invalid")
        if type(self.validation_policy) is not MacroRiskValidationPolicy:  # noqa: E721
            raise ValueError("validation_policy must be the exact domain type")
        _require_decimal(self.tolerance, "tolerance")
        if self.tolerance <= 0:
            raise ValueError("tolerance must be positive")
        if type(self.max_iterations) is not int:  # noqa: E721 - exact built-in contract
            raise ValueError("max_iterations must be an exact built-in integer")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.tolerance > self.validation_policy.macro_risk_parity_tolerance:
            raise ValueError("solver tolerance cannot exceed macro risk validation tolerance")
        _require_utc(self.activated_at, "activated_at")
        _require_utc(self.valid_until, "valid_until")
        if self.valid_until <= self.activated_at:
            raise ValueError("valid_until must follow activated_at")
        _require_hash(self.policy_hash, "policy_hash")
        expected = _policy_hash(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            method=self.method,
            method_version=self.method_version,
            tolerance=self.tolerance,
            max_iterations=self.max_iterations,
            validation_policy=self.validation_policy,
            activated_at=self.activated_at,
            valid_until=self.valid_until,
        )
        if self.policy_hash.lower() != expected:
            raise ValueError("policy_hash mismatch")


@dataclass(frozen=True)
class MacroRiskOptimizationBlocker:
    """One stable family-level fail-closed reason."""

    code: MacroRiskOptimizationBlockerCode
    detail: str


@dataclass(frozen=True)
class MacroRiskCandidateSolution:
    """One server-computed research candidate and its validation evidence."""

    candidate: MacroRiskCandidateInput
    report: MacroRiskCandidateReport
    iterations: int
    convergence_error: Decimal
    usage_scope: str = "research_only"
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if type(self.iterations) is not int or self.iterations < 0:  # noqa: E721
            raise ValueError("iterations must be a non-negative exact built-in integer")
        _require_decimal(self.convergence_error, "convergence_error")
        if self.convergence_error < 0:
            raise ValueError("convergence_error cannot be negative")
        if self.usage_scope != "research_only":
            raise ValueError("candidate solutions must remain research_only")
        if not self.must_not_use_for_decision or not self.must_not_execute:
            raise ValueError("candidate solutions cannot authorize decisions or execution")


def _result_hash(
    *,
    source_hash: str,
    policy_hash: str,
    status: MacroRiskOptimizationStatus,
    solutions: tuple[MacroRiskCandidateSolution, ...],
    blockers: tuple[MacroRiskOptimizationBlocker, ...],
    evaluated_at: datetime,
) -> str:
    return _digest(
        {
            "schema": "r4-macro-risk-candidate-family-result.v1",
            "source_hash": source_hash.lower(),
            "policy_hash": policy_hash.lower(),
            "status": status.value,
            "solutions": [
                {
                    "kind": item.candidate.kind.value,
                    "input_hash": item.candidate.input_hash.lower(),
                    "report_hash": item.report.evidence_hash.lower(),
                    "iterations": item.iterations,
                    "convergence_error": _decimal_text(item.convergence_error),
                }
                for item in solutions
            ],
            "blockers": [{"code": item.code.value, "detail": item.detail} for item in blockers],
            "evaluated_at": _time_text(evaluated_at),
            "usage_scope": "research_only",
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }
    )


@dataclass(frozen=True)
class MacroRiskCandidateFamilyResult:
    """Sealed outcome for exactly one source and one solver policy."""

    source_hash: str
    policy_hash: str
    status: MacroRiskOptimizationStatus
    solutions: tuple[MacroRiskCandidateSolution, ...]
    blockers: tuple[MacroRiskOptimizationBlocker, ...]
    evaluated_at: datetime
    content_hash: str
    usage_scope: str = "research_only"
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        _require_hash(self.source_hash, "source_hash")
        _require_hash(self.policy_hash, "policy_hash")
        _require_hash(self.content_hash, "content_hash")
        _require_utc(self.evaluated_at, "evaluated_at")
        if self.status is MacroRiskOptimizationStatus.READY:
            if len(self.solutions) != 3 or self.blockers:
                raise ValueError("ready family requires exactly three unblocked solutions")
        elif not self.blockers:
            raise ValueError("blocked family requires at least one blocker")
        if self.usage_scope != "research_only":
            raise ValueError("candidate families must remain research_only")
        if not self.must_not_use_for_decision or not self.must_not_execute:
            raise ValueError("candidate families cannot authorize decisions or execution")
        expected = _result_hash(
            source_hash=self.source_hash,
            policy_hash=self.policy_hash,
            status=self.status,
            solutions=self.solutions,
            blockers=self.blockers,
            evaluated_at=self.evaluated_at,
        )
        if self.content_hash.lower() != expected:
            raise ValueError("candidate family content_hash mismatch")


def _is_symmetric(matrix: tuple[tuple[Decimal, ...], ...], tolerance: Decimal) -> bool:
    return all(
        abs(matrix[row][column] - matrix[column][row]) <= tolerance
        for row in range(len(matrix))
        for column in range(row + 1, len(matrix))
    )


def _is_psd(matrix: tuple[tuple[Decimal, ...], ...], tolerance: Decimal) -> bool:
    size = len(matrix)
    factor = [[Decimal("0") for _ in range(size)] for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            value = matrix[row][column] - sum(
                factor[row][index] * factor[column][index] for index in range(column)
            )
            if row == column:
                if value < -tolerance:
                    return False
                factor[row][column] = Decimal("0") if abs(value) <= tolerance else value.sqrt()
            elif abs(factor[column][column]) <= tolerance:
                if abs(value) > tolerance:
                    return False
            else:
                factor[row][column] = value / factor[column][column]
    return True


def _matrix_rank(matrix: tuple[tuple[Decimal, ...], ...], tolerance: Decimal) -> int:
    work = [list(row) for row in matrix]
    row_count = len(work)
    column_count = len(work[0])
    pivot_row = 0
    for column in range(column_count):
        candidate = max(
            range(pivot_row, row_count), key=lambda row: abs(work[row][column]), default=pivot_row
        )
        if pivot_row >= row_count or abs(work[candidate][column]) <= tolerance:
            continue
        work[pivot_row], work[candidate] = work[candidate], work[pivot_row]
        pivot = work[pivot_row][column]
        work[pivot_row] = [value / pivot for value in work[pivot_row]]
        for row in range(row_count):
            if row == pivot_row:
                continue
            multiplier = work[row][column]
            work[row] = [
                value - multiplier * pivot_value
                for value, pivot_value in zip(work[row], work[pivot_row], strict=True)
            ]
        pivot_row += 1
        if pivot_row == row_count:
            break
    return pivot_row


def _risk_parity_error(
    weights: tuple[Decimal, ...],
    covariance: tuple[tuple[Decimal, ...], ...],
    tolerance: Decimal,
) -> Decimal | None:
    marginal = tuple(
        sum(row[column] * weights[column] for column in range(len(weights))) for row in covariance
    )
    contributions = tuple(weights[index] * marginal[index] for index in range(len(weights)))
    total = sum(contributions, Decimal("0"))
    if total <= tolerance or any(value < -tolerance for value in contributions):
        return None
    target = Decimal("1") / Decimal(len(weights))
    return max(abs(value / total - target) for value in contributions)


def _macro_risk_parity_error(
    weights: tuple[Decimal, ...],
    source: MacroRiskCandidateFamilySource,
    tolerance: Decimal,
) -> Decimal | None:
    """Return factor-contribution, not asset-contribution, parity error."""

    betas = tuple(
        tuple(beta.beta for beta in exposure.betas)
        for exposure in source.exposure_version.exposures
    )
    factor_covariance = source.factor_covariance_version.values
    factor_count = len(factor_covariance)
    portfolio_exposures = tuple(
        sum(
            (
                weights[asset_index] * betas[asset_index][factor_index]
                for asset_index in range(len(weights))
            ),
            Decimal("0"),
        )
        for factor_index in range(factor_count)
    )
    marginal = tuple(
        sum(
            (
                factor_covariance[row][column] * portfolio_exposures[column]
                for column in range(factor_count)
            ),
            Decimal("0"),
        )
        for row in range(factor_count)
    )
    contributions = tuple(
        portfolio_exposures[index] * marginal[index] for index in range(factor_count)
    )
    total = sum(contributions, Decimal("0"))
    if total <= tolerance or any(value < -tolerance for value in contributions):
        return None
    target = Decimal("1") / Decimal(factor_count)
    errors = tuple(abs(value / total - target) for value in contributions)
    return max(errors)


def _solve_risk_parity(
    *,
    covariance: tuple[tuple[Decimal, ...], ...],
    lower_bounds: tuple[Decimal, ...],
    upper_bounds: tuple[Decimal, ...],
    constraints: tuple[MacroRiskAssetConstraint, ...],
    policy: MacroRiskSolverPolicy,
    macro_source: MacroRiskCandidateFamilySource | None = None,
) -> tuple[tuple[Decimal, ...], int, Decimal | None, bool, bool]:
    size = len(lower_bounds)
    weights = tuple(Decimal("1") / Decimal(size) for _ in range(size))
    step = Decimal("1") / (Decimal("2") * Decimal(size))
    iterations = 0
    turnover_conflict = False
    cost_conflict = False
    error = (
        _macro_risk_parity_error(weights, macro_source, policy.tolerance)
        if macro_source is not None
        else _risk_parity_error(weights, covariance, policy.tolerance)
    )
    while iterations < policy.max_iterations and (error is None or error > policy.tolerance):
        best_weights = weights
        best_error = error
        for source_index in range(size):
            for target_index in range(size):
                if source_index == target_index:
                    continue
                transfer = min(
                    step,
                    weights[source_index] - lower_bounds[source_index],
                    upper_bounds[target_index] - weights[target_index],
                )
                if transfer <= 0:
                    continue
                trial = list(weights)
                trial[source_index] -= transfer
                trial[target_index] += transfer
                trial_tuple = tuple(trial)
                trial_turnover = sum(
                    abs(weight - constraint.current_weight)
                    for constraint, weight in zip(constraints, trial_tuple, strict=True)
                )
                if trial_turnover > policy.validation_policy.maximum_turnover:
                    turnover_conflict = True
                    continue
                trial_cost = sum(
                    abs(weight - constraint.current_weight) * constraint.transaction_cost_rate
                    for constraint, weight in zip(constraints, trial_tuple, strict=True)
                )
                if trial_cost > policy.validation_policy.maximum_expected_cost:
                    cost_conflict = True
                    continue
                trial_error = (
                    _macro_risk_parity_error(trial_tuple, macro_source, policy.tolerance)
                    if macro_source is not None
                    else _risk_parity_error(trial_tuple, covariance, policy.tolerance)
                )
                if trial_error is None:
                    continue
                if best_error is None or trial_error < best_error:
                    best_weights = trial_tuple
                    best_error = trial_error
        if best_weights == weights:
            step /= Decimal("2")
        else:
            weights = best_weights
            error = best_error
        iterations += 1
        if step <= policy.tolerance and best_weights == weights and error is not None:
            break
    return weights, iterations, error, turnover_conflict, cost_conflict


def _make_result(
    *,
    source: MacroRiskCandidateFamilySource,
    policy: MacroRiskSolverPolicy,
    status: MacroRiskOptimizationStatus,
    solutions: tuple[MacroRiskCandidateSolution, ...],
    blockers: tuple[MacroRiskOptimizationBlocker, ...],
    evaluated_at: datetime,
) -> MacroRiskCandidateFamilyResult:
    digest = _result_hash(
        source_hash=source.content_hash,
        policy_hash=policy.policy_hash,
        status=status,
        solutions=solutions,
        blockers=blockers,
        evaluated_at=evaluated_at,
    )
    return MacroRiskCandidateFamilyResult(
        source_hash=source.content_hash,
        policy_hash=policy.policy_hash,
        status=status,
        solutions=solutions,
        blockers=blockers,
        evaluated_at=evaluated_at,
        content_hash=digest,
    )


def _build_candidate(
    *,
    source: MacroRiskCandidateFamilySource,
    policy: MacroRiskSolverPolicy,
    kind: MacroRiskCandidateKind,
    weights: tuple[Decimal, ...],
    iterations: int,
    convergence_error: Decimal,
    evaluated_at: datetime,
) -> MacroRiskCandidateSolution:
    allocations = tuple(
        AssetAllocation(
            asset_code=constraint.asset_code,
            current_weight=constraint.current_weight,
            candidate_weight=weight,
            minimum_weight=constraint.minimum_weight,
            maximum_weight=constraint.maximum_weight,
            maximum_trade_weight=constraint.maximum_trade_weight,
        )
        for constraint, weight in zip(source.constraints, weights, strict=True)
    )
    expected_cost = sum(
        (
            abs(weight - constraint.current_weight) * constraint.transaction_cost_rate
            for constraint, weight in zip(source.constraints, weights, strict=True)
        ),
        Decimal("0"),
    )
    candidate_id = (
        f"{source.source_id}:{kind.value}:{source.content_hash[:12]}:{policy.policy_hash[:12]}"
    )
    input_hash = build_macro_risk_input_hash(
        candidate_id=candidate_id,
        kind=kind,
        canonical_portfolio_snapshot_id=source.canonical_portfolio_snapshot_id,
        exposure_version=source.exposure_version,
        covariance_version=source.factor_covariance_version,
        cost_model_version=source.cost_model_version,
        constraint_version=source.constraint_version,
        allocations=allocations,
        expected_cost=expected_cost,
        created_at=evaluated_at,
    )
    candidate = MacroRiskCandidateInput(
        candidate_id=candidate_id,
        kind=kind,
        canonical_portfolio_snapshot_id=source.canonical_portfolio_snapshot_id,
        exposure_version=source.exposure_version,
        covariance_version=source.factor_covariance_version,
        cost_model_version=source.cost_model_version,
        constraint_version=source.constraint_version,
        allocations=allocations,
        expected_cost=expected_cost,
        created_at=evaluated_at,
        input_hash=input_hash,
    )
    report = evaluate_macro_risk_candidate(
        candidate,
        policy=policy.validation_policy,
        evaluated_at=evaluated_at,
    )
    return MacroRiskCandidateSolution(
        candidate=candidate,
        report=report,
        iterations=iterations,
        convergence_error=convergence_error,
    )


def _map_report_blockers(
    solutions: tuple[MacroRiskCandidateSolution, ...],
) -> tuple[MacroRiskOptimizationBlocker, ...]:
    mapped: list[MacroRiskOptimizationBlocker] = []
    seen: set[MacroRiskOptimizationBlockerCode] = set()
    translations = {
        MacroRiskBlockerCode.WEIGHT_BOUND_BREACHED: MacroRiskOptimizationBlockerCode.WEIGHT_BOUNDS_CONFLICT,
        MacroRiskBlockerCode.WEIGHT_SUM_INVALID: MacroRiskOptimizationBlockerCode.WEIGHT_BOUNDS_CONFLICT,
        MacroRiskBlockerCode.TURNOVER_BREACHED: MacroRiskOptimizationBlockerCode.TURNOVER_CONFLICT,
        MacroRiskBlockerCode.LIQUIDITY_BREACHED: MacroRiskOptimizationBlockerCode.LIQUIDITY_CONFLICT,
        MacroRiskBlockerCode.COST_BUDGET_BREACHED: MacroRiskOptimizationBlockerCode.COST_CONFLICT,
    }
    for solution in solutions:
        for blocker in solution.report.blockers:
            code = translations.get(
                blocker.code, MacroRiskOptimizationBlockerCode.CANDIDATE_VALIDATION_FAILED
            )
            if code not in seen:
                mapped.append(
                    MacroRiskOptimizationBlocker(
                        code,
                        f"{solution.candidate.kind.value}: {blocker.code.value}",
                    )
                )
                seen.add(code)
    return tuple(mapped)


def build_macro_risk_candidate_family(
    *,
    source: MacroRiskCandidateFamilySource,
    policy: MacroRiskSolverPolicy,
    evaluated_at: datetime,
) -> MacroRiskCandidateFamilyResult:
    """Build equal-weight, asset-RP, and macro-factor-RP from one sealed source."""

    _require_utc(evaluated_at, "evaluated_at")
    if type(source) is not MacroRiskCandidateFamilySource:  # noqa: E721
        raise ValueError("source must be the exact MacroRiskCandidateFamilySource type")
    if type(policy) is not MacroRiskSolverPolicy:  # noqa: E721
        raise ValueError("policy must be the exact MacroRiskSolverPolicy type")
    MacroRiskCandidateFamilySource.__post_init__(source)
    MacroRiskSolverPolicy.__post_init__(policy)
    blockers: list[MacroRiskOptimizationBlocker] = []
    if not source.selection_as_of <= evaluated_at < source.valid_until:
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.SOURCE_NOT_ACTIVE,
                "source is not active at evaluated_at",
            )
        )
    if not policy.activated_at <= evaluated_at < policy.valid_until:
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.POLICY_NOT_ACTIVE,
                "solver policy is not active at evaluated_at",
            )
        )
    symmetry_tolerance = policy.validation_policy.covariance_symmetry_tolerance
    psd_tolerance = policy.validation_policy.covariance_psd_tolerance
    factor_covariance = source.factor_covariance_version.values
    asset_covariance = source.asset_covariance.values
    if not _is_symmetric(factor_covariance, symmetry_tolerance) or not _is_symmetric(
        asset_covariance, symmetry_tolerance
    ):
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.COVARIANCE_NOT_SYMMETRIC,
                "factor and asset covariance matrices must be symmetric",
            )
        )
    if not _is_psd(factor_covariance, psd_tolerance):
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.FACTOR_COVARIANCE_NOT_PSD,
                "factor covariance is not positive semidefinite",
            )
        )
    if _matrix_rank(factor_covariance, psd_tolerance) < len(factor_covariance):
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.FACTOR_COVARIANCE_RANK_DEFICIENT,
                "factor covariance is rank deficient",
            )
        )
    if not _is_psd(asset_covariance, psd_tolerance):
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.ASSET_COVARIANCE_NOT_PSD,
                "asset covariance is not positive semidefinite",
            )
        )
    if source.asset_covariance.matrix_rank < len(asset_covariance) or _matrix_rank(
        asset_covariance, psd_tolerance
    ) < len(asset_covariance):
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.ASSET_COVARIANCE_RANK_DEFICIENT,
                "asset covariance is rank deficient",
            )
        )
    base_lower = tuple(item.minimum_weight for item in source.constraints)
    base_upper = tuple(item.maximum_weight for item in source.constraints)
    base_feasible = not (sum(base_lower, Decimal("0")) > 1 or sum(base_upper, Decimal("0")) < 1)
    if not base_feasible:
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.WEIGHT_BOUNDS_CONFLICT,
                "weight bounds have no fully invested feasible point",
            )
        )
    lower_bounds = tuple(
        max(item.minimum_weight, item.current_weight - item.maximum_trade_weight)
        for item in source.constraints
    )
    upper_bounds = tuple(
        min(item.maximum_weight, item.current_weight + item.maximum_trade_weight)
        for item in source.constraints
    )
    liquidity_feasible = not (
        sum(lower_bounds, Decimal("0")) > 1 or sum(upper_bounds, Decimal("0")) < 1
    )
    if base_feasible and not liquidity_feasible:
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.LIQUIDITY_CONFLICT,
                "liquidity limits have no fully invested feasible point",
            )
        )
    equal_weight = Decimal("1") / Decimal(len(source.constraints))
    if base_feasible and any(
        equal_weight < low or equal_weight > high
        for low, high in zip(base_lower, base_upper, strict=True)
    ):
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.WEIGHT_BOUNDS_CONFLICT,
                "equal-weight baseline breaches a configured weight bound",
            )
        )
    elif (
        base_feasible
        and liquidity_feasible
        and any(
            equal_weight < low or equal_weight > high
            for low, high in zip(lower_bounds, upper_bounds, strict=True)
        )
    ):
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.LIQUIDITY_CONFLICT,
                "equal-weight baseline breaches a configured liquidity limit",
            )
        )
    equal_turnover = sum(abs(equal_weight - item.current_weight) for item in source.constraints)
    if equal_turnover > policy.validation_policy.maximum_turnover:
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.TURNOVER_CONFLICT,
                "equal-weight baseline breaches the turnover budget",
            )
        )
    equal_cost = sum(
        abs(equal_weight - item.current_weight) * item.transaction_cost_rate
        for item in source.constraints
    )
    if equal_cost > policy.validation_policy.maximum_expected_cost:
        blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.COST_CONFLICT,
                "equal-weight baseline breaches the cost budget",
            )
        )
    if blockers:
        unique = tuple(dict.fromkeys((item.code, item.detail) for item in blockers))
        normalized = tuple(MacroRiskOptimizationBlocker(code, detail) for code, detail in unique)
        return _make_result(
            source=source,
            policy=policy,
            status=MacroRiskOptimizationStatus.BLOCKED,
            solutions=(),
            blockers=normalized,
            evaluated_at=evaluated_at,
        )
    equal_weights = tuple(equal_weight for _ in source.constraints)
    (
        asset_weights,
        asset_iterations,
        asset_error,
        asset_turnover_conflict,
        asset_cost_conflict,
    ) = _solve_risk_parity(
        covariance=asset_covariance,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        constraints=source.constraints,
        policy=policy,
    )
    (
        macro_weights,
        macro_iterations,
        macro_error,
        macro_turnover_conflict,
        macro_cost_conflict,
    ) = _solve_risk_parity(
        covariance=asset_covariance,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        constraints=source.constraints,
        policy=policy,
        macro_source=source,
    )
    solver_blockers: list[MacroRiskOptimizationBlocker] = []
    asset_failed = asset_error is None or asset_error > policy.tolerance
    macro_failed = macro_error is None or macro_error > policy.tolerance
    if (asset_failed and asset_turnover_conflict) or (macro_failed and macro_turnover_conflict):
        solver_blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.TURNOVER_CONFLICT,
                "risk-parity improvement is outside the turnover budget",
            )
        )
    if (asset_failed and asset_cost_conflict) or (macro_failed and macro_cost_conflict):
        solver_blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.COST_CONFLICT,
                "risk-parity improvement is outside the cost budget",
            )
        )
    if asset_failed:
        solver_blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.ASSET_RISK_PARITY_NOT_CONVERGED,
                "asset risk contribution error exceeds solver tolerance",
            )
        )
    if macro_failed:
        solver_blockers.append(
            MacroRiskOptimizationBlocker(
                MacroRiskOptimizationBlockerCode.MACRO_RISK_PARITY_NOT_CONVERGED,
                "macro factor contribution error exceeds solver tolerance",
            )
        )
    if solver_blockers:
        return _make_result(
            source=source,
            policy=policy,
            status=MacroRiskOptimizationStatus.BLOCKED,
            solutions=(),
            blockers=tuple(solver_blockers),
            evaluated_at=evaluated_at,
        )
    if asset_error is None or macro_error is None:
        raise RuntimeError("converged solver must publish finite contribution errors")
    solutions = (
        _build_candidate(
            source=source,
            policy=policy,
            kind=MacroRiskCandidateKind.EQUAL_WEIGHT,
            weights=equal_weights,
            iterations=0,
            convergence_error=Decimal("0"),
            evaluated_at=evaluated_at,
        ),
        _build_candidate(
            source=source,
            policy=policy,
            kind=MacroRiskCandidateKind.ASSET_RISK_PARITY,
            weights=asset_weights,
            iterations=asset_iterations,
            convergence_error=asset_error,
            evaluated_at=evaluated_at,
        ),
        _build_candidate(
            source=source,
            policy=policy,
            kind=MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,
            weights=macro_weights,
            iterations=macro_iterations,
            convergence_error=macro_error,
            evaluated_at=evaluated_at,
        ),
    )
    report_blockers = _map_report_blockers(solutions)
    status = (
        MacroRiskOptimizationStatus.BLOCKED
        if report_blockers
        else MacroRiskOptimizationStatus.READY
    )
    return _make_result(
        source=source,
        policy=policy,
        status=status,
        solutions=solutions,
        blockers=report_blockers,
        evaluated_at=evaluated_at,
    )
