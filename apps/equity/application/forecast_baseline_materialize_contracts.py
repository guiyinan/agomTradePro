"""Typed evidence ports and commands for forecast-baseline materialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.equity.domain.forecast_baseline import (
    BaselineApprovalStatus,
    BaselineComputationMethod,
    BaselineFamily,
    CostApplicability,
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
    ForecastErrorMetric,
    ForecastEvaluationPolicy,
    ForecastScenario,
    InvalidationApplicability,
    InvalidationOperator,
    MapeZeroActualRule,
    SensitivityArtifactReference,
    TieBreakRule,
)
from apps.equity.domain.operating_forecast import OperatingForecastVersion


def _require_token(value: str, field_name: str) -> None:
    if not value or len(value) > 192 or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_hash(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class VersionRef:
    """Stable ID/version pair accepted by commands."""

    stable_id: str
    version: str

    def __post_init__(self) -> None:
        _require_token(self.stable_id, "stable_id")
        _require_token(self.version, "version")


@dataclass(frozen=True)
class OperatingForecastRef:
    """Stable OperatingForecastVersion identity accepted by commands."""

    stable_id: str
    version: int

    def __post_init__(self) -> None:
        _require_token(self.stable_id, "forecast stable_id")
        if isinstance(self.version, bool) or self.version < 1:
            raise ValueError("forecast version must be positive")


@dataclass(frozen=True)
class EvidenceIdentity:
    """Exact provider evidence identity resolved after command validation."""

    stable_id: str
    version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.stable_id, "evidence stable_id")
        _require_token(self.version, "evidence version")
        _require_hash(self.content_hash, "evidence content_hash")

    @property
    def version_ref(self) -> VersionRef:
        """Return the command-safe portion of this identity."""

        return VersionRef(self.stable_id, self.version)


@dataclass(frozen=True)
class NumericEvidenceIdentity:
    """Exact identity for canonical records whose version is numeric."""

    stable_id: str
    version: int
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.stable_id, "numeric evidence stable_id")
        if isinstance(self.version, bool) or self.version < 1:
            raise ValueError("numeric evidence version must be positive")
        _require_hash(self.content_hash, "numeric evidence content_hash")


@dataclass(frozen=True)
class ApprovedMetricRuleEvidence:
    """Owner-approved metric gate before Domain construction."""

    metric_code: str
    error_metric: ForecastErrorMetric
    maximum_forecast_error: Decimal
    minimum_improvement: Decimal
    minimum_sample_count: int
    minimum_coverage: Decimal
    mape_zero_actual_rule: MapeZeroActualRule


@dataclass(frozen=True)
class ApprovedInvalidationRuleEvidence:
    """Owner-approved invalidation rule before Domain construction."""

    rule_code: str
    metric_code: str
    operator: InvalidationOperator
    threshold: Decimal
    consecutive_periods: int


@dataclass(frozen=True)
class ApprovedCostRuleEvidence:
    """Owner-approved cost applicability evidence."""

    applicability: CostApplicability
    cost_model: EvidenceIdentity | None
    not_applicable_reason: str


@dataclass(frozen=True)
class ApprovedPITInputEvidence:
    """Exact Data Center manifest requested by one approved input role."""

    input_role: str
    dataset: str
    metric_code: str
    unit: str
    knowledge_scope: str
    manifest: EvidenceIdentity


@dataclass(frozen=True)
class BaselineApprovalEvidence:
    """Exact Equity-owned approval configuration resolved by ID/version."""

    approval: EvidenceIdentity
    approval_owner: str
    approval_status: BaselineApprovalStatus
    evaluation_policy: ForecastEvaluationPolicy
    spec_ref: VersionRef
    subject_code: str
    industry_code: str
    candidate_scenario: ForecastScenario
    horizon_quarters: int
    family: BaselineFamily
    computation_method: BaselineComputationMethod
    computation_code_version: str
    family_parameter_version: str
    family_parameter_hash: str
    seasonal_lag_periods: int | None
    pit_inputs: tuple[ApprovedPITInputEvidence, ...]
    training_window_start: date
    training_window_end: date
    expected_period_ends: tuple[date, ...]
    calendar: EvidenceIdentity
    forecast_origin_at: datetime
    metric_rules: tuple[ApprovedMetricRuleEvidence, ...]
    metric_evaluation_order: tuple[str, ...]
    tie_break_rule: TieBreakRule
    cost_rule: ApprovedCostRuleEvidence
    invalidation_applicability: InvalidationApplicability
    invalidation_rules: tuple[ApprovedInvalidationRuleEvidence, ...]
    invalidation_not_applicable_reason: str
    approved_at: datetime
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Reject post-hoc or authority-inconsistent approval evidence."""

        for field_name, value in (
            ("approval approved_at", self.approved_at),
            ("approval recorded_at", self.recorded_at),
            ("approval forecast_origin_at", self.forecast_origin_at),
            ("approval valid_until", self.valid_until),
        ):
            _require_aware(value, field_name)
        if (
            self.approval_owner != "equity"
            or self.approval_status is not BaselineApprovalStatus.APPROVED
        ):
            raise ValueError("baseline approval authority is invalid")
        if not (self.approved_at <= self.recorded_at <= self.forecast_origin_at < self.valid_until):
            raise ValueError("baseline approval must be recorded before forecast origin")
        if not (
            self.forecast_origin_at
            == self.evaluation_policy.forecast_knowledge_cutoff_at
            <= self.evaluation_policy.forecast_submission_deadline_at
            < self.evaluation_policy.valid_until
        ):
            raise ValueError("baseline approval freeze window is invalid")


