"""Pure R4 macro-factor risk decomposition and candidate validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum


def _require_text(value: str, field_name: str, *, maximum: int = 160) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


class MacroRiskCandidateKind(str, Enum):
    """Governed comparison family for one allocation candidate."""

    EQUAL_WEIGHT = "equal_weight"
    ASSET_RISK_PARITY = "asset_risk_parity"
    MACRO_FACTOR_RISK_PARITY = "macro_factor_risk_parity"


class MacroRiskBlockerCode(str, Enum):
    """Stable fail-closed reasons for R4 research evaluation."""

    EVIDENCE_EXPIRED = "evidence_expired"
    EVIDENCE_NOT_YET_OBSERVED = "evidence_not_yet_observed"
    ASSET_SET_MISMATCH = "asset_set_mismatch"
    FACTOR_SET_MISMATCH = "factor_set_mismatch"
    WEIGHT_SUM_INVALID = "weight_sum_invalid"
    WEIGHT_BOUND_BREACHED = "weight_bound_breached"
    TURNOVER_BREACHED = "turnover_breached"
    LIQUIDITY_BREACHED = "liquidity_breached"
    COST_BUDGET_BREACHED = "cost_budget_breached"
    EXPOSURE_QUALITY_LOW = "exposure_quality_low"
    COVARIANCE_NOT_SYMMETRIC = "covariance_not_symmetric"
    COVARIANCE_NOT_PSD = "covariance_not_psd"
    FACTOR_VARIANCE_NON_POSITIVE = "factor_variance_non_positive"
    NEGATIVE_FACTOR_CONTRIBUTION = "negative_factor_contribution"
    CONTRIBUTION_IDENTITY_FAILED = "contribution_identity_failed"
    RISK_PARITY_TARGET_MISSED = "risk_parity_target_missed"


@dataclass(frozen=True)
class MacroFactorBeta:
    """One versioned asset exposure with uncertainty bounds."""

    factor_code: str
    beta: Decimal
    confidence_low: Decimal
    confidence_high: Decimal

    def __post_init__(self) -> None:
        _require_text(self.factor_code, "factor_code", maximum=80)
        for name, value in (
            ("beta", self.beta),
            ("confidence_low", self.confidence_low),
            ("confidence_high", self.confidence_high),
        ):
            _require_finite(value, name)
        if self.confidence_low > self.beta or self.beta > self.confidence_high:
            raise ValueError("beta must lie inside its confidence interval")


@dataclass(frozen=True)
class AssetMacroExposure:
    """One asset's promoted rolling exposure diagnostics."""

    asset_code: str
    betas: tuple[MacroFactorBeta, ...]
    residual_variance: Decimal
    r_squared: Decimal
    stability_score: Decimal

    def __post_init__(self) -> None:
        _require_text(self.asset_code, "asset_code", maximum=80)
        if not self.betas:
            raise ValueError("asset exposure requires at least one factor beta")
        codes = tuple(beta.factor_code for beta in self.betas)
        if len(codes) != len(set(codes)):
            raise ValueError("factor betas must be unique per asset")
        for name, value in (
            ("residual_variance", self.residual_variance),
            ("r_squared", self.r_squared),
            ("stability_score", self.stability_score),
        ):
            _require_finite(value, name)
        if self.residual_variance < 0:
            raise ValueError("residual_variance cannot be negative")
        if not Decimal("0") <= self.r_squared <= Decimal("1"):
            raise ValueError("r_squared must be between zero and one")
        if not Decimal("0") <= self.stability_score <= Decimal("1"):
            raise ValueError("stability_score must be between zero and one")


@dataclass(frozen=True)
class MacroExposureVersion:
    """Immutable asset-by-factor exposure matrix produced from PIT evidence."""

    version_id: str
    promoted_factor_version: str
    promotion_decision_id: str
    pit_manifest_id: str
    code_version: str
    parameter_version: str
    observed_at: datetime
    valid_until: datetime
    exposures: tuple[AssetMacroExposure, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("version_id", self.version_id),
            ("promoted_factor_version", self.promoted_factor_version),
            ("promotion_decision_id", self.promotion_decision_id),
            ("pit_manifest_id", self.pit_manifest_id),
            ("code_version", self.code_version),
            ("parameter_version", self.parameter_version),
        ):
            _require_text(value, name)
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until <= self.observed_at:
            raise ValueError("valid_until must follow observed_at")
        if not self.exposures:
            raise ValueError("exposure version cannot be empty")
        assets = tuple(exposure.asset_code for exposure in self.exposures)
        if len(assets) != len(set(assets)):
            raise ValueError("asset exposures must be unique")
        factor_sets = {
            tuple(beta.factor_code for beta in exposure.betas) for exposure in self.exposures
        }
        if len(factor_sets) != 1:
            raise ValueError("all assets must expose the same ordered factor set")

    @property
    def factor_codes(self) -> tuple[str, ...]:
        """Return the canonical ordered factor universe."""

        return tuple(beta.factor_code for beta in self.exposures[0].betas)


