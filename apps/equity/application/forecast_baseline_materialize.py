"""R1 forecast-baseline ports plus spec/artifact materialization use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.equity.domain.forecast_baseline import (
    BaselineApprovalStatus,
    BaselineComputationEvidence,
    BaselineComputationMethod,
    BaselineCostRule,
    BaselineFamily,
    BaselineInvalidationRule,
    BaselineMetricRule,
    BaselinePITInputSpec,
    BaselinePITManifestMember,
    BaselinePITSelectedVersion,
    BaselinePredictionObservation,
    CostApplicability,
    ForecastArtifactReference,
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
    ForecastCalendarPeriod,
    ForecastCalendarScheduleEvidence,
    ForecastErrorMetric,
    ForecastEvaluationPolicy,
    ForecastPeriodHorizon,
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
    valid_until: datetime


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


class MaterializeForecastBaselineSpecUseCase:
    """Exact-read approved configuration and append one immutable Domain spec."""

    def __init__(
        self,
        *,
        approval_provider: BaselineApprovalEvidenceProvider,
        pit_provider: BaselinePITEvidenceProvider,
        repository: ForecastBaselineSpecRepository,
    ) -> None:
        self._approval_provider = approval_provider
        self._pit_provider = pit_provider
        self._repository = repository

    def execute(
        self,
        command: MaterializeForecastBaselineSpecCommand,
    ) -> ForecastBaselineSpec:
        """Resolve exact evidence, validate source selection and append the spec."""

        approval = self._approval_provider.get_approval(
            command.approval_ref,
            as_of=command.as_of,
        )
        if approval is None:
            raise ForecastBaselineEvidenceError("baseline approval evidence is missing")
        _validate_approval(command, approval)
        bundle = self._pit_provider.get_baseline_bundle(
            manifests=tuple(item.manifest for item in approval.pit_inputs),
            calendar=approval.calendar,
            target_periods=approval.expected_period_ends,
            family=approval.family,
            as_of=command.as_of,
        )
        schedule, pit_inputs = _materialize_pit_evidence(approval, bundle)
        period_horizons = tuple(
            ForecastPeriodHorizon.create(
                target_period_end=period,
                forecast_origin_at=approval.forecast_origin_at,
                schedule=schedule,
            )
            for period in approval.expected_period_ends
        )
        spec = ForecastBaselineSpec.create(
            spec_id=approval.spec_ref.stable_id,
            spec_version=approval.spec_ref.version,
            owner="equity",
            approval_evidence_id=approval.approval.stable_id,
            approval_evidence_version=approval.approval.version,
            approval_evidence_content_hash=approval.approval.content_hash,
            approval_owner=approval.approval_owner,
            approval_status=approval.approval_status,
            evaluation_policy=approval.evaluation_policy,
            subject_code=approval.subject_code,
            industry_code=approval.industry_code,
            candidate_scenario=approval.candidate_scenario,
            horizon_quarters=approval.horizon_quarters,
            family=approval.family,
            computation_method=approval.computation_method,
            computation_code_version=approval.computation_code_version,
            family_parameter_version=approval.family_parameter_version,
            family_parameter_hash=approval.family_parameter_hash,
            seasonal_lag_periods=approval.seasonal_lag_periods,
            pit_inputs=pit_inputs,
            training_window_start=approval.training_window_start,
            training_window_end=approval.training_window_end,
            expected_period_ends=approval.expected_period_ends,
            calendar_schedule=schedule,
            period_horizons=period_horizons,
            metric_rules=tuple(
                BaselineMetricRule(
                    metric_code=item.metric_code,
                    error_metric=item.error_metric,
                    maximum_forecast_error=item.maximum_forecast_error,
                    minimum_improvement=item.minimum_improvement,
                    minimum_sample_count=item.minimum_sample_count,
                    minimum_coverage=item.minimum_coverage,
                    mape_zero_actual_rule=item.mape_zero_actual_rule,
                )
                for item in approval.metric_rules
            ),
            metric_evaluation_order=approval.metric_evaluation_order,
            tie_break_rule=approval.tie_break_rule,
            cost_rule=_materialize_cost_rule(approval.cost_rule),
            invalidation_applicability=approval.invalidation_applicability,
            invalidation_rules=tuple(
                BaselineInvalidationRule(
                    rule_code=item.rule_code,
                    metric_code=item.metric_code,
                    operator=item.operator,
                    threshold=item.threshold,
                    consecutive_periods=item.consecutive_periods,
                )
                for item in approval.invalidation_rules
            ),
            invalidation_not_applicable_reason=(approval.invalidation_not_applicable_reason),
            approved_at=approval.approved_at,
            valid_until=approval.valid_until,
        )
        persisted = self._repository.append_spec(spec)
        if persisted != spec:
            raise ForecastBaselineEvidenceError(
                "spec repository did not preserve the exact domain object"
            )
        return persisted


class BuildForecastBaselineArtifactUseCase:
    """Build an immutable artifact exclusively from exact owner evidence."""

    def __init__(
        self,
        *,
        forecast_provider: OperatingForecastEvidenceProvider,
        pit_provider: BaselinePITEvidenceProvider,
        repository: ForecastBaselineSpecRepository,
    ) -> None:
        self._forecast_provider = forecast_provider
        self._pit_provider = pit_provider
        self._repository = repository

    def execute(
        self,
        command: BuildForecastBaselineArtifactCommand,
    ) -> ForecastBaselineArtifact:
        """Resolve exact forecasts and PIT sources, then append one artifact."""

        spec = self._repository.get_spec(command.spec_ref)
        if spec is None or (spec.spec_id, spec.spec_version) != (
            command.spec_ref.stable_id,
            command.spec_ref.version,
        ):
            raise ForecastBaselineEvidenceError("exact baseline spec is unavailable")
        if not spec.approved_at <= command.as_of < spec.valid_until:
            raise ForecastBaselineEvidenceError("baseline spec is inactive")
        bundle = self._pit_provider.get_baseline_bundle(
            manifests=tuple(
                EvidenceIdentity(
                    item.pit_manifest_id,
                    item.pit_manifest_version,
                    item.pit_manifest_hash,
                )
                for item in spec.pit_inputs
            ),
            calendar=EvidenceIdentity(
                spec.calendar_schedule.calendar_id,
                spec.calendar_schedule.calendar_version,
                spec.calendar_schedule.calendar_content_hash,
            ),
            target_periods=spec.expected_period_ends,
            family=spec.family,
            as_of=command.as_of,
        )
        _validate_exact_baseline_bundle(spec, bundle)
        forecasts = tuple(
            _materialize_forecast_reference(
                spec,
                forecast_ref,
                self._forecast_provider.get_forecast(
                    forecast_ref,
                    as_of=command.as_of,
                ),
                knowledge_as_of=command.as_of,
            )
            for forecast_ref in command.forecast_refs
        )
        forecasts = tuple(sorted(forecasts, key=lambda item: item.target_period_end))
        if tuple(item.target_period_end for item in forecasts) != spec.expected_period_ends:
            raise ForecastBaselineEvidenceError(
                "forecast versions do not exactly cover approved periods"
            )
        predictions = _materialize_baseline_predictions(spec)
        artifact = ForecastBaselineArtifact.create(
            artifact_id=command.output_artifact_ref.stable_id,
            artifact_version=command.output_artifact_ref.version,
            owner="equity",
            spec=spec,
            forecasts=forecasts,
            predictions=predictions,
            knowledge_as_of=command.as_of,
            produced_at=command.as_of,
            valid_until=spec.valid_until,
        )
        persisted = self._repository.append_artifact(artifact)
        if persisted != artifact:
            raise ForecastBaselineEvidenceError(
                "artifact repository did not preserve the exact domain object"
            )
        return persisted


def _validate_exact_baseline_bundle(
    spec: ForecastBaselineSpec,
    bundle: BaselinePITBundle,
) -> None:
    if (
        bundle.family is not spec.family
        or bundle.computation_method is not spec.computation_method
        or bundle.computation_code_version != spec.computation_code_version
        or bundle.family_parameter_version != spec.family_parameter_version
        or bundle.family_parameter_hash != spec.family_parameter_hash
        or bundle.seasonal_lag_periods != spec.seasonal_lag_periods
        or bundle.calendar.owner != "data_center"
    ):
        raise ForecastBaselineEvidenceError("artifact baseline bundle was substituted")
    schedule = ForecastCalendarScheduleEvidence.create(
        owner=bundle.calendar.owner,
        calendar_id=bundle.calendar.identity.stable_id,
        calendar_version=bundle.calendar.identity.version,
        calendar_content_hash=bundle.calendar.identity.content_hash,
        periods=tuple(
            ForecastCalendarPeriod(item.period_end, item.ordinal)
            for item in bundle.calendar.periods
        ),
    )
    if schedule != spec.calendar_schedule:
        raise ForecastBaselineEvidenceError("artifact calendar schedule was substituted")
    expected_by_role = {item.input_role: item for item in spec.pit_inputs}
    actual_by_role = {item.input_role: item for item in bundle.inputs}
    if (
        len(expected_by_role) != len(spec.pit_inputs)
        or len(actual_by_role) != len(bundle.inputs)
        or set(actual_by_role) != set(expected_by_role)
    ):
        raise ForecastBaselineEvidenceError("artifact baseline input roles were substituted")
    forecast_origin_at = spec.period_horizons[0].forecast_origin_at
    for role, expected in expected_by_role.items():
        snapshot = actual_by_role[role]
        if (
            snapshot.dataset != expected.dataset
            or snapshot.metric_code != expected.metric_code
            or snapshot.unit != expected.unit
            or snapshot.manifest
            != EvidenceIdentity(
                expected.pit_manifest_id,
                expected.pit_manifest_version,
                expected.pit_manifest_hash,
            )
            or snapshot.as_of_time != expected.manifest_as_of_time
            or snapshot.produced_at != expected.manifest_produced_at
            or snapshot.knowledge_scope != expected.manifest_knowledge_scope
            or snapshot.is_verified != expected.manifest_is_verified
            or snapshot.coverage_ratio != expected.manifest_coverage_ratio
            or snapshot.missing_count != expected.manifest_missing_count
            or snapshot.estimated_count != expected.manifest_estimated_count
            or snapshot.unknown_count != expected.manifest_unknown_count
            or snapshot.selected_versions_hash != expected.selected_versions_hash
        ):
            raise ForecastBaselineEvidenceError("artifact PIT manifest was substituted")
        selected_versions = _selected_versions_from_evidence(snapshot.selected_versions)
        if selected_versions != expected.selected_versions:
            raise ForecastBaselineEvidenceError("artifact selected versions were substituted")
        materialized_members = tuple(
            _materialize_member_for_spec(
                spec,
                schedule,
                expected.metric_code,
                expected.unit,
                member,
                forecast_origin_at,
            )
            for member in sorted(
                snapshot.members,
                key=lambda item: item.target_period_end,
            )
        )
        if materialized_members != expected.members:
            raise ForecastBaselineEvidenceError("artifact PIT members were substituted")


def _materialize_forecast_reference(
    spec: ForecastBaselineSpec,
    forecast_ref: OperatingForecastRef,
    snapshot: OperatingForecastSnapshot | None,
    *,
    knowledge_as_of: datetime,
) -> ForecastArtifactReference:
    if snapshot is None:
        raise ForecastBaselineEvidenceError("exact operating forecast is unavailable")
    forecast = snapshot.forecast
    if (
        forecast.forecast_id != forecast_ref.stable_id
        or forecast.forecast_version != forecast_ref.version
        or snapshot.persisted_content_hash != forecast.content_hash
        or not (
            forecast.as_of_time
            <= snapshot.persisted_at
            <= spec.evaluation_policy.forecast_submission_deadline_at
        )
        or snapshot.persisted_at > knowledge_as_of
        or snapshot.template_owner != "sector"
        or snapshot.template
        != NumericEvidenceIdentity(
            forecast.template_code,
            forecast.template_version,
            forecast.template_content_hash.lower(),
        )
        or snapshot.template_run
        != NumericEvidenceIdentity(
            forecast.template_run_key,
            forecast.template_run_version,
            forecast.template_run_content_hash.lower(),
        )
    ):
        raise ForecastBaselineEvidenceError("operating forecast identity was substituted")
    horizon_by_period = {item.target_period_end: item for item in spec.period_horizons}
    horizon = horizon_by_period.get(forecast.target_period_end)
    if (
        forecast.subject_code != spec.subject_code
        or forecast.industry_code != spec.industry_code
        or horizon is None
        or forecast.as_of_time != horizon.forecast_origin_at
        or forecast.horizon_quarters != horizon.horizon_quarters
    ):
        raise ForecastBaselineEvidenceError("operating forecast scope or horizon mismatch")
    projection = next(
        (item for item in forecast.projections if item.scenario is spec.candidate_scenario),
        None,
    )
    if projection is None:
        raise ForecastBaselineEvidenceError("candidate scenario projection is unavailable")
    expected_sensitivities = tuple(
        sorted(
            (
                SensitivityArtifactReference(
                    owner="valuation",
                    artifact_id=item.source_artifact_ref,
                    artifact_version=item.method_version,
                    artifact_content_hash=item.source_artifact_hash.lower(),
                )
                for item in projection.sensitivities
            ),
            key=lambda item: (item.owner, item.artifact_id, item.artifact_version),
        )
    )
    supplied_sensitivities = tuple(
        sorted(
            snapshot.sensitivity_evidence,
            key=lambda item: (item.owner, item.artifact_id, item.artifact_version),
        )
    )
    if supplied_sensitivities != expected_sensitivities:
        raise ForecastBaselineEvidenceError("forecast sensitivity evidence was substituted")
    expected_units = {item.metric_code: item.unit for item in spec.pit_inputs}
    metric_values: list[tuple[str, Decimal]] = []
    metric_units: list[tuple[str, str]] = []
    for rule in spec.metric_rules:
        value, unit = _projection_metric(projection, rule.metric_code)
        if expected_units.get(rule.metric_code) != unit:
            raise ForecastBaselineEvidenceError("forecast projection unit mismatch")
        metric_values.append((rule.metric_code, value))
        metric_units.append((rule.metric_code, unit))
    return ForecastArtifactReference(
        forecast_id=forecast.forecast_id,
        forecast_version=forecast.forecast_version,
        forecast_content_hash=forecast.content_hash,
        subject_code=forecast.subject_code,
        industry_code=forecast.industry_code,
        candidate_scenario=spec.candidate_scenario,
        horizon_quarters=forecast.horizon_quarters,
        period_horizon=horizon,
        metric_values=tuple(metric_values),
        metric_units=tuple(metric_units),
        as_of_time=forecast.as_of_time,
        persisted_at=snapshot.persisted_at,
        target_period_end=forecast.target_period_end,
        template_owner=snapshot.template_owner,
        template_code=forecast.template_code,
        template_version=forecast.template_version,
        template_content_hash=forecast.template_content_hash.lower(),
        template_run_owner=snapshot.template_owner,
        template_run_key=forecast.template_run_key,
        template_run_version=forecast.template_run_version,
        template_run_content_hash=forecast.template_run_content_hash.lower(),
        sensitivity_artifacts=expected_sensitivities,
    )


def _projection_metric(projection: object, metric_code: str) -> tuple[Decimal, str]:
    revenue = getattr(projection, "revenue", None)
    net_profit = getattr(projection, "net_profit", None)
    cash_flow = getattr(projection, "cash_flow", None)
    currency_unit = getattr(projection, "currency_unit", None)
    margin = getattr(projection, "profit_margin_percent", None)
    if metric_code == "revenue" and isinstance(revenue, Decimal) and isinstance(currency_unit, str):
        return revenue, currency_unit
    if (
        metric_code == "net_profit"
        and isinstance(net_profit, Decimal)
        and isinstance(currency_unit, str)
    ):
        return net_profit, currency_unit
    if (
        metric_code == "cash_flow"
        and isinstance(cash_flow, Decimal)
        and isinstance(currency_unit, str)
    ):
        return cash_flow, currency_unit
    if metric_code in {"profit_margin", "profit_margin_percent"} and isinstance(margin, Decimal):
        return margin, "%"
    raise ForecastBaselineEvidenceError("forecast metric projection is unsupported")


def _materialize_baseline_predictions(
    spec: ForecastBaselineSpec,
) -> tuple[BaselinePredictionObservation, ...]:
    inputs_by_metric: dict[str, BaselinePITInputSpec] = {}
    for item in spec.pit_inputs:
        if item.metric_code in inputs_by_metric:
            raise ForecastBaselineEvidenceError("baseline metric input is ambiguous")
        inputs_by_metric[item.metric_code] = item
    predictions: list[BaselinePredictionObservation] = []
    for period in spec.expected_period_ends:
        for rule in spec.metric_rules:
            pit_input = inputs_by_metric.get(rule.metric_code)
            member = (
                next(
                    (item for item in pit_input.members if item.target_period_end == period),
                    None,
                )
                if pit_input is not None
                else None
            )
            if pit_input is None or member is None:
                raise ForecastBaselineEvidenceError("baseline member is unavailable")
            computation = BaselineComputationEvidence.create(
                family=spec.family,
                method=spec.computation_method,
                code_version=spec.computation_code_version,
                family_parameter_version=spec.family_parameter_version,
                family_parameter_hash=spec.family_parameter_hash,
                seasonal_lag_periods=spec.seasonal_lag_periods,
                source_value=member.source_value,
                source_unit=member.source_unit,
                source_member_id=member.selected_member_id,
                source_member_version=member.selected_member_version,
                source_member_content_hash=member.selected_member_content_hash,
                source_fact_id=member.source_fact_id,
                source_fact_version=member.source_fact_version,
                source_fact_content_hash=member.source_fact_content_hash,
                source_vintage_id=member.vintage_id,
                source_vintage_version=member.vintage_version,
                source_vintage_content_hash=member.vintage_content_hash,
            )
            predictions.append(
                BaselinePredictionObservation(
                    period_end=period,
                    metric_code=rule.metric_code,
                    input_role=pit_input.input_role,
                    value=member.source_value,
                    unit=member.source_unit,
                    pit_manifest_id=pit_input.pit_manifest_id,
                    pit_manifest_hash=pit_input.pit_manifest_hash,
                    selected_member_id=member.selected_member_id,
                    selected_member_version=member.selected_member_version,
                    selected_member_content_hash=member.selected_member_content_hash,
                    source_fact_id=member.source_fact_id,
                    source_fact_version=member.source_fact_version,
                    source_fact_content_hash=member.source_fact_content_hash,
                    computation_evidence=computation,
                    effective_at=member.source_effective_at,
                    available_at=member.source_available_at,
                    vintage_id=member.vintage_id,
                    vintage_version=member.vintage_version,
                    vintage_content_hash=member.vintage_content_hash,
                )
            )
    return tuple(predictions)


def _selected_versions_from_evidence(
    selections: tuple[ManifestSelectedVersionEvidence, ...],
) -> tuple[BaselinePITSelectedVersion, ...]:
    return tuple(
        sorted(
            (
                BaselinePITSelectedVersion(
                    selected_member_id=item.member.stable_id,
                    selected_member_version=item.member.version,
                    selected_member_content_hash=item.member.content_hash,
                    source_fact_id=item.upstream_fact.stable_id,
                    source_fact_version=item.upstream_fact.version,
                    source_fact_content_hash=item.upstream_fact.content_hash,
                    vintage_id=item.vintage.stable_id,
                    vintage_version=item.vintage.version,
                    vintage_content_hash=item.vintage.content_hash,
                )
                for item in selections
            ),
            key=lambda item: item.identity_tuple,
        )
    )


def _materialize_member_for_spec(
    spec: ForecastBaselineSpec,
    schedule: ForecastCalendarScheduleEvidence,
    metric_code: str,
    unit: str,
    member: BaselinePITMemberEvidence,
    forecast_origin_at: datetime,
) -> BaselinePITManifestMember:
    if (
        member.metric_code != metric_code
        or member.source_unit != unit
        or member.source_available_at > forecast_origin_at
    ):
        raise ForecastBaselineEvidenceError("artifact baseline source is invalid")
    _validate_source_period(
        family=spec.family,
        seasonal_lag_periods=spec.seasonal_lag_periods,
        schedule=schedule,
        target_period_end=member.target_period_end,
        source_period_end=member.source_period_end,
    )
    return BaselinePITManifestMember(
        target_period_end=member.target_period_end,
        source_period_end=member.source_period_end,
        metric_code=member.metric_code,
        selected_member_id=member.member.stable_id,
        selected_member_version=member.member.version,
        selected_member_content_hash=member.member.content_hash,
        source_value=member.source_value,
        source_unit=member.source_unit,
        source_effective_at=member.source_effective_at,
        source_available_at=member.source_available_at,
        source_fact_id=member.upstream_fact.stable_id,
        source_fact_version=member.upstream_fact.version,
        source_fact_content_hash=member.upstream_fact.content_hash,
        vintage_id=member.vintage.stable_id,
        vintage_version=member.vintage.version,
        vintage_content_hash=member.vintage.content_hash,
    )


def _validate_source_period(
    *,
    family: BaselineFamily,
    seasonal_lag_periods: int | None,
    schedule: ForecastCalendarScheduleEvidence,
    target_period_end: date,
    source_period_end: date,
) -> None:
    if family is BaselineFamily.EXTERNAL_CONSENSUS:
        if seasonal_lag_periods is not None or source_period_end != target_period_end:
            raise ForecastBaselineEvidenceError("consensus source target period mismatch")
        return
    if family is not BaselineFamily.SEASONAL_NAIVE:
        raise ForecastBaselineEvidenceError("baseline family selection is unsupported")
    if (
        isinstance(seasonal_lag_periods, bool)
        or seasonal_lag_periods is None
        or seasonal_lag_periods < 1
    ):
        raise ForecastBaselineEvidenceError("seasonal lag parameter is invalid")
    target = next(
        (item for item in schedule.periods if item.period_end == target_period_end),
        None,
    )
    source = (
        next(
            (
                item
                for item in schedule.periods
                if item.ordinal == target.ordinal - seasonal_lag_periods
            ),
            None,
        )
        if target is not None
        else None
    )
    if source is None or source.period_end != source_period_end:
        raise ForecastBaselineEvidenceError("seasonal source does not match approved lag")


def _validate_approval(
    command: MaterializeForecastBaselineSpecCommand,
    approval: BaselineApprovalEvidence,
) -> None:
    if (
        approval.approval.version_ref != command.approval_ref
        or approval.spec_ref != command.output_spec_ref
        or approval.approval_owner != "equity"
        or approval.approval_status is not BaselineApprovalStatus.APPROVED
    ):
        raise ForecastBaselineEvidenceError("baseline approval identity is invalid")
    if not approval.approved_at <= command.as_of < approval.valid_until:
        raise ForecastBaselineEvidenceError("baseline approval is inactive at command as_of")
    if not approval.approved_at <= approval.forecast_origin_at < approval.valid_until:
        raise ForecastBaselineEvidenceError("forecast origin is outside approval validity")


def _materialize_pit_evidence(
    approval: BaselineApprovalEvidence,
    bundle: BaselinePITBundle,
) -> tuple[ForecastCalendarScheduleEvidence, tuple[BaselinePITInputSpec, ...]]:
    if (
        bundle.family is not approval.family
        or bundle.computation_method is not approval.computation_method
        or bundle.computation_code_version != approval.computation_code_version
        or bundle.family_parameter_version != approval.family_parameter_version
        or bundle.family_parameter_hash != approval.family_parameter_hash
        or bundle.seasonal_lag_periods != approval.seasonal_lag_periods
        or bundle.calendar.owner != "data_center"
        or bundle.calendar.identity != approval.calendar
    ):
        raise ForecastBaselineEvidenceError("baseline PIT bundle identity is invalid")
    schedule = ForecastCalendarScheduleEvidence.create(
        owner=bundle.calendar.owner,
        calendar_id=bundle.calendar.identity.stable_id,
        calendar_version=bundle.calendar.identity.version,
        calendar_content_hash=bundle.calendar.identity.content_hash,
        periods=tuple(
            ForecastCalendarPeriod(period_end=item.period_end, ordinal=item.ordinal)
            for item in bundle.calendar.periods
        ),
    )
    requested = {item.input_role: item for item in approval.pit_inputs}
    resolved = {item.input_role: item for item in bundle.inputs}
    if (
        len(requested) != len(approval.pit_inputs)
        or len(resolved) != len(bundle.inputs)
        or set(resolved) != set(requested)
    ):
        raise ForecastBaselineEvidenceError("baseline PIT input roles were substituted")
    domain_inputs: list[BaselinePITInputSpec] = []
    for role in sorted(requested):
        request = requested[role]
        snapshot = resolved[role]
        if (
            snapshot.dataset != request.dataset
            or snapshot.metric_code != request.metric_code
            or snapshot.unit != request.unit
            or snapshot.knowledge_scope != request.knowledge_scope
            or snapshot.manifest != request.manifest
        ):
            raise ForecastBaselineEvidenceError("baseline PIT manifest identity mismatch")
        _require_aware(snapshot.as_of_time, "manifest as_of_time")
        _require_aware(snapshot.produced_at, "manifest produced_at")
        _require_token(snapshot.knowledge_scope, "manifest knowledge_scope")
        if (
            snapshot.as_of_time > approval.forecast_origin_at
            or snapshot.produced_at > approval.forecast_origin_at
            or snapshot.as_of_time > snapshot.produced_at
            or any(item.source_available_at > snapshot.as_of_time for item in snapshot.members)
            or snapshot.is_verified is not True
            or snapshot.coverage_ratio != Decimal("1")
            or snapshot.missing_count != 0
            or snapshot.estimated_count != 0
            or snapshot.unknown_count != 0
        ):
            raise ForecastBaselineEvidenceError(
                "baseline PIT manifest is not complete and knowable at forecast origin"
            )
        selected_versions = tuple(
            sorted(
                (
                    BaselinePITSelectedVersion(
                        selected_member_id=item.member.stable_id,
                        selected_member_version=item.member.version,
                        selected_member_content_hash=item.member.content_hash,
                        source_fact_id=item.upstream_fact.stable_id,
                        source_fact_version=item.upstream_fact.version,
                        source_fact_content_hash=item.upstream_fact.content_hash,
                        vintage_id=item.vintage.stable_id,
                        vintage_version=item.vintage.version,
                        vintage_content_hash=item.vintage.content_hash,
                    )
                    for item in snapshot.selected_versions
                ),
                key=lambda item: item.identity_tuple,
            )
        )
        member_versions = tuple(
            sorted(
                (
                    BaselinePITSelectedVersion(
                        selected_member_id=item.member.stable_id,
                        selected_member_version=item.member.version,
                        selected_member_content_hash=item.member.content_hash,
                        source_fact_id=item.upstream_fact.stable_id,
                        source_fact_version=item.upstream_fact.version,
                        source_fact_content_hash=item.upstream_fact.content_hash,
                        vintage_id=item.vintage.stable_id,
                        vintage_version=item.vintage.version,
                        vintage_content_hash=item.vintage.content_hash,
                    )
                    for item in snapshot.members
                ),
                key=lambda item: item.identity_tuple,
            )
        )
        if selected_versions != member_versions:
            raise ForecastBaselineEvidenceError(
                "manifest selected versions do not exactly match members"
            )
        members = tuple(
            _materialize_member(approval, schedule, request, item)
            for item in sorted(snapshot.members, key=lambda member: member.target_period_end)
        )
        domain_inputs.append(
            BaselinePITInputSpec(
                input_role=role,
                dataset=request.dataset,
                metric_code=request.metric_code,
                unit=request.unit,
                pit_manifest_id=request.manifest.stable_id,
                pit_manifest_version=request.manifest.version,
                pit_manifest_hash=request.manifest.content_hash,
                manifest_as_of_time=snapshot.as_of_time,
                manifest_produced_at=snapshot.produced_at,
                manifest_knowledge_scope=snapshot.knowledge_scope,
                manifest_is_verified=snapshot.is_verified,
                manifest_coverage_ratio=snapshot.coverage_ratio,
                manifest_missing_count=snapshot.missing_count,
                manifest_estimated_count=snapshot.estimated_count,
                manifest_unknown_count=snapshot.unknown_count,
                selected_versions=selected_versions,
                selected_versions_hash=snapshot.selected_versions_hash,
                members=members,
                calendar_id=approval.calendar.stable_id,
                calendar_version=approval.calendar.version,
                calendar_content_hash=approval.calendar.content_hash,
            )
        )
    return schedule, tuple(domain_inputs)


def _materialize_member(
    approval: BaselineApprovalEvidence,
    schedule: ForecastCalendarScheduleEvidence,
    request: ApprovedPITInputEvidence,
    member: BaselinePITMemberEvidence,
) -> BaselinePITManifestMember:
    if member.metric_code != request.metric_code or member.source_unit != request.unit:
        raise ForecastBaselineEvidenceError("baseline source metric or unit mismatch")
    if member.source_available_at > approval.forecast_origin_at:
        raise ForecastBaselineEvidenceError("baseline source was unavailable at forecast origin")
    if approval.family is BaselineFamily.SEASONAL_NAIVE:
        lag_periods = approval.seasonal_lag_periods
        if isinstance(lag_periods, bool) or lag_periods is None or lag_periods < 1:
            raise ForecastBaselineEvidenceError("seasonal lag parameter is invalid")
        target = next(
            (
                period
                for period in schedule.periods
                if period.period_end == member.target_period_end
            ),
            None,
        )
        if target is None:
            raise ForecastBaselineEvidenceError("seasonal target is absent from calendar")
        source_ordinal = target.ordinal - lag_periods
        expected_source = next(
            (period for period in schedule.periods if period.ordinal == source_ordinal),
            None,
        )
        if expected_source is None:
            raise ForecastBaselineEvidenceError("seasonal source ordinal is absent from calendar")
        expected_source_period = expected_source.period_end
        if member.source_period_end != expected_source_period:
            raise ForecastBaselineEvidenceError("seasonal source does not match approved lag")
    elif approval.family is BaselineFamily.EXTERNAL_CONSENSUS:
        if approval.seasonal_lag_periods is not None:
            raise ForecastBaselineEvidenceError("consensus cannot carry seasonal lag")
        if member.source_period_end != member.target_period_end:
            raise ForecastBaselineEvidenceError("consensus source target period mismatch")
    else:
        raise ForecastBaselineEvidenceError("baseline family selection is unsupported")
    return BaselinePITManifestMember(
        target_period_end=member.target_period_end,
        source_period_end=member.source_period_end,
        metric_code=member.metric_code,
        selected_member_id=member.member.stable_id,
        selected_member_version=member.member.version,
        selected_member_content_hash=member.member.content_hash,
        source_value=member.source_value,
        source_unit=member.source_unit,
        source_effective_at=member.source_effective_at,
        source_available_at=member.source_available_at,
        source_fact_id=member.upstream_fact.stable_id,
        source_fact_version=member.upstream_fact.version,
        source_fact_content_hash=member.upstream_fact.content_hash,
        vintage_id=member.vintage.stable_id,
        vintage_version=member.vintage.version,
        vintage_content_hash=member.vintage.content_hash,
    )


def _materialize_cost_rule(evidence: ApprovedCostRuleEvidence) -> BaselineCostRule:
    model = evidence.cost_model
    return BaselineCostRule(
        applicability=evidence.applicability,
        cost_model_version=(model.version if model is not None else ""),
        cost_model_content_hash=(model.content_hash if model is not None else ""),
        not_applicable_reason=evidence.not_applicable_reason,
    )


__all__ = [
    "ApprovedCostRuleEvidence",
    "ApprovedInvalidationRuleEvidence",
    "ApprovedMetricRuleEvidence",
    "ApprovedPITInputEvidence",
    "BaselineApprovalEvidence",
    "BaselineApprovalEvidenceProvider",
    "BaselinePITBundle",
    "BaselinePITEvidenceProvider",
    "BaselinePITInputSnapshot",
    "BaselinePITMemberEvidence",
    "BuildForecastBaselineArtifactCommand",
    "BuildForecastBaselineArtifactUseCase",
    "CalendarPeriodEvidence",
    "CalendarScheduleSnapshot",
    "EvidenceIdentity",
    "ForecastBaselineEvidenceError",
    "ForecastBaselineSpecRepository",
    "MaterializeForecastBaselineSpecCommand",
    "MaterializeForecastBaselineSpecUseCase",
    "ManifestSelectedVersionEvidence",
    "NumericEvidenceIdentity",
    "OperatingForecastEvidenceProvider",
    "OperatingForecastRef",
    "OperatingForecastSnapshot",
    "VersionRef",
]
