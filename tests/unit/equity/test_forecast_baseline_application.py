"""Application contract tests for R1 forecast-baseline materialization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.equity.application.forecast_baseline import (
    ApprovedCostRuleEvidence,
    ApprovedMetricRuleEvidence,
    ApprovedPITInputEvidence,
    BaselineApprovalEvidence,
    BaselinePITBundle,
    BaselinePITInputSnapshot,
    BaselinePITMemberEvidence,
    BuildForecastBaselineArtifactCommand,
    BuildForecastBaselineArtifactUseCase,
    CalendarPeriodEvidence,
    CalendarScheduleSnapshot,
    EvaluateForecastBaselineTrialCommand,
    EvaluateForecastBaselineTrialUseCase,
    EvaluationActualManifestSnapshot,
    EvidenceIdentity,
    ForecastBaselineEvidenceError,
    ManifestSelectedVersionEvidence,
    MaterializeForecastBaselineSpecCommand,
    MaterializeForecastBaselineSpecUseCase,
    NumericEvidenceIdentity,
    OperatingForecastRef,
    OperatingForecastSnapshot,
    ResearchTrialEvidence,
    VersionRef,
)
from apps.equity.domain.forecast_baseline import (
    ActualFactObservation,
    ActualRevisionRule,
    ActualVintageRule,
    BaselineApprovalStatus,
    BaselineComputationMethod,
    BaselineFamily,
    CostApplicability,
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
    ForecastErrorMetric,
    ForecastEvaluationPolicy,
    ForecastFreezeRule,
    ForecastScenario,
    InvalidationApplicability,
    MapeZeroActualRule,
    SensitivityArtifactReference,
    TieBreakRule,
)
from apps.equity.domain.operating_forecast import (
    ForecastInputKind,
    OperatingFactEvidence,
    OperatingForecastAssumption,
    OperatingForecastProjection,
    OperatingForecastSourceKind,
    OperatingForecastSourceLineageStatus,
    OperatingForecastStage,
    OperatingForecastStageValue,
    OperatingForecastVersion,
    ValuationSensitivityPoint,
)

APPROVAL_REF = VersionRef("approval:consumer", "approval.v1")
SPEC_REF = VersionRef("baseline-spec:consumer", "spec.v1")
ORIGIN = datetime(2025, 1, 26, 9, tzinfo=UTC)
COMMAND_AS_OF = ORIGIN + timedelta(days=1)
SOURCE_PERIOD = date(2024, 1, 27)
TARGET_PERIOD = date(2025, 2, 22)


def _identity(name: str, character: str) -> EvidenceIdentity:
    return EvidenceIdentity(name, f"{name}.v1", character * 64)


MANIFEST = _identity("manifest:revenue", "1")
CALENDAR = _identity("calendar:fiscal-53-week", "2")
MEMBER = _identity("member:revenue:target", "3")
FACT = _identity("fact:revenue:source", "4")
VINTAGE = _identity("vintage:revenue:source", "5")


def _evaluation_policy() -> ForecastEvaluationPolicy:
    return ForecastEvaluationPolicy.create(
        policy_id="evaluation-policy:consumer",
        policy_version="policy.v1",
        owner="equity",
        actual_dataset="research.operating-actual.v1",
        actual_knowledge_scope="public",
        actual_revision_rule=ActualRevisionRule.FIRST_PUBLICATION,
        actual_vintage_rule=ActualVintageRule.MANIFEST_AS_OF,
        forecast_freeze_rule=ForecastFreezeRule.PERSISTED_BY_DEADLINE,
        forecast_knowledge_cutoff_at=ORIGIN,
        forecast_submission_deadline_at=ORIGIN + timedelta(hours=23),
        valid_until=datetime(2026, 1, 1, 9, tzinfo=UTC),
    )


def _selection(
    *,
    member: EvidenceIdentity = MEMBER,
    fact: EvidenceIdentity = FACT,
    vintage: EvidenceIdentity = VINTAGE,
) -> ManifestSelectedVersionEvidence:
    return ManifestSelectedVersionEvidence(
        member=member,
        upstream_fact=fact,
        vintage=vintage,
    )


def _selection_hash(
    selections: tuple[ManifestSelectedVersionEvidence, ...],
) -> str:
    versions = sorted(
        (
            item.member.stable_id,
            item.member.version,
            item.member.content_hash,
            item.upstream_fact.stable_id,
            item.upstream_fact.version,
            item.upstream_fact.content_hash,
            item.vintage.stable_id,
            item.vintage.version,
            item.vintage.content_hash,
        )
        for item in selections
    )
    payload = {
        "schema": "r1-baseline-selected-versions.v1",
        "versions": [list(item) for item in versions],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _approval() -> BaselineApprovalEvidence:
    return BaselineApprovalEvidence(
        approval=EvidenceIdentity(
            APPROVAL_REF.stable_id,
            APPROVAL_REF.version,
            "a" * 64,
        ),
        approval_owner="equity",
        approval_status=BaselineApprovalStatus.APPROVED,
        evaluation_policy=_evaluation_policy(),
        spec_ref=SPEC_REF,
        subject_code="600519.SH",
        industry_code="consumer-staples",
        candidate_scenario=ForecastScenario.BASE,
        horizon_quarters=1,
        family=BaselineFamily.SEASONAL_NAIVE,
        computation_method=BaselineComputationMethod.DIRECT_APPROVED_SOURCE,
        computation_code_version="equity.baseline.direct.v1",
        family_parameter_version="seasonal-53w.v1",
        family_parameter_hash="b" * 64,
        seasonal_lag_periods=5,
        pit_inputs=(
            ApprovedPITInputEvidence(
                input_role="revenue_actual",
                dataset="research.operating-observation.v1",
                metric_code="revenue",
                unit="CNY",
                knowledge_scope="public",
                manifest=MANIFEST,
            ),
        ),
        training_window_start=date(2023, 1, 1),
        training_window_end=date(2025, 1, 25),
        expected_period_ends=(TARGET_PERIOD,),
        calendar=CALENDAR,
        forecast_origin_at=ORIGIN,
        metric_rules=(
            ApprovedMetricRuleEvidence(
                metric_code="revenue",
                error_metric=ForecastErrorMetric.MAE,
                maximum_forecast_error=Decimal("5"),
                minimum_improvement=Decimal("0.5"),
                minimum_sample_count=1,
                minimum_coverage=Decimal("1"),
                mape_zero_actual_rule=MapeZeroActualRule.BLOCK,
            ),
        ),
        metric_evaluation_order=("revenue",),
        tie_break_rule=TieBreakRule.BASELINE_WINS,
        cost_rule=ApprovedCostRuleEvidence(
            applicability=CostApplicability.NOT_APPLICABLE,
            cost_model=None,
            not_applicable_reason="Forecast accuracy has no trading-cost adjustment.",
        ),
        invalidation_applicability=InvalidationApplicability.NOT_APPLICABLE,
        invalidation_rules=(),
        invalidation_not_applicable_reason="Owner approved no invalidation rule.",
        approved_at=datetime(2025, 1, 1, 9, tzinfo=UTC),
        recorded_at=datetime(2025, 1, 2, 9, tzinfo=UTC),
        valid_until=datetime(2026, 1, 1, 9, tzinfo=UTC),
    )


def _member() -> BaselinePITMemberEvidence:
    return BaselinePITMemberEvidence(
        target_period_end=TARGET_PERIOD,
        source_period_end=SOURCE_PERIOD,
        metric_code="revenue",
        member=MEMBER,
        upstream_fact=FACT,
        source_value=Decimal("100"),
        source_unit="CNY",
        source_effective_at=datetime(2024, 1, 27, 9, tzinfo=UTC),
        source_available_at=datetime(2024, 2, 1, 9, tzinfo=UTC),
        vintage=VINTAGE,
    )


def _snapshot() -> BaselinePITInputSnapshot:
    selections = (_selection(),)
    return BaselinePITInputSnapshot(
        input_role="revenue_actual",
        dataset="research.operating-observation.v1",
        metric_code="revenue",
        unit="CNY",
        manifest=MANIFEST,
        as_of_time=datetime(2025, 1, 24, 9, tzinfo=UTC),
        produced_at=datetime(2025, 1, 25, 9, tzinfo=UTC),
        knowledge_scope="public",
        is_verified=True,
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        selected_versions=selections,
        selected_versions_hash=_selection_hash(selections),
        members=(_member(),),
    )


def _bundle() -> BaselinePITBundle:
    return BaselinePITBundle(
        family=BaselineFamily.SEASONAL_NAIVE,
        computation_method=BaselineComputationMethod.DIRECT_APPROVED_SOURCE,
        computation_code_version="equity.baseline.direct.v1",
        family_parameter_version="seasonal-53w.v1",
        family_parameter_hash="b" * 64,
        seasonal_lag_periods=5,
        inputs=(_snapshot(),),
        calendar=CalendarScheduleSnapshot(
            owner="data_center",
            identity=CALENDAR,
            periods=(
                CalendarPeriodEvidence(SOURCE_PERIOD, 0),
                CalendarPeriodEvidence(date(2024, 4, 27), 1),
                CalendarPeriodEvidence(date(2024, 7, 27), 2),
                CalendarPeriodEvidence(date(2024, 10, 26), 3),
                CalendarPeriodEvidence(date(2025, 1, 25), 4),
                CalendarPeriodEvidence(TARGET_PERIOD, 5),
            ),
        ),
    )


FORECAST_REF = OperatingForecastRef("forecast:consumer:2025-02", 1)
ARTIFACT_REF = VersionRef("baseline-artifact:consumer", "artifact.v1")
RESULT_REF = VersionRef("baseline-trial-result:consumer", "result.v1")
ACTUAL_MANIFEST_REF = VersionRef("actual-manifest:consumer", "actuals.v1")
RESEARCH_TRIAL_REF = VersionRef("research-trial:r1:consumer", "trial.v1")
EVALUATED_AT = datetime(2025, 3, 5, 9, tzinfo=UTC)


def _operating_forecast() -> OperatingForecastVersion:
    fact = OperatingFactEvidence(
        version_id=1,
        dataset="research.operating-observation.v1",
        business_key="600519.SH:revenue:2024-01-27",
        metric_code="revenue",
        subject_type="company",
        subject_code="600519.SH",
        effective_at=datetime(2024, 1, 27, 9, tzinfo=UTC),
        available_at=datetime(2024, 2, 1, 9, tzinfo=UTC),
        source_record_id="operating-fact:1",
        content_hash="6" * 64,
        value=Decimal("100"),
        unit="CNY",
    )
    assumptions = tuple(
        OperatingForecastAssumption(
            scenario=scenario,
            assumption_key="observed_revenue",
            value=fact.value,
            unit=fact.unit,
            input_kind=ForecastInputKind.OBSERVED_FACT,
            rationale="Exact observed operating fact.",
            observed_fact_version_id=fact.version_id,
            observed_metric_code=fact.metric_code,
            observed_fact_content_hash=fact.content_hash,
            observed_subject_type=fact.subject_type,
            observed_subject_code=fact.subject_code,
        )
        for scenario in ForecastScenario
    )
    projections: list[OperatingForecastProjection] = []
    for scenario, revenue, profit, cash_flow in (
        (ForecastScenario.BASE, Decimal("105"), Decimal("11"), Decimal("10")),
        (ForecastScenario.BULL, Decimal("115"), Decimal("15"), Decimal("14")),
        (ForecastScenario.BEAR, Decimal("95"), Decimal("6"), Decimal("5")),
    ):
        projections.append(
            OperatingForecastProjection(
                scenario=scenario,
                revenue=revenue,
                net_profit=profit,
                cash_flow=cash_flow,
                currency_unit="CNY",
                stage_values=(
                    OperatingForecastStageValue(
                        OperatingForecastStage.REVENUE,
                        "revenue",
                        revenue,
                        "CNY",
                    ),
                    OperatingForecastStageValue(
                        OperatingForecastStage.COST,
                        "cost",
                        Decimal("60"),
                        "CNY",
                    ),
                    OperatingForecastStageValue(
                        OperatingForecastStage.GROSS_PROFIT,
                        "gross_profit",
                        revenue - Decimal("60"),
                        "CNY",
                    ),
                    OperatingForecastStageValue(
                        OperatingForecastStage.EXPENSE,
                        "expense",
                        Decimal("20"),
                        "CNY",
                    ),
                    OperatingForecastStageValue(
                        OperatingForecastStage.NET_PROFIT,
                        "net_profit",
                        profit,
                        "CNY",
                    ),
                    OperatingForecastStageValue(
                        OperatingForecastStage.CASH_FLOW,
                        "cash_flow",
                        cash_flow,
                        "CNY",
                    ),
                ),
                sensitivities=(
                    ValuationSensitivityPoint(
                        sensitivity_key="pe_multiple",
                        input_value=Decimal("10"),
                        input_unit="multiple",
                        output_value=Decimal("1050"),
                        output_unit="CNY",
                        method_version="sensitivity.v1",
                        source_artifact_ref="valuation:worksheet:r1",
                        source_artifact_hash="7" * 64,
                    ),
                ),
            )
        )
    return OperatingForecastVersion(
        forecast_id=FORECAST_REF.stable_id,
        forecast_key="600519.SH-2025-02-22",
        forecast_version=FORECAST_REF.version,
        subject_code="600519.SH",
        industry_code="consumer-staples",
        as_of_time=ORIGIN,
        target_period_end=TARGET_PERIOD,
        horizon_quarters=1,
        methodology_ref="research-note:r1:v1",
        created_by_ref="analyst:1",
        source_kind=OperatingForecastSourceKind.INDUSTRY_TEMPLATE,
        evidence_schema_version=2,
        source_lineage_status=OperatingForecastSourceLineageStatus.TEMPLATE_BOUND,
        template_code="consumer-template",
        template_version=1,
        template_content_hash="8" * 64,
        template_run_key="consumer-template:600519:2025-02",
        template_run_version=1,
        template_run_content_hash="9" * 64,
        facts=(fact,),
        assumptions=assumptions,
        projections=tuple(projections),
    )


def _forecast_snapshot() -> OperatingForecastSnapshot:
    forecast = _operating_forecast()
    return OperatingForecastSnapshot(
        forecast=forecast,
        persisted_content_hash=forecast.content_hash,
        persisted_at=ORIGIN + timedelta(hours=2),
        template_owner="sector",
        template=NumericEvidenceIdentity(
            forecast.template_code,
            forecast.template_version,
            forecast.template_content_hash,
        ),
        template_run=NumericEvidenceIdentity(
            forecast.template_run_key,
            forecast.template_run_version,
            forecast.template_run_content_hash,
        ),
        sensitivity_evidence=(
            SensitivityArtifactReference(
                owner="valuation",
                artifact_id="valuation:worksheet:r1",
                artifact_version="sensitivity.v1",
                artifact_content_hash="7" * 64,
            ),
        ),
    )


def _actual_observation(*, revision_number: int = 1) -> ActualFactObservation:
    return ActualFactObservation.create(
        subject_code="600519.SH",
        industry_code="consumer-staples",
        dataset="research.operating-actual.v1",
        period_end=TARGET_PERIOD,
        metric_code="revenue",
        value=Decimal("104"),
        unit="CNY",
        source_fact_id="actual-fact:revenue:2025-02",
        source_fact_version="fact.v1",
        source_fact_content_hash="c" * 64,
        revision_number=revision_number,
        effective_at=datetime(2025, 2, 22, 9, tzinfo=UTC),
        available_at=datetime(2025, 3, 1, 9, tzinfo=UTC),
        vintage_id="actual-vintage:revenue:2025-02",
        vintage_version="vintage.v1",
        vintage_content_hash="d" * 64,
        pit_manifest_id=ACTUAL_MANIFEST_REF.stable_id,
        pit_manifest_hash="e" * 64,
        manifest_member_id="actual-member:revenue:2025-02",
        manifest_member_version="member.v1",
        manifest_member_content_hash="f" * 64,
        calendar_id=CALENDAR.stable_id,
        calendar_version=CALENDAR.version,
        calendar_content_hash=CALENDAR.content_hash,
    )


def _actual_snapshot(
    actual: ActualFactObservation | None = None,
) -> EvaluationActualManifestSnapshot:
    actual = actual or _actual_observation()
    selection = ManifestSelectedVersionEvidence(
        member=EvidenceIdentity(
            actual.manifest_member_id,
            actual.manifest_member_version,
            actual.manifest_member_content_hash,
        ),
        upstream_fact=EvidenceIdentity(
            actual.source_fact_id,
            actual.source_fact_version,
            actual.source_fact_content_hash,
        ),
        vintage=EvidenceIdentity(
            actual.vintage_id,
            actual.vintage_version,
            actual.vintage_content_hash,
        ),
    )
    versions = (
        (
            selection.member.stable_id,
            selection.member.version,
            selection.member.content_hash,
            selection.upstream_fact.stable_id,
            selection.upstream_fact.version,
            selection.upstream_fact.content_hash,
            selection.vintage.stable_id,
            selection.vintage.version,
            selection.vintage.content_hash,
        ),
    )
    selected_hash = hashlib.sha256(
        json.dumps(
            {
                "schema": "r1-actual-selected-versions.v1",
                "versions": [list(item) for item in versions],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return EvaluationActualManifestSnapshot(
        identity=EvidenceIdentity(
            ACTUAL_MANIFEST_REF.stable_id,
            ACTUAL_MANIFEST_REF.version,
            "e" * 64,
        ),
        owner="data_center",
        dataset="research.operating-actual.v1",
        subject_code="600519.SH",
        industry_code="consumer-staples",
        calendar=CALENDAR,
        as_of_time=datetime(2025, 3, 2, 9, tzinfo=UTC),
        produced_at=datetime(2025, 3, 3, 9, tzinfo=UTC),
        knowledge_scope="public",
        is_verified=True,
        coverage_ratio=Decimal("1"),
        missing_count=0,
        estimated_count=0,
        unknown_count=0,
        selected_versions=(selection,),
        selected_versions_hash=selected_hash,
        actuals=(actual,),
    )


def _trial_split_hash(spec: ForecastBaselineSpec) -> str:
    payload = {
        "schema": "r1-trial-split.v1",
        "training_window": [
            spec.training_window_start.isoformat(),
            spec.training_window_end.isoformat(),
        ],
        "evaluation_periods": [item.isoformat() for item in spec.expected_period_ends],
        "calendar_schedule_hash": spec.calendar_schedule.content_hash,
        "actual_selection_policy_hash": spec.evaluation_policy.policy_content_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _trial_parameter_hash(spec: ForecastBaselineSpec) -> str:
    payload = {
        "schema": "r1-trial-parameters.v1",
        "baseline_spec": [spec.spec_id, spec.spec_version, spec.content_hash],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _research_trial(spec: ForecastBaselineSpec) -> ResearchTrialEvidence:
    return ResearchTrialEvidence(
        identity=EvidenceIdentity(
            RESEARCH_TRIAL_REF.stable_id,
            RESEARCH_TRIAL_REF.version,
            "a" * 64,
        ),
        owner="research",
        capability="r1",
        purpose="valuation",
        status="running",
        split_spec_hash=_trial_split_hash(spec),
        parameter_hash=_trial_parameter_hash(spec),
        baseline_spec_ref=SPEC_REF,
        baseline_spec_content_hash=spec.content_hash,
        expected_period_ends=spec.expected_period_ends,
        metric_codes=tuple(item.metric_code for item in spec.metric_rules),
        calendar_schedule_hash=spec.calendar_schedule.content_hash,
        evaluation_policy=spec.evaluation_policy,
        baseline_spec_approved_at=spec.approved_at,
        forecast_origin_at=ORIGIN,
        activated_at=datetime(2025, 1, 2, 9, tzinfo=UTC),
        recorded_at=datetime(2025, 1, 3, 9, tzinfo=UTC),
        valid_until=datetime(2025, 12, 31, 9, tzinfo=UTC),
    )


class _ApprovalProvider:
    def __init__(self, approval: BaselineApprovalEvidence | None) -> None:
        self.approval = approval
        self.calls: list[tuple[VersionRef, datetime]] = []

    def get_approval(
        self,
        approval_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> BaselineApprovalEvidence | None:
        self.calls.append((approval_ref, as_of))
        return self.approval


class _PITProvider:
    def __init__(self, bundle: BaselinePITBundle) -> None:
        self.bundle = bundle
        self.calls: list[
            tuple[
                tuple[EvidenceIdentity, ...],
                EvidenceIdentity,
                tuple[date, ...],
                BaselineFamily,
                datetime,
            ]
        ] = []

    def get_baseline_bundle(
        self,
        *,
        manifests: tuple[EvidenceIdentity, ...],
        calendar: EvidenceIdentity,
        target_periods: tuple[date, ...],
        family: BaselineFamily,
        as_of: datetime,
    ) -> BaselinePITBundle:
        self.calls.append((manifests, calendar, target_periods, family, as_of))
        return self.bundle


class _ForecastProvider:
    def __init__(self, snapshot: OperatingForecastSnapshot | None) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[OperatingForecastRef, datetime]] = []

    def get_forecast(
        self,
        forecast_ref: OperatingForecastRef,
        *,
        as_of: datetime,
    ) -> OperatingForecastSnapshot | None:
        self.calls.append((forecast_ref, as_of))
        return self.snapshot


class _ActualProvider:
    def __init__(self, snapshot: EvaluationActualManifestSnapshot | None) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[VersionRef, datetime]] = []

    def get_actual_manifest(
        self,
        manifest_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> EvaluationActualManifestSnapshot | None:
        self.calls.append((manifest_ref, as_of))
        return self.snapshot


class _ResearchProvider:
    def __init__(self, evidence: ResearchTrialEvidence | None) -> None:
        self.evidence = evidence
        self.calls: list[tuple[VersionRef, datetime]] = []

    def get_trial(
        self,
        trial_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> ResearchTrialEvidence | None:
        self.calls.append((trial_ref, as_of))
        return self.evidence


class _Repository:
    def __init__(self) -> None:
        self.appended: list[ForecastBaselineSpec] = []
        self.artifacts: list[ForecastBaselineArtifact] = []
        self.trials: list[ForecastBaselineTrialResult] = []

    def append_spec(self, spec: ForecastBaselineSpec) -> ForecastBaselineSpec:
        self.appended.append(spec)
        return spec

    def get_spec(self, spec_ref: VersionRef) -> ForecastBaselineSpec | None:
        return next(
            (
                item
                for item in self.appended
                if (item.spec_id, item.spec_version) == (spec_ref.stable_id, spec_ref.version)
            ),
            None,
        )

    def append_artifact(
        self,
        artifact: ForecastBaselineArtifact,
    ) -> ForecastBaselineArtifact:
        self.artifacts.append(artifact)
        return artifact

    def get_artifact(
        self,
        artifact_ref: VersionRef,
    ) -> ForecastBaselineArtifact | None:
        return next(
            (
                item
                for item in self.artifacts
                if (item.artifact_id, item.artifact_version)
                == (artifact_ref.stable_id, artifact_ref.version)
            ),
            None,
        )

    def append_trial(
        self,
        trial: ForecastBaselineTrialResult,
    ) -> ForecastBaselineTrialResult:
        self.trials.append(trial)
        return trial

    def get_trial(
        self,
        trial_ref: VersionRef,
    ) -> ForecastBaselineTrialResult | None:
        return next(
            (
                item
                for item in self.trials
                if (item.result_id, item.result_version) == (trial_ref.stable_id, trial_ref.version)
            ),
            None,
        )


def _execute(
    *,
    approval: BaselineApprovalEvidence | None = None,
    bundle: BaselinePITBundle | None = None,
) -> tuple[ForecastBaselineSpec, _ApprovalProvider, _PITProvider, _Repository]:
    approval_provider = _ApprovalProvider(approval or _approval())
    pit_provider = _PITProvider(bundle or _bundle())
    repository = _Repository()
    spec = MaterializeForecastBaselineSpecUseCase(
        approval_provider=approval_provider,
        pit_provider=pit_provider,
        repository=repository,
    ).execute(
        MaterializeForecastBaselineSpecCommand(
            output_spec_ref=SPEC_REF,
            approval_ref=APPROVAL_REF,
            as_of=COMMAND_AS_OF,
        )
    )
    return spec, approval_provider, pit_provider, repository


def _build_artifact(
    *,
    approval: BaselineApprovalEvidence | None = None,
    snapshot: OperatingForecastSnapshot | None = None,
    bundle: BaselinePITBundle | None = None,
    build_as_of: datetime = COMMAND_AS_OF,
) -> tuple[
    ForecastBaselineSpec,
    ForecastBaselineArtifact,
    _ForecastProvider,
    _Repository,
]:
    spec, _, _, repository = _execute(approval=approval)
    forecast_provider = _ForecastProvider(_forecast_snapshot() if snapshot is None else snapshot)
    artifact = BuildForecastBaselineArtifactUseCase(
        forecast_provider=forecast_provider,
        pit_provider=_PITProvider(bundle or _bundle()),
        repository=repository,
    ).execute(
        BuildForecastBaselineArtifactCommand(
            output_artifact_ref=ARTIFACT_REF,
            spec_ref=SPEC_REF,
            forecast_refs=(FORECAST_REF,),
            as_of=build_as_of,
        )
    )
    return spec, artifact, forecast_provider, repository


def _evaluate_trial(
    *,
    approval: BaselineApprovalEvidence | None = None,
    actual_snapshot: EvaluationActualManifestSnapshot | None = None,
    research_evidence: ResearchTrialEvidence | None = None,
) -> tuple[
    ForecastBaselineSpec,
    ForecastBaselineArtifact,
    ForecastBaselineTrialResult,
    _ActualProvider,
    _ResearchProvider,
    _Repository,
]:
    spec, artifact, _, repository = _build_artifact(approval=approval)
    actual_provider = _ActualProvider(
        _actual_snapshot() if actual_snapshot is None else actual_snapshot
    )
    research_provider = _ResearchProvider(
        _research_trial(spec) if research_evidence is None else research_evidence
    )
    result = EvaluateForecastBaselineTrialUseCase(
        actual_provider=actual_provider,
        research_trial_provider=research_provider,
        repository=repository,
    ).execute(
        EvaluateForecastBaselineTrialCommand(
            output_trial_ref=RESULT_REF,
            spec_ref=SPEC_REF,
            artifact_ref=ARTIFACT_REF,
            actual_manifest_ref=ACTUAL_MANIFEST_REF,
            research_trial_ref=RESEARCH_TRIAL_REF,
            as_of=EVALUATED_AT,
        )
    )
    return (
        spec,
        artifact,
        result,
        actual_provider,
        research_provider,
        repository,
    )


def test_materialize_is_id_only_and_preserves_exact_evidence() -> None:
    spec, approval_provider, pit_provider, repository = _execute()

    assert tuple(item.name for item in fields(MaterializeForecastBaselineSpecCommand)) == (
        "output_spec_ref",
        "approval_ref",
        "as_of",
    )
    assert approval_provider.calls == [(APPROVAL_REF, COMMAND_AS_OF)]
    assert pit_provider.calls == [
        ((MANIFEST,), CALENDAR, (TARGET_PERIOD,), BaselineFamily.SEASONAL_NAIVE, COMMAND_AS_OF)
    ]
    assert repository.appended == [spec]
    assert spec.approved_at == _approval().approved_at
    assert spec.family_parameter_version == "seasonal-53w.v1"
    assert spec.seasonal_lag_periods == 5
    pit_input = spec.pit_inputs[0]
    assert pit_input.manifest_as_of_time == _snapshot().as_of_time
    assert pit_input.manifest_produced_at == _snapshot().produced_at
    assert pit_input.members[0].source_period_end == SOURCE_PERIOD
    assert pit_input.members[0].source_fact_id == FACT.stable_id
    assert pit_input.members[0].vintage_id == VINTAGE.stable_id


def test_seasonal_source_uses_non_calendar_schedule_ordinal() -> None:
    spec, *_ = _execute()

    assert TARGET_PERIOD.month != SOURCE_PERIOD.month
    assert spec.pit_inputs[0].members[0].source_period_end == SOURCE_PERIOD


@pytest.mark.parametrize(
    "bundle",
    (
        replace(_bundle(), family_parameter_hash="f" * 64),
        replace(_bundle(), seasonal_lag_periods=4),
    ),
)
def test_family_parameter_substitution_fails_closed(bundle: BaselinePITBundle) -> None:
    with pytest.raises(ForecastBaselineEvidenceError, match="bundle identity"):
        _execute(bundle=bundle)


def test_missing_schedule_source_ordinal_fails_closed() -> None:
    approval = replace(_approval(), seasonal_lag_periods=6)
    bundle = replace(_bundle(), seasonal_lag_periods=6)

    with pytest.raises(ForecastBaselineEvidenceError, match="source ordinal"):
        _execute(approval=approval, bundle=bundle)


@pytest.mark.parametrize(
    "snapshot",
    (
        replace(_snapshot(), is_verified=False),
        replace(_snapshot(), coverage_ratio=Decimal("0.99")),
        replace(_snapshot(), missing_count=1),
        replace(_snapshot(), estimated_count=1),
        replace(_snapshot(), unknown_count=1),
        replace(_snapshot(), as_of_time=ORIGIN + timedelta(seconds=1)),
        replace(_snapshot(), produced_at=ORIGIN + timedelta(seconds=1)),
    ),
)
def test_manifest_quality_and_origin_cutoff_fail_closed(
    snapshot: BaselinePITInputSnapshot,
) -> None:
    with pytest.raises(ForecastBaselineEvidenceError, match="complete and knowable"):
        _execute(bundle=replace(_bundle(), inputs=(snapshot,)))


def test_manifest_time_chain_accepts_equality() -> None:
    member = replace(_member(), source_available_at=ORIGIN)
    snapshot = replace(
        _snapshot(),
        as_of_time=ORIGIN,
        produced_at=ORIGIN,
        members=(member,),
    )

    spec, *_ = _execute(bundle=replace(_bundle(), inputs=(snapshot,)))

    assert spec.pit_inputs[0].manifest_produced_at == ORIGIN


def test_manifest_rejects_fact_after_as_of_and_produced_before_as_of() -> None:
    after_as_of = replace(
        _snapshot(),
        members=(
            replace(
                _member(),
                source_available_at=_snapshot().as_of_time + timedelta(seconds=1),
            ),
        ),
    )
    with pytest.raises(ForecastBaselineEvidenceError, match="complete and knowable"):
        _execute(bundle=replace(_bundle(), inputs=(after_as_of,)))

    backwards = replace(
        _snapshot(),
        produced_at=_snapshot().as_of_time - timedelta(seconds=1),
    )
    with pytest.raises(ForecastBaselineEvidenceError, match="complete and knowable"):
        _execute(bundle=replace(_bundle(), inputs=(backwards,)))


def test_manifest_selected_versions_reject_fact_or_vintage_substitution() -> None:
    changed_fact = replace(_member(), upstream_fact=_identity("fact:other", "8"))
    changed_vintage = replace(_member(), vintage=_identity("vintage:other", "9"))

    for changed_member in (changed_fact, changed_vintage):
        snapshot = replace(_snapshot(), members=(changed_member,))
        with pytest.raises(ForecastBaselineEvidenceError, match="selected versions"):
            _execute(bundle=replace(_bundle(), inputs=(snapshot,)))


def test_missing_or_substituted_approval_fails_before_pit_read() -> None:
    approval_provider = _ApprovalProvider(None)
    pit_provider = _PITProvider(_bundle())
    repository = _Repository()
    use_case = MaterializeForecastBaselineSpecUseCase(
        approval_provider=approval_provider,
        pit_provider=pit_provider,
        repository=repository,
    )
    command = MaterializeForecastBaselineSpecCommand(SPEC_REF, APPROVAL_REF, COMMAND_AS_OF)

    with pytest.raises(ForecastBaselineEvidenceError, match="missing"):
        use_case.execute(command)
    assert pit_provider.calls == []

    substituted = replace(_approval(), approval=_identity("approval:other", "c"))
    with pytest.raises(ForecastBaselineEvidenceError, match="identity"):
        _execute(approval=substituted)


def test_build_artifact_is_id_only_and_derives_projection_and_baseline() -> None:
    spec, artifact, forecast_provider, repository = _build_artifact()

    assert tuple(item.name for item in fields(BuildForecastBaselineArtifactCommand)) == (
        "output_artifact_ref",
        "spec_ref",
        "forecast_refs",
        "as_of",
    )
    assert forecast_provider.calls == [(FORECAST_REF, COMMAND_AS_OF)]
    assert artifact.spec_content_hash == spec.content_hash
    assert artifact.forecasts[0].metric_values == (("revenue", Decimal("105")),)
    assert artifact.forecasts[0].template_run_content_hash == "9" * 64
    assert artifact.forecasts[0].sensitivity_artifacts[0].artifact_content_hash == "7" * 64
    assert artifact.predictions[0].value == Decimal("100")
    assert artifact.predictions[0].source_fact_id == FACT.stable_id
    assert repository.artifacts == [artifact]


@pytest.mark.parametrize(
    "snapshot",
    (
        replace(_forecast_snapshot(), persisted_content_hash="f" * 64),
        replace(_forecast_snapshot(), template_owner="equity"),
        replace(
            _forecast_snapshot(),
            template=NumericEvidenceIdentity("wrong-template", 1, "8" * 64),
        ),
        replace(
            _forecast_snapshot(),
            template_run=NumericEvidenceIdentity("wrong-run", 1, "9" * 64),
        ),
        replace(
            _forecast_snapshot(),
            sensitivity_evidence=(
                SensitivityArtifactReference(
                    owner="sector",
                    artifact_id="valuation:worksheet:r1",
                    artifact_version="sensitivity.v1",
                    artifact_content_hash="7" * 64,
                ),
            ),
        ),
    ),
)
def test_build_rejects_forecast_template_run_or_sensitivity_substitution(
    snapshot: OperatingForecastSnapshot,
) -> None:
    with pytest.raises(ForecastBaselineEvidenceError, match="substituted"):
        _build_artifact(snapshot=snapshot)


def test_build_enforces_persistence_cutoff_and_submission_deadline() -> None:
    policy = _evaluation_policy()
    after_deadline = replace(
        _forecast_snapshot(),
        persisted_at=policy.forecast_submission_deadline_at + timedelta(seconds=1),
    )
    with pytest.raises(ForecastBaselineEvidenceError, match="substituted"):
        _build_artifact(snapshot=after_deadline)

    after_request_cutoff = replace(
        _forecast_snapshot(),
        persisted_at=ORIGIN + timedelta(hours=4),
    )
    with pytest.raises(ForecastBaselineEvidenceError, match="substituted"):
        _build_artifact(
            snapshot=after_request_cutoff,
            build_as_of=ORIGIN + timedelta(hours=3),
        )

    at_deadline = replace(
        _forecast_snapshot(),
        persisted_at=policy.forecast_submission_deadline_at,
    )
    _, artifact, *_ = _build_artifact(snapshot=at_deadline)
    assert artifact.forecasts[0].persisted_at == policy.forecast_submission_deadline_at


def test_build_rejects_exact_baseline_source_substitution() -> None:
    changed_member = replace(_member(), source_value=Decimal("999"))
    changed_snapshot = replace(_snapshot(), members=(changed_member,))

    with pytest.raises(ForecastBaselineEvidenceError, match="members were substituted"):
        _build_artifact(bundle=replace(_bundle(), inputs=(changed_snapshot,)))


def test_build_rejects_forecast_id_version_and_projection_unit_mismatch() -> None:
    for changed_forecast in (
        replace(_operating_forecast(), forecast_id="forecast:other"),
        replace(_operating_forecast(), forecast_version=2),
    ):
        snapshot = replace(
            _forecast_snapshot(),
            forecast=changed_forecast,
            persisted_content_hash=changed_forecast.content_hash,
        )
        with pytest.raises(ForecastBaselineEvidenceError, match="substituted"):
            _build_artifact(snapshot=snapshot)

    forecast = _operating_forecast()
    base = next(item for item in forecast.projections if item.scenario is ForecastScenario.BASE)
    usd_base = replace(
        base,
        currency_unit="USD",
        stage_values=tuple(replace(item, unit="USD") for item in base.stage_values),
    )
    changed_forecast = replace(
        forecast,
        projections=tuple(
            usd_base if item.scenario is ForecastScenario.BASE else item
            for item in forecast.projections
        ),
    )
    snapshot = replace(
        _forecast_snapshot(),
        forecast=changed_forecast,
        persisted_content_hash=changed_forecast.content_hash,
    )
    with pytest.raises(ForecastBaselineEvidenceError, match="unit mismatch"):
        _build_artifact(snapshot=snapshot)


def test_evaluate_trial_is_id_only_and_builds_paired_rows_internally() -> None:
    spec, artifact, result, actual_provider, research_provider, repository = _evaluate_trial()

    assert tuple(item.name for item in fields(EvaluateForecastBaselineTrialCommand)) == (
        "output_trial_ref",
        "spec_ref",
        "artifact_ref",
        "actual_manifest_ref",
        "research_trial_ref",
        "as_of",
    )
    assert actual_provider.calls == [(ACTUAL_MANIFEST_REF, EVALUATED_AT)]
    assert research_provider.calls == [(RESEARCH_TRIAL_REF, EVALUATED_AT)]
    assert result.spec_content_hash == spec.content_hash
    assert result.baseline_artifact_content_hash == artifact.content_hash
    assert result.research_trial.trial_version == RESEARCH_TRIAL_REF.version
    assert result.research_trial.evaluation_policy == spec.evaluation_policy
    assert result.actual_manifest.dataset == "research.operating-actual.v1"
    assert (
        result.actual_manifest.selected_versions_hash == _actual_snapshot().selected_versions_hash
    )
    assert result.paired_rows[0].forecast_value == Decimal("105")
    assert result.paired_rows[0].baseline_value == Decimal("100")
    assert result.paired_rows[0].actual.value == Decimal("104")
    assert repository.trials == [result]


@pytest.mark.parametrize(
    "snapshot",
    (
        replace(_actual_snapshot(), owner="equity"),
        replace(_actual_snapshot(), dataset="research.other-actual.v1"),
        replace(_actual_snapshot(), subject_code="000001.SZ"),
        replace(_actual_snapshot(), industry_code="other-industry"),
        replace(_actual_snapshot(), calendar=_identity("calendar:other", "b")),
        replace(_actual_snapshot(), knowledge_scope="system"),
        replace(_actual_snapshot(), is_verified=False),
        replace(_actual_snapshot(), coverage_ratio=Decimal("0.9")),
        replace(_actual_snapshot(), missing_count=1),
        replace(
            _actual_snapshot(),
            produced_at=_actual_snapshot().as_of_time - timedelta(seconds=1),
        ),
        replace(_actual_snapshot(), produced_at=EVALUATED_AT + timedelta(seconds=1)),
    ),
)
def test_evaluate_rejects_actual_manifest_scope_quality_or_time_substitution(
    snapshot: EvaluationActualManifestSnapshot,
) -> None:
    with pytest.raises(ForecastBaselineEvidenceError, match="actual manifest is invalid"):
        _evaluate_trial(actual_snapshot=snapshot)


def test_evaluate_rejects_actual_revision_or_selected_vintage_substitution() -> None:
    revised = _actual_snapshot(_actual_observation(revision_number=2))
    with pytest.raises(ForecastBaselineEvidenceError, match="actual manifest is invalid"):
        _evaluate_trial(actual_snapshot=revised)

    changed_actual = ActualFactObservation.create(
        **{
            **{
                field.name: getattr(_actual_observation(), field.name)
                for field in fields(ActualFactObservation)
                if field.name != "observation_hash"
            },
            "vintage_id": "actual-vintage:substituted",
        }
    )
    selected_stale = replace(_actual_snapshot(), actuals=(changed_actual,))
    with pytest.raises(ForecastBaselineEvidenceError, match="selected versions"):
        _evaluate_trial(actual_snapshot=selected_stale)


def test_evaluate_rejects_duplicate_actual_identity_across_metric_keys() -> None:
    snapshot = _actual_snapshot()
    first = snapshot.actuals[0]
    duplicate = ActualFactObservation.create(
        **{
            **{
                field.name: getattr(first, field.name)
                for field in fields(ActualFactObservation)
                if field.name not in {"observation_hash", "metric_code", "value"}
            },
            "metric_code": "net_profit",
            "value": Decimal("10"),
        }
    )
    selection = snapshot.selected_versions[0]
    identity = [
        selection.member.stable_id,
        selection.member.version,
        selection.member.content_hash,
        selection.upstream_fact.stable_id,
        selection.upstream_fact.version,
        selection.upstream_fact.content_hash,
        selection.vintage.stable_id,
        selection.vintage.version,
        selection.vintage.content_hash,
    ]
    selected_hash = hashlib.sha256(
        json.dumps(
            {
                "schema": "r1-actual-selected-versions.v1",
                "versions": [identity, identity],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    duplicate_snapshot = replace(
        snapshot,
        actuals=(first, duplicate),
        selected_versions=(selection, selection),
        selected_versions_hash=selected_hash,
    )

    with pytest.raises(ForecastBaselineEvidenceError, match="not unique"):
        _evaluate_trial(actual_snapshot=duplicate_snapshot)


def test_evaluate_rejects_research_scope_status_expiry_and_spec_substitution() -> None:
    spec, *_ = _build_artifact()
    evidence = _research_trial(spec)
    substitutions = (
        replace(evidence, capability="r2"),
        replace(evidence, purpose="portfolio"),
        replace(evidence, status="completed"),
        replace(evidence, baseline_spec_content_hash="f" * 64),
        replace(evidence, split_spec_hash="e" * 64),
        replace(evidence, parameter_hash="d" * 64),
        replace(evidence, valid_until=EVALUATED_AT),
    )

    for changed in substitutions:
        with pytest.raises(ForecastBaselineEvidenceError, match="authorization is invalid"):
            _evaluate_trial(research_evidence=changed)


def test_research_trial_must_be_recorded_before_forecast_origin() -> None:
    spec, *_ = _build_artifact()
    evidence = _research_trial(spec)
    accepted = replace(evidence, activated_at=ORIGIN, recorded_at=ORIGIN)
    _, _, result, *_ = _evaluate_trial(research_evidence=accepted)
    assert result.research_trial.recorded_at == ORIGIN

    late = replace(
        evidence,
        activated_at=ORIGIN + timedelta(seconds=1),
        recorded_at=ORIGIN + timedelta(seconds=2),
    )
    with pytest.raises(ForecastBaselineEvidenceError, match="authorization is invalid"):
        _evaluate_trial(research_evidence=late)
