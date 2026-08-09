"""Typed study and result contracts for rolling R4 macro-risk research."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from apps.portfolio.domain.macro_factor_risk import (
    MacroRiskCandidateInput,
    MacroRiskCandidateKind,
    MacroRiskValidationPolicy,
    build_macro_risk_input_hash,
)
from apps.portfolio.domain.r4_rolling_evidence import (
    ExactR3PromotionAttestation,
    R4AssetCovarianceEvidence,
    R4MacroExposureProjectionEvidence,
    R4OOSReturnPathEvidence,
    R4RegimeAssignmentEvidence,
)
from apps.portfolio.domain.r4_temporal_split import TemporalSplitSpec, WalkForwardFold


def _require_text(value: str, field_name: str, *, maximum: int = 300) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if "\0" in value:
        raise ValueError(f"{field_name} cannot contain a null character")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _hash_parts(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _candidate_content_hash(candidate: MacroRiskCandidateInput) -> str:
    return build_macro_risk_input_hash(
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


def _temporal_split_hash(split: TemporalSplitSpec) -> str:
    fold_parts = tuple(
        "|".join(
            (
                fold.fold_id,
                fold.training.start.isoformat(),
                fold.training.end.isoformat(),
                fold.validation.start.isoformat(),
                fold.validation.end.isoformat(),
                fold.out_of_sample.start.isoformat(),
                fold.out_of_sample.end.isoformat(),
            )
        )
        for fold in split.walk_forward_folds
    )
    return _hash_parts(
        "r4-temporal-split.v1",
        split.policy_version,
        split.training.start.isoformat(),
        split.training.end.isoformat(),
        split.validation.start.isoformat(),
        split.validation.end.isoformat(),
        split.out_of_sample.start.isoformat(),
        split.out_of_sample.end.isoformat(),
        str(split.embargo_days),
        *fold_parts,
    )


class R4CostTreatment(StrEnum):
    """Explicit cost semantics for the no-data research slice."""

    REPORT_SEPARATELY_FROM_GROSS_RETURN = "report_separately_from_gross_return"


class R4RollingBlockerCode(StrEnum):
    """Stable fail-closed reasons for one rolling R4 study."""

    R3_PROMOTION_INVALID = "r3_promotion_invalid"
    METHOD_FAMILY_INCOMPLETE = "method_family_incomplete"
    METHOD_INPUT_MISMATCH = "method_input_mismatch"
    FORMATION_EVIDENCE_INVALID = "formation_evidence_invalid"
    RETURN_PATH_INVALID = "return_path_invalid"
    REGIME_EVIDENCE_INVALID = "regime_evidence_invalid"
    EQUAL_WEIGHT_MISMATCH = "equal_weight_mismatch"
    ASSET_COVARIANCE_INVALID = "asset_covariance_invalid"
    ASSET_COVARIANCE_ILL_CONDITIONED = "asset_covariance_ill_conditioned"
    ASSET_COVARIANCE_MISSING_COVERAGE = "asset_covariance_missing_coverage"
    ASSET_RISK_PARITY_MISMATCH = "asset_risk_parity_mismatch"
    CANDIDATE_INELIGIBLE = "candidate_ineligible"
    REGIME_SAMPLE_INSUFFICIENT = "regime_sample_insufficient"
    STUDY_INCOMPLETE = "study_incomplete"


@dataclass(frozen=True)
class R4RollingValidationPolicy:
    """Versioned rolling, covariance, benchmark, and cost semantics."""

    version: str
    cost_semantics_version: str
    cost_treatment: R4CostTreatment
    weight_tolerance: Decimal
    covariance_symmetry_tolerance: Decimal
    covariance_psd_tolerance: Decimal
    maximum_condition_number: Decimal
    minimum_covariance_coverage_ratio: Decimal
    asset_risk_parity_tolerance: Decimal
    minimum_regime_windows: int

    def __post_init__(self) -> None:
        _require_text(self.version, "version")
        _require_text(self.cost_semantics_version, "cost_semantics_version")
        if not isinstance(self.cost_treatment, R4CostTreatment):
            raise ValueError("cost_treatment is invalid")
        for decimal_name, decimal_value in (
            ("weight_tolerance", self.weight_tolerance),
            ("covariance_symmetry_tolerance", self.covariance_symmetry_tolerance),
            ("covariance_psd_tolerance", self.covariance_psd_tolerance),
            ("maximum_condition_number", self.maximum_condition_number),
            (
                "minimum_covariance_coverage_ratio",
                self.minimum_covariance_coverage_ratio,
            ),
            ("asset_risk_parity_tolerance", self.asset_risk_parity_tolerance),
        ):
            _require_finite(decimal_value, decimal_name)
            if decimal_value < 0:
                raise ValueError(f"{decimal_name} cannot be negative")
        if self.maximum_condition_number < 1:
            raise ValueError("maximum_condition_number must be at least one")
        if not Decimal("0") < self.minimum_covariance_coverage_ratio <= Decimal("1"):
            raise ValueError("minimum_covariance_coverage_ratio must be within (0, 1]")
        if isinstance(self.minimum_regime_windows, bool) or self.minimum_regime_windows < 1:
            raise ValueError("minimum_regime_windows must be a positive integer")


@dataclass(frozen=True)
class R4RollingWindowInput:
    """One exact formation/OOS window shared by all three R4 methods."""

    fold: WalkForwardFold
    selection_as_of: datetime
    evaluation_as_of: datetime
    macro_projection: R4MacroExposureProjectionEvidence
    candidates: tuple[MacroRiskCandidateInput, ...]
    asset_covariance: R4AssetCovarianceEvidence
    return_path: R4OOSReturnPathEvidence
    regime_assignment: R4RegimeAssignmentEvidence
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        fold: WalkForwardFold,
        selection_as_of: datetime,
        evaluation_as_of: datetime,
        macro_projection: R4MacroExposureProjectionEvidence,
        candidates: tuple[MacroRiskCandidateInput, ...],
        asset_covariance: R4AssetCovarianceEvidence,
        return_path: R4OOSReturnPathEvidence,
        regime_assignment: R4RegimeAssignmentEvidence,
    ) -> R4RollingWindowInput:
        """Create and seal one shared rolling window."""

        digest = _rolling_window_hash(
            fold=fold,
            selection_as_of=selection_as_of,
            evaluation_as_of=evaluation_as_of,
            macro_projection=macro_projection,
            candidates=candidates,
            asset_covariance=asset_covariance,
            return_path=return_path,
            regime_assignment=regime_assignment,
        )
        return cls(
            fold=fold,
            selection_as_of=selection_as_of,
            evaluation_as_of=evaluation_as_of,
            macro_projection=macro_projection,
            candidates=candidates,
            asset_covariance=asset_covariance,
            return_path=return_path,
            regime_assignment=regime_assignment,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_aware(self.selection_as_of, "selection_as_of")
        _require_aware(self.evaluation_as_of, "evaluation_as_of")
        if self.selection_as_of >= self.evaluation_as_of:
            raise ValueError("selection_as_of must precede evaluation_as_of")
        if self.selection_as_of.date() <= self.fold.validation.end:
            raise ValueError("selection cutoff must follow the validation window")
        if self.selection_as_of.date() >= self.fold.out_of_sample.start:
            raise ValueError("selection cutoff must precede the OOS window")
        if self.evaluation_as_of.date() < self.fold.out_of_sample.end:
            raise ValueError("evaluation cutoff must cover the OOS window")
        if self.return_path.out_of_sample != self.fold.out_of_sample:
            raise ValueError("return path must bind the typed fold OOS window")
        if (
            self.asset_covariance.estimation_window.start != self.fold.training.start
            or self.asset_covariance.estimation_window.end != self.fold.validation.end
        ):
            raise ValueError("asset covariance must bind the exact formation window")
        if not self.candidates:
            raise ValueError("rolling window candidates cannot be empty")
        for candidate in self.candidates:
            if candidate.input_hash.lower() != _candidate_content_hash(candidate):
                raise ValueError("rolling window contains a non-canonical candidate")
            if candidate.exposure_version != self.macro_projection.exposure_version:
                raise ValueError("candidate does not consume the exact macro projection")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _rolling_window_hash(
            fold=self.fold,
            selection_as_of=self.selection_as_of,
            evaluation_as_of=self.evaluation_as_of,
            macro_projection=self.macro_projection,
            candidates=self.candidates,
            asset_covariance=self.asset_covariance,
            return_path=self.return_path,
            regime_assignment=self.regime_assignment,
        ):
            raise ValueError("rolling window content_hash mismatch")


def _rolling_window_hash(
    *,
    fold: WalkForwardFold,
    selection_as_of: datetime,
    evaluation_as_of: datetime,
    macro_projection: R4MacroExposureProjectionEvidence,
    candidates: tuple[MacroRiskCandidateInput, ...],
    asset_covariance: R4AssetCovarianceEvidence,
    return_path: R4OOSReturnPathEvidence,
    regime_assignment: R4RegimeAssignmentEvidence,
) -> str:
    candidates_sealed = tuple(
        f"{item.kind.value}|{item.input_hash.lower()}|{_candidate_content_hash(item)}"
        for item in sorted(candidates, key=lambda value: (value.kind.value, value.candidate_id))
    )
    return _hash_parts(
        "r4-rolling-window.v2",
        fold.fold_id,
        fold.training.start.isoformat(),
        fold.training.end.isoformat(),
        fold.validation.start.isoformat(),
        fold.validation.end.isoformat(),
        fold.out_of_sample.start.isoformat(),
        fold.out_of_sample.end.isoformat(),
        _utc_text(selection_as_of),
        _utc_text(evaluation_as_of),
        macro_projection.content_hash.lower(),
        asset_covariance.content_hash.lower(),
        return_path.content_hash.lower(),
        regime_assignment.content_hash.lower(),
        *candidates_sealed,
    )


@dataclass(frozen=True)
class R4RollingStudyInput:
    """Exact typed walk-forward study input without activation authority."""

    study_id: str
    study_version: str
    temporal_split: TemporalSplitSpec
    candidate_policy: MacroRiskValidationPolicy
    rolling_policy: R4RollingValidationPolicy
    windows: tuple[R4RollingWindowInput, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        study_id: str,
        study_version: str,
        temporal_split: TemporalSplitSpec,
        candidate_policy: MacroRiskValidationPolicy,
        rolling_policy: R4RollingValidationPolicy,
        windows: tuple[R4RollingWindowInput, ...],
    ) -> R4RollingStudyInput:
        """Create and seal a typed rolling study."""

        digest = _rolling_study_hash(
            study_id=study_id,
            study_version=study_version,
            temporal_split=temporal_split,
            candidate_policy=candidate_policy,
            rolling_policy=rolling_policy,
            windows=windows,
        )
        return cls(
            study_id=study_id,
            study_version=study_version,
            temporal_split=temporal_split,
            candidate_policy=candidate_policy,
            rolling_policy=rolling_policy,
            windows=windows,
            content_hash=digest,
        )

    @property
    def split_contract_hash(self) -> str:
        """Return the canonical hash of the full typed split and embargo plan."""

        return _temporal_split_hash(self.temporal_split)

    def __post_init__(self) -> None:
        _require_text(self.study_id, "study_id")
        _require_text(self.study_version, "study_version")
        if len(self.windows) < 2:
            raise ValueError("rolling study requires at least two windows")
        if tuple(item.fold for item in self.windows) != self.temporal_split.walk_forward_folds:
            raise ValueError("rolling windows must cover the typed split folds exactly")
        if any(
            left.fold.out_of_sample.end >= right.fold.out_of_sample.start
            for left, right in zip(self.windows, self.windows[1:], strict=False)
        ):
            raise ValueError("rolling OOS windows must be ordered and non-overlapping")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _rolling_study_hash(
            study_id=self.study_id,
            study_version=self.study_version,
            temporal_split=self.temporal_split,
            candidate_policy=self.candidate_policy,
            rolling_policy=self.rolling_policy,
            windows=self.windows,
        ):
            raise ValueError("rolling study content_hash mismatch")


def _rolling_study_hash(
    *,
    study_id: str,
    study_version: str,
    temporal_split: TemporalSplitSpec,
    candidate_policy: MacroRiskValidationPolicy,
    rolling_policy: R4RollingValidationPolicy,
    windows: tuple[R4RollingWindowInput, ...],
) -> str:
    return _hash_parts(
        "r4-rolling-study.v3",
        study_id,
        study_version,
        _temporal_split_hash(temporal_split),
        candidate_policy.version,
        _decimal_text(candidate_policy.weight_sum_tolerance),
        _decimal_text(candidate_policy.covariance_symmetry_tolerance),
        _decimal_text(candidate_policy.covariance_psd_tolerance),
        _decimal_text(candidate_policy.contribution_identity_tolerance),
        _decimal_text(candidate_policy.minimum_r_squared),
        _decimal_text(candidate_policy.minimum_stability_score),
        _decimal_text(candidate_policy.maximum_turnover),
        _decimal_text(candidate_policy.maximum_expected_cost),
        _decimal_text(candidate_policy.macro_risk_parity_tolerance),
        rolling_policy.version,
        rolling_policy.cost_semantics_version,
        rolling_policy.cost_treatment.value,
        _decimal_text(rolling_policy.weight_tolerance),
        _decimal_text(rolling_policy.covariance_symmetry_tolerance),
        _decimal_text(rolling_policy.covariance_psd_tolerance),
        _decimal_text(rolling_policy.maximum_condition_number),
        _decimal_text(rolling_policy.minimum_covariance_coverage_ratio),
        _decimal_text(rolling_policy.asset_risk_parity_tolerance),
        str(rolling_policy.minimum_regime_windows),
        *(item.content_hash.lower() for item in windows),
    )


@dataclass(frozen=True)
class R4RollingBlocker:
    """One deterministic study or window blocker."""

    code: R4RollingBlockerCode
    detail: str
    fold_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.detail, "blocker detail", maximum=500)
        if self.fold_id is not None:
            _require_text(self.fold_id, "fold_id")


@dataclass(frozen=True)
class R4MethodWindowMetrics:
    """Hash-sealed realized metrics for one method and shared OOS path."""

    fold_id: str
    kind: MacroRiskCandidateKind
    period_returns: tuple[Decimal, ...]
    gross_return: Decimal
    realized_variance: Decimal
    maximum_drawdown: Decimal
    turnover: Decimal
    expected_cost: Decimal
    cost_semantics_version: str
    candidate_report_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        fold_id: str,
        kind: MacroRiskCandidateKind,
        period_returns: tuple[Decimal, ...],
        gross_return: Decimal,
        realized_variance: Decimal,
        maximum_drawdown: Decimal,
        turnover: Decimal,
        expected_cost: Decimal,
        cost_semantics_version: str,
        candidate_report_hash: str,
    ) -> R4MethodWindowMetrics:
        """Create and seal one method-window result."""

        digest = _method_window_hash(
            fold_id=fold_id,
            kind=kind,
            period_returns=period_returns,
            gross_return=gross_return,
            realized_variance=realized_variance,
            maximum_drawdown=maximum_drawdown,
            turnover=turnover,
            expected_cost=expected_cost,
            cost_semantics_version=cost_semantics_version,
            candidate_report_hash=candidate_report_hash,
        )
        return cls(
            fold_id=fold_id,
            kind=kind,
            period_returns=period_returns,
            gross_return=gross_return,
            realized_variance=realized_variance,
            maximum_drawdown=maximum_drawdown,
            turnover=turnover,
            expected_cost=expected_cost,
            cost_semantics_version=cost_semantics_version,
            candidate_report_hash=candidate_report_hash,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_text(self.fold_id, "fold_id")
        _require_text(self.cost_semantics_version, "cost_semantics_version")
        if not self.period_returns:
            raise ValueError("window metrics require period returns")
        for value in self.period_returns:
            _require_finite(value, "period_return")
            if value < -1:
                raise ValueError("period return cannot be below -100%")
        for decimal_name, decimal_value in (
            ("gross_return", self.gross_return),
            ("realized_variance", self.realized_variance),
            ("maximum_drawdown", self.maximum_drawdown),
            ("turnover", self.turnover),
            ("expected_cost", self.expected_cost),
        ):
            _require_finite(decimal_value, decimal_name)
        if self.realized_variance < 0 or not Decimal("0") <= self.maximum_drawdown <= Decimal("1"):
            raise ValueError("window risk metrics are invalid")
        if self.turnover < 0 or self.expected_cost < 0:
            raise ValueError("window turnover and cost cannot be negative")
        _require_sha256(self.candidate_report_hash, "candidate_report_hash")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _method_window_hash(
            fold_id=self.fold_id,
            kind=self.kind,
            period_returns=self.period_returns,
            gross_return=self.gross_return,
            realized_variance=self.realized_variance,
            maximum_drawdown=self.maximum_drawdown,
            turnover=self.turnover,
            expected_cost=self.expected_cost,
            cost_semantics_version=self.cost_semantics_version,
            candidate_report_hash=self.candidate_report_hash,
        ):
            raise ValueError("method window content_hash mismatch")


def _method_window_hash(
    *,
    fold_id: str,
    kind: MacroRiskCandidateKind,
    period_returns: tuple[Decimal, ...],
    gross_return: Decimal,
    realized_variance: Decimal,
    maximum_drawdown: Decimal,
    turnover: Decimal,
    expected_cost: Decimal,
    cost_semantics_version: str,
    candidate_report_hash: str,
) -> str:
    return _hash_parts(
        "r4-method-window.v1",
        fold_id,
        kind.value,
        *(_decimal_text(value) for value in period_returns),
        _decimal_text(gross_return),
        _decimal_text(realized_variance),
        _decimal_text(maximum_drawdown),
        _decimal_text(turnover),
        _decimal_text(expected_cost),
        cost_semantics_version,
        candidate_report_hash.lower(),
    )


@dataclass(frozen=True)
class R4RollingExposurePoint:
    """Hash-sealed asset/factor exposure in one formation regime."""

    fold_id: str
    regime_code: str
    asset_code: str
    factor_code: str
    beta: Decimal
    confidence_low: Decimal
    confidence_high: Decimal
    residual_variance: Decimal
    r_squared: Decimal
    stability_score: Decimal
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        fold_id: str,
        regime_code: str,
        asset_code: str,
        factor_code: str,
        beta: Decimal,
        confidence_low: Decimal,
        confidence_high: Decimal,
        residual_variance: Decimal,
        r_squared: Decimal,
        stability_score: Decimal,
    ) -> R4RollingExposurePoint:
        """Create and seal one rolling exposure point."""

        digest = _exposure_point_hash(
            fold_id,
            regime_code,
            asset_code,
            factor_code,
            beta,
            confidence_low,
            confidence_high,
            residual_variance,
            r_squared,
            stability_score,
        )
        return cls(
            fold_id,
            regime_code,
            asset_code,
            factor_code,
            beta,
            confidence_low,
            confidence_high,
            residual_variance,
            r_squared,
            stability_score,
            digest,
        )

    def __post_init__(self) -> None:
        for text_name, text_value in (
            ("fold_id", self.fold_id),
            ("regime_code", self.regime_code),
            ("asset_code", self.asset_code),
            ("factor_code", self.factor_code),
        ):
            _require_text(text_value, text_name)
        for decimal_name, decimal_value in (
            ("beta", self.beta),
            ("confidence_low", self.confidence_low),
            ("confidence_high", self.confidence_high),
            ("residual_variance", self.residual_variance),
            ("r_squared", self.r_squared),
            ("stability_score", self.stability_score),
        ):
            _require_finite(decimal_value, decimal_name)
        if not self.confidence_low <= self.beta <= self.confidence_high:
            raise ValueError("exposure beta lies outside its confidence interval")
        if self.residual_variance < 0:
            raise ValueError("residual variance cannot be negative")
        if not Decimal("0") <= self.r_squared <= Decimal("1"):
            raise ValueError("r_squared must be within [0, 1]")
        if not Decimal("0") <= self.stability_score <= Decimal("1"):
            raise ValueError("stability_score must be within [0, 1]")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _exposure_point_hash(
            self.fold_id,
            self.regime_code,
            self.asset_code,
            self.factor_code,
            self.beta,
            self.confidence_low,
            self.confidence_high,
            self.residual_variance,
            self.r_squared,
            self.stability_score,
        ):
            raise ValueError("rolling exposure point content_hash mismatch")


def _exposure_point_hash(
    fold_id: str,
    regime_code: str,
    asset_code: str,
    factor_code: str,
    beta: Decimal,
    confidence_low: Decimal,
    confidence_high: Decimal,
    residual_variance: Decimal,
    r_squared: Decimal,
    stability_score: Decimal,
) -> str:
    return _hash_parts(
        "r4-exposure-point.v1",
        fold_id,
        regime_code,
        asset_code,
        factor_code,
        _decimal_text(beta),
        _decimal_text(confidence_low),
        _decimal_text(confidence_high),
        _decimal_text(residual_variance),
        _decimal_text(r_squared),
        _decimal_text(stability_score),
    )


@dataclass(frozen=True)
class R4RegimeExposureSummary:
    """Hash-sealed descriptive exposure stability for one regime group."""

    regime_code: str
    asset_code: str
    factor_code: str
    window_count: int
    mean_beta: Decimal
    minimum_beta: Decimal
    maximum_beta: Decimal
    mean_residual_variance: Decimal
    mean_r_squared: Decimal
    mean_stability_score: Decimal
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        regime_code: str,
        asset_code: str,
        factor_code: str,
        window_count: int,
        mean_beta: Decimal,
        minimum_beta: Decimal,
        maximum_beta: Decimal,
        mean_residual_variance: Decimal,
        mean_r_squared: Decimal,
        mean_stability_score: Decimal,
    ) -> R4RegimeExposureSummary:
        """Create and seal one regime exposure summary."""

        values = (
            regime_code,
            asset_code,
            factor_code,
            window_count,
            mean_beta,
            minimum_beta,
            maximum_beta,
            mean_residual_variance,
            mean_r_squared,
            mean_stability_score,
        )
        digest = _regime_summary_hash(*values)
        return cls(*values, digest)

    def __post_init__(self) -> None:
        for text_name, text_value in (
            ("regime_code", self.regime_code),
            ("asset_code", self.asset_code),
            ("factor_code", self.factor_code),
        ):
            _require_text(text_value, text_name)
        if isinstance(self.window_count, bool) or self.window_count < 1:
            raise ValueError("window_count must be positive")
        for decimal_name, decimal_value in (
            ("mean_beta", self.mean_beta),
            ("minimum_beta", self.minimum_beta),
            ("maximum_beta", self.maximum_beta),
            ("mean_residual_variance", self.mean_residual_variance),
            ("mean_r_squared", self.mean_r_squared),
            ("mean_stability_score", self.mean_stability_score),
        ):
            _require_finite(decimal_value, decimal_name)
        if not self.minimum_beta <= self.mean_beta <= self.maximum_beta:
            raise ValueError("regime beta summary is inconsistent")
        if self.mean_residual_variance < 0:
            raise ValueError("mean residual variance cannot be negative")
        if not Decimal("0") <= self.mean_r_squared <= Decimal("1"):
            raise ValueError("mean r_squared must be within [0, 1]")
        if not Decimal("0") <= self.mean_stability_score <= Decimal("1"):
            raise ValueError("mean stability must be within [0, 1]")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _regime_summary_hash(
            self.regime_code,
            self.asset_code,
            self.factor_code,
            self.window_count,
            self.mean_beta,
            self.minimum_beta,
            self.maximum_beta,
            self.mean_residual_variance,
            self.mean_r_squared,
            self.mean_stability_score,
        ):
            raise ValueError("regime summary content_hash mismatch")


def _regime_summary_hash(
    regime_code: str,
    asset_code: str,
    factor_code: str,
    window_count: int,
    mean_beta: Decimal,
    minimum_beta: Decimal,
    maximum_beta: Decimal,
    mean_residual_variance: Decimal,
    mean_r_squared: Decimal,
    mean_stability_score: Decimal,
) -> str:
    return _hash_parts(
        "r4-regime-summary.v1",
        regime_code,
        asset_code,
        factor_code,
        str(window_count),
        _decimal_text(mean_beta),
        _decimal_text(minimum_beta),
        _decimal_text(maximum_beta),
        _decimal_text(mean_residual_variance),
        _decimal_text(mean_r_squared),
        _decimal_text(mean_stability_score),
    )


@dataclass(frozen=True)
class R4MethodBacktestSummary:
    """Hash-sealed aggregate realized metrics for one comparison method."""

    kind: MacroRiskCandidateKind
    window_count: int
    compounded_gross_return: Decimal
    realized_variance: Decimal
    maximum_drawdown: Decimal
    total_turnover: Decimal
    total_expected_cost: Decimal
    cost_semantics_version: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        kind: MacroRiskCandidateKind,
        window_count: int,
        compounded_gross_return: Decimal,
        realized_variance: Decimal,
        maximum_drawdown: Decimal,
        total_turnover: Decimal,
        total_expected_cost: Decimal,
        cost_semantics_version: str,
    ) -> R4MethodBacktestSummary:
        """Create and seal one aggregate method summary."""

        values = (
            kind,
            window_count,
            compounded_gross_return,
            realized_variance,
            maximum_drawdown,
            total_turnover,
            total_expected_cost,
            cost_semantics_version,
        )
        digest = _method_summary_hash(*values)
        return cls(*values, digest)

    def __post_init__(self) -> None:
        if isinstance(self.window_count, bool) or self.window_count < 1:
            raise ValueError("method window_count must be positive")
        _require_text(self.cost_semantics_version, "cost_semantics_version")
        for name, value in (
            ("compounded_gross_return", self.compounded_gross_return),
            ("realized_variance", self.realized_variance),
            ("maximum_drawdown", self.maximum_drawdown),
            ("total_turnover", self.total_turnover),
            ("total_expected_cost", self.total_expected_cost),
        ):
            _require_finite(value, name)
        if self.realized_variance < 0 or not Decimal("0") <= self.maximum_drawdown <= Decimal("1"):
            raise ValueError("method risk metrics are invalid")
        if self.total_turnover < 0 or self.total_expected_cost < 0:
            raise ValueError("method turnover and cost cannot be negative")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _method_summary_hash(
            self.kind,
            self.window_count,
            self.compounded_gross_return,
            self.realized_variance,
            self.maximum_drawdown,
            self.total_turnover,
            self.total_expected_cost,
            self.cost_semantics_version,
        ):
            raise ValueError("method summary content_hash mismatch")


def _method_summary_hash(
    kind: MacroRiskCandidateKind,
    window_count: int,
    compounded_gross_return: Decimal,
    realized_variance: Decimal,
    maximum_drawdown: Decimal,
    total_turnover: Decimal,
    total_expected_cost: Decimal,
    cost_semantics_version: str,
) -> str:
    return _hash_parts(
        "r4-method-summary.v1",
        kind.value,
        str(window_count),
        _decimal_text(compounded_gross_return),
        _decimal_text(realized_variance),
        _decimal_text(maximum_drawdown),
        _decimal_text(total_turnover),
        _decimal_text(total_expected_cost),
        cost_semantics_version,
    )


def _artifact_is_complete(
    study: R4RollingStudyInput | None,
    expected_fold_ids: tuple[str, ...],
    window_metrics: tuple[R4MethodWindowMetrics, ...],
    exposure_points: tuple[R4RollingExposurePoint, ...],
    regime_summaries: tuple[R4RegimeExposureSummary, ...],
    method_summaries: tuple[R4MethodBacktestSummary, ...],
) -> bool:
    from .macro_risk_rolling_output_integrity import artifact_is_complete

    return artifact_is_complete(
        study=study,
        expected_fold_ids=expected_fold_ids,
        window_metrics=window_metrics,
        exposure_points=exposure_points,
        regime_summaries=regime_summaries,
        method_summaries=method_summaries,
    )


@dataclass(frozen=True)
class R4RollingResearchArtifact:
    """Derived, hash-sealed artifact that never authorizes a decision."""

    study_id: str
    study_version: str
    input_hash: str
    r3_promotion_attestation_hash: str
    expected_window_count: int
    expected_fold_ids: tuple[str, ...]
    evidence_complete: bool
    eligible_for_research_comparison: bool
    window_metrics: tuple[R4MethodWindowMetrics, ...]
    exposure_points: tuple[R4RollingExposurePoint, ...]
    regime_summaries: tuple[R4RegimeExposureSummary, ...]
    method_summaries: tuple[R4MethodBacktestSummary, ...]
    blockers: tuple[R4RollingBlocker, ...]
    evaluated_at: datetime
    policy_version: str
    content_hash: str
    usage_scope: str = "research_only"
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        study: R4RollingStudyInput,
        promotion_attestation: ExactR3PromotionAttestation,
        window_metrics: tuple[R4MethodWindowMetrics, ...],
        exposure_points: tuple[R4RollingExposurePoint, ...],
        regime_summaries: tuple[R4RegimeExposureSummary, ...],
        method_summaries: tuple[R4MethodBacktestSummary, ...],
        blockers: tuple[R4RollingBlocker, ...],
        evaluated_at: datetime,
    ) -> R4RollingResearchArtifact:
        """Derive completeness and eligibility, then seal the research artifact."""

        expected_fold_ids = tuple(item.fold.fold_id for item in study.windows)
        expected_count = len(expected_fold_ids)
        complete = _artifact_is_complete(
            study,
            expected_fold_ids,
            window_metrics,
            exposure_points,
            regime_summaries,
            method_summaries,
        )
        effective_blockers = blockers
        if not complete and not any(
            item.code is R4RollingBlockerCode.STUDY_INCOMPLETE for item in blockers
        ):
            effective_blockers = (
                *blockers,
                R4RollingBlocker(
                    code=R4RollingBlockerCode.STUDY_INCOMPLETE,
                    detail="rolling study output is incomplete",
                ),
            )
        effective_blockers = tuple(
            sorted(
                effective_blockers,
                key=lambda item: (item.code.value, item.fold_id or "", item.detail),
            )
        )
        eligible = complete and not effective_blockers
        digest = build_r4_rolling_artifact_hash(
            study_id=study.study_id,
            study_version=study.study_version,
            input_hash=study.content_hash,
            r3_promotion_attestation_hash=promotion_attestation.content_hash,
            expected_window_count=expected_count,
            expected_fold_ids=expected_fold_ids,
            evidence_complete=complete,
            eligible_for_research_comparison=eligible,
            window_metrics=window_metrics,
            exposure_points=exposure_points,
            regime_summaries=regime_summaries,
            method_summaries=method_summaries,
            blockers=effective_blockers,
            evaluated_at=evaluated_at,
            policy_version=study.rolling_policy.version,
        )
        return cls(
            study_id=study.study_id,
            study_version=study.study_version,
            input_hash=study.content_hash,
            r3_promotion_attestation_hash=promotion_attestation.content_hash,
            expected_window_count=expected_count,
            expected_fold_ids=expected_fold_ids,
            evidence_complete=complete,
            eligible_for_research_comparison=eligible,
            window_metrics=window_metrics,
            exposure_points=exposure_points,
            regime_summaries=regime_summaries,
            method_summaries=method_summaries,
            blockers=effective_blockers,
            evaluated_at=evaluated_at,
            policy_version=study.rolling_policy.version,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        _require_text(self.study_id, "study_id")
        _require_text(self.study_version, "study_version")
        _require_sha256(self.input_hash, "input_hash")
        _require_sha256(self.r3_promotion_attestation_hash, "r3_promotion_attestation_hash")
        if isinstance(self.expected_window_count, bool) or self.expected_window_count < 2:
            raise ValueError("expected_window_count must describe a rolling study")
        if len(self.expected_fold_ids) != self.expected_window_count or len(
            self.expected_fold_ids
        ) != len(set(self.expected_fold_ids)):
            raise ValueError("expected fold identities must be complete and unique")
        for fold_id in self.expected_fold_ids:
            _require_text(fold_id, "expected_fold_id")
        internally_complete = _artifact_is_complete(
            None,
            self.expected_fold_ids,
            self.window_metrics,
            self.exposure_points,
            self.regime_summaries,
            self.method_summaries,
        )
        if self.evidence_complete and not internally_complete:
            raise ValueError("artifact completeness contradicts sealed outputs")
        if self.eligible_for_research_comparison is not (
            self.evidence_complete and not self.blockers
        ):
            raise ValueError("artifact eligibility must be derived from blockers and completeness")
        _require_aware(self.evaluated_at, "evaluated_at")
        _require_text(self.policy_version, "policy_version")
        if self.usage_scope != "research_only":
            raise ValueError("rolling R4 artifacts must remain research_only")
        if not self.must_not_use_for_decision or not self.must_not_execute:
            raise ValueError("rolling R4 artifacts cannot authorize decisions or execution")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != build_r4_rolling_artifact_hash(
            study_id=self.study_id,
            study_version=self.study_version,
            input_hash=self.input_hash,
            r3_promotion_attestation_hash=self.r3_promotion_attestation_hash,
            expected_window_count=self.expected_window_count,
            expected_fold_ids=self.expected_fold_ids,
            evidence_complete=self.evidence_complete,
            eligible_for_research_comparison=self.eligible_for_research_comparison,
            window_metrics=self.window_metrics,
            exposure_points=self.exposure_points,
            regime_summaries=self.regime_summaries,
            method_summaries=self.method_summaries,
            blockers=self.blockers,
            evaluated_at=self.evaluated_at,
            policy_version=self.policy_version,
        ):
            raise ValueError("rolling R4 artifact content_hash mismatch")


from apps.portfolio.domain.macro_risk_rolling_hashing import (  # noqa: E402
    build_r4_rolling_artifact_hash,
)

__all__ = [
    "R4CostTreatment",
    "R4MethodBacktestSummary",
    "R4MethodWindowMetrics",
    "R4RegimeExposureSummary",
    "R4RollingBlocker",
    "R4RollingBlockerCode",
    "R4RollingExposurePoint",
    "R4RollingResearchArtifact",
    "R4RollingStudyInput",
    "R4RollingValidationPolicy",
    "R4RollingWindowInput",
    "build_r4_rolling_artifact_hash",
]