@dataclass(frozen=True)
class BaselinePITMemberEvidence:
    """Exact selected manifest member and upstream fact payload."""

    target_period_end: date
    source_period_end: date
    metric_code: str
    member: EvidenceIdentity
    upstream_fact: EvidenceIdentity
    source_value: Decimal
    source_unit: str
    source_effective_at: datetime
    source_available_at: datetime
    vintage: EvidenceIdentity


@dataclass(frozen=True)
class ManifestSelectedVersionEvidence:
    """Canonical manifest selection across member, fact and vintage layers."""

    member: EvidenceIdentity
    upstream_fact: EvidenceIdentity
    vintage: EvidenceIdentity


@dataclass(frozen=True)
class BaselinePITInputSnapshot:
    """One exact manifest resolved by the Data Center provider."""

    input_role: str
    dataset: str
    metric_code: str
    unit: str
    manifest: EvidenceIdentity
    as_of_time: datetime
    produced_at: datetime
    knowledge_scope: str
    is_verified: bool
    coverage_ratio: Decimal
    missing_count: int
    estimated_count: int
    unknown_count: int
    selected_versions: tuple[ManifestSelectedVersionEvidence, ...]
    selected_versions_hash: str
    members: tuple[BaselinePITMemberEvidence, ...]


@dataclass(frozen=True)
class CalendarPeriodEvidence:
    """One period ordinal from an exact Data Center calendar version."""

    period_end: date
    ordinal: int


@dataclass(frozen=True)
class CalendarScheduleSnapshot:
    """Exact Data Center schedule resolved for the approved calendar."""

    owner: str
    identity: EvidenceIdentity
    periods: tuple[CalendarPeriodEvidence, ...]


@dataclass(frozen=True)
class BaselinePITBundle:
    """Exact source selection returned for one approved baseline family."""

    family: BaselineFamily
    computation_method: BaselineComputationMethod
    computation_code_version: str
    family_parameter_version: str
    family_parameter_hash: str
    seasonal_lag_periods: int | None
    inputs: tuple[BaselinePITInputSnapshot, ...]
    calendar: CalendarScheduleSnapshot


@dataclass(frozen=True)
class OperatingForecastSnapshot:
    """Exact canonical OperatingForecastVersion and persisted content seal."""

    forecast: OperatingForecastVersion
    persisted_content_hash: str
    persisted_at: datetime
    template_owner: str
    template: NumericEvidenceIdentity
    template_run: NumericEvidenceIdentity
    sensitivity_evidence: tuple[SensitivityArtifactReference, ...]

    def __post_init__(self) -> None:
        _require_hash(self.persisted_content_hash, "persisted forecast content hash")
        _require_aware(self.persisted_at, "persisted forecast timestamp")


class BaselineApprovalEvidenceProvider(Protocol):
    """Read one exact Equity-owned approval at the requested knowledge time."""

    def get_approval(
        self,
        approval_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> BaselineApprovalEvidence | None: ...


class BaselinePITEvidenceProvider(Protocol):
    """Read exact manifests, members, facts and schedule without substitution."""

    def get_baseline_bundle(
        self,
        *,
        manifests: tuple[EvidenceIdentity, ...],
        calendar: EvidenceIdentity,
        target_periods: tuple[date, ...],
        family: BaselineFamily,
        as_of: datetime,
    ) -> BaselinePITBundle: ...


class OperatingForecastEvidenceProvider(Protocol):
    """Exact-read canonical OperatingForecastVersion evidence."""

    def get_forecast(
        self,
        forecast_ref: OperatingForecastRef,
        *,
        as_of: datetime,
    ) -> OperatingForecastSnapshot | None: ...


class ForecastBaselineSpecRepository(Protocol):
    """Append/load exact immutable baseline specifications."""

    def append_spec(self, spec: ForecastBaselineSpec) -> ForecastBaselineSpec: ...

    def get_spec(self, spec_ref: VersionRef) -> ForecastBaselineSpec | None: ...

    def append_artifact(
        self,
        artifact: ForecastBaselineArtifact,
    ) -> ForecastBaselineArtifact: ...

    def get_artifact(
        self,
        artifact_ref: VersionRef,
    ) -> ForecastBaselineArtifact | None: ...

    def append_trial(
        self,
        trial: ForecastBaselineTrialResult,
    ) -> ForecastBaselineTrialResult: ...

    def get_trial(
        self,
        trial_ref: VersionRef,
    ) -> ForecastBaselineTrialResult | None: ...


class ForecastBaselineEvidenceError(ValueError):
    """Raised when an exact upstream identity or temporal rule is violated."""


class ForecastBaselineConflictError(ForecastBaselineEvidenceError):
    """Raised when an immutable ledger identity has different content."""


@dataclass(frozen=True)
class MaterializeForecastBaselineSpecCommand:
    """ID-only request to materialize one approved baseline specification."""

    output_spec_ref: VersionRef
    approval_ref: VersionRef
    as_of: datetime

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "command as_of")


@dataclass(frozen=True)
class BuildForecastBaselineArtifactCommand:
    """ID-only request to build exact baseline predictions for forecasts."""

    output_artifact_ref: VersionRef
    spec_ref: VersionRef
    forecast_refs: tuple[OperatingForecastRef, ...]
    as_of: datetime

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "command as_of")
        if not self.forecast_refs or len(self.forecast_refs) != len(set(self.forecast_refs)):
            raise ValueError("forecast refs must be non-empty and unique")