@dataclass(frozen=True)
class FactorCovarianceVersion:
    """Immutable factor covariance input with PIT and lineage references."""

    version_id: str
    factor_codes: tuple[str, ...]
    values: tuple[tuple[Decimal, ...], ...]
    pit_manifest_id: str
    estimator_version: str
    observed_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        _require_text(self.version_id, "version_id")
        _require_text(self.pit_manifest_id, "pit_manifest_id")
        _require_text(self.estimator_version, "estimator_version")
        _require_aware(self.observed_at, "observed_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until <= self.observed_at:
            raise ValueError("valid_until must follow observed_at")
        if not self.factor_codes or len(self.factor_codes) != len(set(self.factor_codes)):
            raise ValueError("factor_codes must be non-empty and unique")
        size = len(self.factor_codes)
        if len(self.values) != size or any(len(row) != size for row in self.values):
            raise ValueError("covariance values must be square")
        for row_index, row in enumerate(self.values):
            for column_index, value in enumerate(row):
                _require_finite(value, f"values[{row_index}][{column_index}]")


@dataclass(frozen=True)
class AssetAllocation:
    """Current or candidate portfolio weight and liquidity capacity."""

    asset_code: str
    current_weight: Decimal
    candidate_weight: Decimal
    minimum_weight: Decimal
    maximum_weight: Decimal
    maximum_trade_weight: Decimal

    def __post_init__(self) -> None:
        _require_text(self.asset_code, "asset_code", maximum=80)
        for name, value in (
            ("current_weight", self.current_weight),
            ("candidate_weight", self.candidate_weight),
            ("minimum_weight", self.minimum_weight),
            ("maximum_weight", self.maximum_weight),
            ("maximum_trade_weight", self.maximum_trade_weight),
        ):
            _require_finite(value, name)
        if self.minimum_weight > self.maximum_weight:
            raise ValueError("minimum_weight cannot exceed maximum_weight")
        if self.maximum_trade_weight < 0:
            raise ValueError("maximum_trade_weight cannot be negative")


@dataclass(frozen=True)
class MacroRiskCandidateInput:
    """Canonical, research-only R4 candidate input snapshot."""

    candidate_id: str
    kind: MacroRiskCandidateKind
    canonical_portfolio_snapshot_id: str
    exposure_version: MacroExposureVersion
    covariance_version: FactorCovarianceVersion
    cost_model_version: str
    constraint_version: str
    allocations: tuple[AssetAllocation, ...]
    expected_cost: Decimal
    created_at: datetime
    input_hash: str

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("canonical_portfolio_snapshot_id", self.canonical_portfolio_snapshot_id),
            ("cost_model_version", self.cost_model_version),
            ("constraint_version", self.constraint_version),
        ):
            _require_text(value, name)
        if not isinstance(self.kind, MacroRiskCandidateKind):
            raise ValueError("kind is invalid")
        if self.exposure_version.pit_manifest_id != self.covariance_version.pit_manifest_id:
            raise ValueError("exposure and covariance must use the same PIT manifest")
        _require_finite(self.expected_cost, "expected_cost")
        if self.expected_cost < 0:
            raise ValueError("expected_cost cannot be negative")
        _require_aware(self.created_at, "created_at")
        if (
            self.exposure_version.observed_at > self.created_at
            or self.covariance_version.observed_at > self.created_at
        ):
            raise ValueError("candidate cannot use evidence observed after creation")
        _require_sha256(self.input_hash, "input_hash")
        assets = tuple(allocation.asset_code for allocation in self.allocations)
        if not assets or len(assets) != len(set(assets)):
            raise ValueError("allocations must be non-empty and unique")


@dataclass(frozen=True)
class MacroRiskValidationPolicy:
    """Versioned numeric tolerances; no mutable threshold is hardcoded."""

    version: str
    weight_sum_tolerance: Decimal
    covariance_symmetry_tolerance: Decimal
    covariance_psd_tolerance: Decimal
    contribution_identity_tolerance: Decimal
    minimum_r_squared: Decimal
    minimum_stability_score: Decimal
    maximum_turnover: Decimal
    maximum_expected_cost: Decimal
    macro_risk_parity_tolerance: Decimal

    def __post_init__(self) -> None:
        _require_text(self.version, "version")
        for name, value in (
            ("weight_sum_tolerance", self.weight_sum_tolerance),
            ("covariance_symmetry_tolerance", self.covariance_symmetry_tolerance),
            ("covariance_psd_tolerance", self.covariance_psd_tolerance),
            ("contribution_identity_tolerance", self.contribution_identity_tolerance),
            ("minimum_r_squared", self.minimum_r_squared),
            ("minimum_stability_score", self.minimum_stability_score),
            ("maximum_turnover", self.maximum_turnover),
            ("maximum_expected_cost", self.maximum_expected_cost),
            ("macro_risk_parity_tolerance", self.macro_risk_parity_tolerance),
        ):
            _require_finite(value, name)
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.minimum_r_squared > 1 or self.minimum_stability_score > 1:
            raise ValueError("quality thresholds cannot exceed one")


@dataclass(frozen=True)
class MacroFactorRiskContribution:
    """Contribution of one named macro source to candidate variance."""

    factor_code: str
    portfolio_exposure: Decimal
    marginal_variance: Decimal
    variance_contribution: Decimal
    contribution_share: Decimal


@dataclass(frozen=True)
class MacroRiskBlocker:
    """One deterministic R4 blocker."""

    code: MacroRiskBlockerCode
    detail: str


@dataclass(frozen=True)
class MacroRiskCandidateReport:
    """Auditable R4 evaluation; it never authorizes execution."""

    candidate_id: str
    input_hash: str
    eligible_for_research_comparison: bool
    factor_variance: Decimal
    residual_variance: Decimal
    total_variance: Decimal
    turnover: Decimal
    contributions: tuple[MacroFactorRiskContribution, ...]
    blockers: tuple[MacroRiskBlocker, ...]
    evaluated_at: datetime
    policy_version: str
    evidence_hash: str
    usage_scope: str = "research_only"
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        """Reject a report whose sealed output was altered after evaluation."""

        _require_text(self.candidate_id, "candidate_id")
        _require_sha256(self.input_hash, "input_hash")
        _require_text(self.policy_version, "policy_version")
        _require_aware(self.evaluated_at, "evaluated_at")
        for name, value in (
            ("factor_variance", self.factor_variance),
            ("residual_variance", self.residual_variance),
            ("total_variance", self.total_variance),
            ("turnover", self.turnover),
        ):
            _require_finite(value, name)
        if self.usage_scope != "research_only":
            raise ValueError("macro-risk reports must remain research_only")
        if not self.must_not_use_for_decision or not self.must_not_execute:
            raise ValueError("macro-risk reports cannot authorize decisions or execution")
        expected_hash = build_macro_risk_report_hash(
            candidate_id=self.candidate_id,
            input_hash=self.input_hash,
            eligible_for_research_comparison=self.eligible_for_research_comparison,
            factor_variance=self.factor_variance,
            residual_variance=self.residual_variance,
            total_variance=self.total_variance,
            turnover=self.turnover,
            contributions=self.contributions,
            blockers=self.blockers,
            evaluated_at=self.evaluated_at,
            policy_version=self.policy_version,
            usage_scope=self.usage_scope,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )
        if self.evidence_hash.lower() != expected_hash:
            raise ValueError("evidence_hash does not match canonical macro-risk report")


def build_macro_risk_input_hash(
    *,
    candidate_id: str,
    kind: MacroRiskCandidateKind,
    canonical_portfolio_snapshot_id: str,
    exposure_version: MacroExposureVersion,
    covariance_version: FactorCovarianceVersion,
    cost_model_version: str,
    constraint_version: str,
    allocations: tuple[AssetAllocation, ...],
    expected_cost: Decimal,
    created_at: datetime,
) -> str:
    """Build the canonical digest required by ``MacroRiskCandidateInput``."""

    payload = {
        "candidate_id": candidate_id,
        "kind": kind.value,
        "canonical_portfolio_snapshot_id": canonical_portfolio_snapshot_id,
        "exposure_version": exposure_version.version_id,
        "promoted_factor_version": exposure_version.promoted_factor_version,
        "promotion_decision_id": exposure_version.promotion_decision_id,
        "pit_manifest_id": exposure_version.pit_manifest_id,
        "exposure_code_version": exposure_version.code_version,
        "exposure_parameter_version": exposure_version.parameter_version,
        "exposure_observed_at": exposure_version.observed_at.astimezone(UTC).isoformat(),
        "exposure_valid_until": exposure_version.valid_until.astimezone(UTC).isoformat(),
        "exposures": [
            {
                "asset_code": exposure.asset_code,
                "residual_variance": _decimal_text(exposure.residual_variance),
                "r_squared": _decimal_text(exposure.r_squared),
                "stability_score": _decimal_text(exposure.stability_score),
                "betas": [
                    {
                        "factor_code": beta.factor_code,
                        "beta": _decimal_text(beta.beta),
                        "confidence_low": _decimal_text(beta.confidence_low),
                        "confidence_high": _decimal_text(beta.confidence_high),
                    }
                    for beta in exposure.betas
                ],
            }
            for exposure in sorted(
                exposure_version.exposures,
                key=lambda item: item.asset_code,
            )
        ],
        "covariance_version": covariance_version.version_id,
        "covariance_factor_codes": list(covariance_version.factor_codes),
        "covariance_values": [
            [_decimal_text(value) for value in row] for row in covariance_version.values
        ],
        "covariance_estimator_version": covariance_version.estimator_version,
        "covariance_observed_at": covariance_version.observed_at.astimezone(UTC).isoformat(),
        "covariance_valid_until": covariance_version.valid_until.astimezone(UTC).isoformat(),
        "cost_model_version": cost_model_version,
        "constraint_version": constraint_version,
        "allocations": [
            {
                "asset_code": item.asset_code,
                "current_weight": _decimal_text(item.current_weight),
                "candidate_weight": _decimal_text(item.candidate_weight),
                "minimum_weight": _decimal_text(item.minimum_weight),
                "maximum_weight": _decimal_text(item.maximum_weight),
                "maximum_trade_weight": _decimal_text(item.maximum_trade_weight),
            }
            for item in sorted(allocations, key=lambda allocation: allocation.asset_code)
        ],
        "expected_cost": _decimal_text(expected_cost),
        "created_at": created_at.astimezone(UTC).isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_macro_risk_report_hash(
    *,
    candidate_id: str,
    input_hash: str,
    eligible_for_research_comparison: bool,
    factor_variance: Decimal,
    residual_variance: Decimal,
    total_variance: Decimal,
    turnover: Decimal,
    contributions: tuple[MacroFactorRiskContribution, ...],
    blockers: tuple[MacroRiskBlocker, ...],
    evaluated_at: datetime,
    policy_version: str,
    usage_scope: str,
    must_not_use_for_decision: bool,
    must_not_execute: bool,
) -> str:
    """Seal every decision-relevant field of one R4 candidate report."""

    payload = {
        "candidate_id": candidate_id,
        "input_hash": input_hash.lower(),
        "eligible_for_research_comparison": eligible_for_research_comparison,
        "factor_variance": _decimal_text(factor_variance),
        "residual_variance": _decimal_text(residual_variance),
        "total_variance": _decimal_text(total_variance),
        "turnover": _decimal_text(turnover),
        "contributions": [
            {
                "factor_code": item.factor_code,
                "portfolio_exposure": _decimal_text(item.portfolio_exposure),
                "marginal_variance": _decimal_text(item.marginal_variance),
                "variance_contribution": _decimal_text(item.variance_contribution),
                "contribution_share": _decimal_text(item.contribution_share),
            }
            for item in contributions
        ],
        "blockers": [
            {"code": item.code.value, "detail": item.detail}
            for item in sorted(blockers, key=lambda value: (value.code.value, value.detail))
        ],
        "evaluated_at": evaluated_at.astimezone(UTC).isoformat(),
        "policy_version": policy_version,
        "usage_scope": usage_scope,
        "must_not_use_for_decision": must_not_use_for_decision,
        "must_not_execute": must_not_execute,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def evaluate_macro_risk_candidate(
    candidate: MacroRiskCandidateInput,
    *,
    policy: MacroRiskValidationPolicy,
    evaluated_at: datetime,
) -> MacroRiskCandidateReport:
    """Validate one candidate and decompose variance into named macro sources."""

    _require_aware(evaluated_at, "evaluated_at")
    blockers: list[MacroRiskBlocker] = []
    expected_hash = build_macro_risk_input_hash(
        candidate_id=candidate.candidate_id,
        kind=candidate.kind,
        canonical_portfolio_snapshot_id=candidate.canonical_portfolio_snapshot_id,
        exposure_version=candidate.exposure_version,
        covariance_version=candidate.covariance_version,
        cost_model_version=candidate.cost_model_version,
        constraint_version=candidate.constraint_version,
        allocations=candidate.allocations,
        expected_cost=candidate.expected_cost,
        created_at=candidate.created_at,
    )
    if candidate.input_hash.lower() != expected_hash:
        raise ValueError("input_hash does not match canonical candidate content")

    exposure = candidate.exposure_version
    covariance = candidate.covariance_version
    if evaluated_at >= exposure.valid_until or evaluated_at >= covariance.valid_until:
        blockers.append(_block(MacroRiskBlockerCode.EVIDENCE_EXPIRED, "input evidence expired"))
    if (
        evaluated_at < exposure.observed_at
        or evaluated_at < covariance.observed_at
        or evaluated_at < candidate.created_at
    ):
        blockers.append(
            _block(
                MacroRiskBlockerCode.EVIDENCE_NOT_YET_OBSERVED,
                "input evidence is not yet observable",
            )
        )

    allocations = {item.asset_code: item for item in candidate.allocations}
    exposures = {item.asset_code: item for item in exposure.exposures}
    if set(allocations) != set(exposures):
        blockers.append(_block(MacroRiskBlockerCode.ASSET_SET_MISMATCH, "asset sets differ"))
    if exposure.factor_codes != covariance.factor_codes:
        blockers.append(_block(MacroRiskBlockerCode.FACTOR_SET_MISMATCH, "factor sets differ"))

    weight_sum = sum((item.candidate_weight for item in candidate.allocations), Decimal("0"))
    if abs(weight_sum - Decimal("1")) > policy.weight_sum_tolerance:
        blockers.append(
            _block(MacroRiskBlockerCode.WEIGHT_SUM_INVALID, "weights do not sum to one")
        )
    if any(
        item.candidate_weight < item.minimum_weight or item.candidate_weight > item.maximum_weight
        for item in candidate.allocations
    ):
        blockers.append(_block(MacroRiskBlockerCode.WEIGHT_BOUND_BREACHED, "weight bound breached"))
    if any(
        abs(item.candidate_weight - item.current_weight) > item.maximum_trade_weight
        for item in candidate.allocations
    ):
        blockers.append(_block(MacroRiskBlockerCode.LIQUIDITY_BREACHED, "trade capacity breached"))
    turnover = sum(
        (abs(item.candidate_weight - item.current_weight) for item in candidate.allocations),
        Decimal("0"),
    )
    if turnover > policy.maximum_turnover:
        blockers.append(_block(MacroRiskBlockerCode.TURNOVER_BREACHED, "turnover limit breached"))
    if candidate.expected_cost > policy.maximum_expected_cost:
        blockers.append(
            _block(
                MacroRiskBlockerCode.COST_BUDGET_BREACHED,
                "expected transaction cost budget breached",
            )
        )
    if any(
        item.r_squared < policy.minimum_r_squared
        or item.stability_score < policy.minimum_stability_score
        for item in exposure.exposures
    ):
        blockers.append(
            _block(MacroRiskBlockerCode.EXPOSURE_QUALITY_LOW, "exposure quality is low")
        )

    symmetric = _is_symmetric(covariance.values, policy.covariance_symmetry_tolerance)
    if not symmetric:
        blockers.append(
            _block(MacroRiskBlockerCode.COVARIANCE_NOT_SYMMETRIC, "covariance is not symmetric")
        )
    psd = symmetric and _is_positive_semidefinite(
        covariance.values,
        policy.covariance_psd_tolerance,
    )
    if not psd:
        blockers.append(_block(MacroRiskBlockerCode.COVARIANCE_NOT_PSD, "covariance is not PSD"))

    contributions: tuple[MacroFactorRiskContribution, ...] = ()
    factor_variance = Decimal("0")
    residual_variance = Decimal("0")
    if set(allocations) == set(exposures) and exposure.factor_codes == covariance.factor_codes:
        portfolio_exposure = tuple(
            sum(
                (
                    allocations[item.asset_code].candidate_weight * item.betas[index].beta
                    for item in exposure.exposures
                ),
                Decimal("0"),
            )
            for index in range(len(exposure.factor_codes))
        )
        marginal = _matrix_vector(covariance.values, portfolio_exposure)
        raw = tuple(
            portfolio_exposure[index] * marginal[index] for index in range(len(portfolio_exposure))
        )
        factor_variance = sum(raw, Decimal("0"))
        residual_variance = sum(
            (
                allocations[item.asset_code].candidate_weight
                * allocations[item.asset_code].candidate_weight
                * item.residual_variance
                for item in exposure.exposures
            ),
            Decimal("0"),
        )
        if factor_variance <= policy.covariance_psd_tolerance:
            blockers.append(
                _block(
                    MacroRiskBlockerCode.FACTOR_VARIANCE_NON_POSITIVE,
                    "factor variance is not positive",
                )
            )
        else:
            contributions = tuple(
                MacroFactorRiskContribution(
                    factor_code=code,
                    portfolio_exposure=portfolio_exposure[index],
                    marginal_variance=marginal[index],
                    variance_contribution=raw[index],
                    contribution_share=raw[index] / factor_variance,
                )
                for index, code in enumerate(exposure.factor_codes)
            )
            if candidate.kind is MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY and any(
                item.variance_contribution < 0 for item in contributions
            ):
                blockers.append(
                    _block(
                        MacroRiskBlockerCode.NEGATIVE_FACTOR_CONTRIBUTION,
                        "negative macro contribution cannot satisfy risk parity",
                    )
                )
            if candidate.kind is MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY:
                target = Decimal("1") / Decimal(len(contributions))
                if any(
                    abs(item.contribution_share - target) > policy.macro_risk_parity_tolerance
                    for item in contributions
                ):
                    blockers.append(
                        _block(
                            MacroRiskBlockerCode.RISK_PARITY_TARGET_MISSED,
                            "macro contribution target missed",
                        )
                    )

    total_variance = factor_variance + residual_variance
    if (
        contributions
        and abs(
            sum((item.variance_contribution for item in contributions), Decimal("0"))
            + residual_variance
            - total_variance
        )
        > policy.contribution_identity_tolerance
    ):
        blockers.append(
            _block(MacroRiskBlockerCode.CONTRIBUTION_IDENTITY_FAILED, "risk identity failed")
        )

    blocker_tuple = tuple(blockers)
    evidence_hash = build_macro_risk_report_hash(
        candidate_id=candidate.candidate_id,
        input_hash=candidate.input_hash,
        eligible_for_research_comparison=not blocker_tuple,
        factor_variance=factor_variance,
        residual_variance=residual_variance,
        total_variance=total_variance,
        turnover=turnover,
        contributions=contributions,
        blockers=blocker_tuple,
        evaluated_at=evaluated_at,
        policy_version=policy.version,
        usage_scope="research_only",
        must_not_use_for_decision=True,
        must_not_execute=True,
    )
    return MacroRiskCandidateReport(
        candidate_id=candidate.candidate_id,
        input_hash=candidate.input_hash,
        eligible_for_research_comparison=not blocker_tuple,
        factor_variance=factor_variance,
        residual_variance=residual_variance,
        total_variance=total_variance,
        turnover=turnover,
        contributions=contributions,
        blockers=blocker_tuple,
        evaluated_at=evaluated_at,
        policy_version=policy.version,
        evidence_hash=evidence_hash,
    )


def _block(code: MacroRiskBlockerCode, detail: str) -> MacroRiskBlocker:
    return MacroRiskBlocker(code=code, detail=detail)


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
            lower[row][index] * lower[row][index] * diagonal[index] for index in range(row)
        )
        if diagonal[row] < -tolerance:
            return False
        if abs(diagonal[row]) <= tolerance:
            diagonal[row] = Decimal("0")
        for below in range(row + 1, size):
            numerator = matrix[below][row] - sum(
                lower[below][index] * lower[row][index] * diagonal[index] for index in range(row)
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
        sum((value * vector[index] for index, value in enumerate(row)), Decimal("0"))
        for row in matrix
    )


__all__ = [
    "AssetAllocation",
    "AssetMacroExposure",
    "FactorCovarianceVersion",
    "MacroExposureVersion",
    "MacroFactorBeta",
    "MacroFactorRiskContribution",
    "MacroRiskBlocker",
    "MacroRiskBlockerCode",
    "MacroRiskCandidateInput",
    "MacroRiskCandidateKind",
    "MacroRiskCandidateReport",
    "MacroRiskValidationPolicy",
    "build_macro_risk_input_hash",
    "build_macro_risk_report_hash",
    "evaluate_macro_risk_candidate",
]
