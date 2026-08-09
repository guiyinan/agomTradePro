"""R1 exact-actual and Research-authorized trial evaluation use case."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.equity.application.forecast_baseline_materialize_contracts import _require_aware
from apps.equity.domain.forecast_baseline import (
    ActualFactObservation,
    BaselinePITSelectedVersion,
    EvaluationActualManifest,
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
    ForecastBaselineTrialResult,
    ForecastEvaluationPolicy,
    PairedForecastBaselineRow,
    ResearchTrialAuthorization,
)

from .forecast_baseline_materialize import (
    EvidenceIdentity,
    ForecastBaselineEvidenceError,
    ForecastBaselineSpecRepository,
    ManifestSelectedVersionEvidence,
    VersionRef,
    _selected_versions_from_evidence,
)


@dataclass(frozen=True)
class EvaluationActualManifestSnapshot:
    """Exact Data Center actual manifest projection resolved by identity."""

    identity: EvidenceIdentity
    owner: str
    dataset: str
    subject_code: str
    industry_code: str
    calendar: EvidenceIdentity
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
    actuals: tuple[ActualFactObservation, ...]


@dataclass(frozen=True)
class ResearchTrialEvidence:
    """Exact pre-registered Research trial authorization for R1 valuation."""

    identity: EvidenceIdentity
    owner: str
    capability: str
    purpose: str
    status: str
    split_spec_hash: str
    parameter_hash: str
    baseline_spec_ref: VersionRef
    baseline_spec_content_hash: str
    expected_period_ends: tuple[date, ...]
    metric_codes: tuple[str, ...]
    calendar_schedule_hash: str
    evaluation_policy: ForecastEvaluationPolicy
    baseline_spec_approved_at: datetime
    forecast_origin_at: datetime
    activated_at: datetime
    recorded_at: datetime
    valid_until: datetime


class EvaluationActualEvidenceProvider(Protocol):
    """Exact-read independent Data Center actual manifest evidence."""

    def get_actual_manifest(
        self,
        manifest_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> EvaluationActualManifestSnapshot | None: ...


class ResearchTrialEvidenceProvider(Protocol):
    """Exact-read pre-registered Research trial evidence."""

    def get_trial(
        self,
        trial_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> ResearchTrialEvidence | None: ...


@dataclass(frozen=True)
class EvaluateForecastBaselineTrialCommand:
    """ID-only request to evaluate one pre-registered R1 research trial."""

    output_trial_ref: VersionRef
    spec_ref: VersionRef
    artifact_ref: VersionRef
    actual_manifest_ref: VersionRef
    research_trial_ref: VersionRef
    as_of: datetime

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "command as_of")


class EvaluateForecastBaselineTrialUseCase:
    """Evaluate exact forecasts against exact actuals under Research authority."""

    def __init__(
        self,
        *,
        actual_provider: EvaluationActualEvidenceProvider,
        research_trial_provider: ResearchTrialEvidenceProvider,
        repository: ForecastBaselineSpecRepository,
    ) -> None:
        self._actual_provider = actual_provider
        self._research_trial_provider = research_trial_provider
        self._repository = repository

    def execute(
        self,
        command: EvaluateForecastBaselineTrialCommand,
    ) -> ForecastBaselineTrialResult:
        """Create paired rows internally and append a recomputed trial result."""

        spec = self._repository.get_spec(command.spec_ref)
        artifact = self._repository.get_artifact(command.artifact_ref)
        if spec is None or (spec.spec_id, spec.spec_version) != (
            command.spec_ref.stable_id,
            command.spec_ref.version,
        ):
            raise ForecastBaselineEvidenceError("exact baseline spec is unavailable")
        if artifact is None or (artifact.artifact_id, artifact.artifact_version) != (
            command.artifact_ref.stable_id,
            command.artifact_ref.version,
        ):
            raise ForecastBaselineEvidenceError("exact baseline artifact is unavailable")
        if (
            artifact.spec_id != spec.spec_id
            or artifact.spec_version != spec.spec_version
            or artifact.spec_content_hash != spec.content_hash
            or artifact.evaluation_policy != spec.evaluation_policy
        ):
            raise ForecastBaselineEvidenceError("baseline artifact was substituted")
        actual_snapshot = self._actual_provider.get_actual_manifest(
            command.actual_manifest_ref,
            as_of=command.as_of,
        )
        if actual_snapshot is None:
            raise ForecastBaselineEvidenceError("exact evaluation actual manifest is unavailable")
        actual_manifest = _materialize_actual_manifest(command, spec, actual_snapshot)
        trial_evidence = self._research_trial_provider.get_trial(
            command.research_trial_ref,
            as_of=command.as_of,
        )
        if trial_evidence is None:
            raise ForecastBaselineEvidenceError("exact Research trial is unavailable")
        authorization = _materialize_research_authorization(
            command,
            spec,
            artifact,
            trial_evidence,
        )
        paired_rows = _materialize_paired_rows(artifact, actual_manifest)
        valid_until = min(spec.valid_until, artifact.valid_until, authorization.valid_until)
        if command.as_of >= valid_until:
            raise ForecastBaselineEvidenceError("trial authority is expired")
        result = ForecastBaselineTrialResult.create(
            result_id=command.output_trial_ref.stable_id,
            result_version=command.output_trial_ref.version,
            owner="equity",
            research_trial=authorization,
            spec=spec,
            artifact=artifact,
            paired_rows=paired_rows,
            actual_manifest=actual_manifest,
            evaluated_at=command.as_of,
            valid_until=valid_until,
        )
        persisted = self._repository.append_trial(result)
        if persisted != result:
            raise ForecastBaselineEvidenceError(
                "trial repository did not preserve the exact domain object"
            )
        return persisted


def _materialize_actual_manifest(
    command: EvaluateForecastBaselineTrialCommand,
    spec: ForecastBaselineSpec,
    snapshot: EvaluationActualManifestSnapshot,
) -> EvaluationActualManifest:
    if (
        snapshot.identity.version_ref != command.actual_manifest_ref
        or snapshot.owner != "data_center"
        or snapshot.dataset != spec.evaluation_policy.actual_dataset
        or snapshot.subject_code != spec.subject_code
        or snapshot.industry_code != spec.industry_code
        or snapshot.calendar
        != EvidenceIdentity(
            spec.calendar_schedule.calendar_id,
            spec.calendar_schedule.calendar_version,
            spec.calendar_schedule.calendar_content_hash,
        )
        or snapshot.knowledge_scope != spec.evaluation_policy.actual_knowledge_scope
        or snapshot.as_of_time > snapshot.produced_at
        or snapshot.produced_at > command.as_of
        or snapshot.is_verified is not True
        or snapshot.coverage_ratio != Decimal("1")
        or snapshot.missing_count != 0
        or snapshot.estimated_count != 0
        or snapshot.unknown_count != 0
        or any(item.available_at > snapshot.as_of_time for item in snapshot.actuals)
        or any(
            item.dataset != snapshot.dataset or item.revision_number != 1
            for item in snapshot.actuals
        )
    ):
        raise ForecastBaselineEvidenceError("evaluation actual manifest is invalid")
    selected_versions = _selected_versions_from_evidence(snapshot.selected_versions)
    selected_identity_tuples = tuple(item.identity_tuple for item in selected_versions)
    actual_member_ids = tuple(
        (item.manifest_member_id, item.manifest_member_version) for item in snapshot.actuals
    )
    actual_fact_ids = tuple(
        (item.source_fact_id, item.source_fact_version) for item in snapshot.actuals
    )
    actual_vintage_ids = tuple((item.vintage_id, item.vintage_version) for item in snapshot.actuals)
    if (
        len(selected_identity_tuples) != len(set(selected_identity_tuples))
        or len(actual_member_ids) != len(set(actual_member_ids))
        or len(actual_fact_ids) != len(set(actual_fact_ids))
        or len(actual_vintage_ids) != len(set(actual_vintage_ids))
    ):
        raise ForecastBaselineEvidenceError("actual selected versions are not unique")
    member_versions = tuple(
        sorted(
            (
                BaselinePITSelectedVersion(
                    selected_member_id=item.manifest_member_id,
                    selected_member_version=item.manifest_member_version,
                    selected_member_content_hash=item.manifest_member_content_hash,
                    source_fact_id=item.source_fact_id,
                    source_fact_version=item.source_fact_version,
                    source_fact_content_hash=item.source_fact_content_hash,
                    vintage_id=item.vintage_id,
                    vintage_version=item.vintage_version,
                    vintage_content_hash=item.vintage_content_hash,
                )
                for item in snapshot.actuals
            ),
            key=lambda item: item.identity_tuple,
        )
    )
    if selected_versions != member_versions:
        raise ForecastBaselineEvidenceError("actual selected versions were substituted")
    return EvaluationActualManifest.create(
        manifest_id=snapshot.identity.stable_id,
        manifest_version=snapshot.identity.version,
        manifest_content_hash=snapshot.identity.content_hash,
        owner=snapshot.owner,
        subject_code=snapshot.subject_code,
        industry_code=snapshot.industry_code,
        dataset=snapshot.dataset,
        calendar_id=snapshot.calendar.stable_id,
        calendar_version=snapshot.calendar.version,
        calendar_content_hash=snapshot.calendar.content_hash,
        as_of_time=snapshot.as_of_time,
        produced_at=snapshot.produced_at,
        knowledge_scope=snapshot.knowledge_scope,
        is_verified=snapshot.is_verified,
        coverage_ratio=snapshot.coverage_ratio,
        missing_count=snapshot.missing_count,
        estimated_count=snapshot.estimated_count,
        unknown_count=snapshot.unknown_count,
        selected_versions=selected_versions,
        selected_versions_hash=snapshot.selected_versions_hash,
        members=snapshot.actuals,
    )


def _materialize_research_authorization(
    command: EvaluateForecastBaselineTrialCommand,
    spec: ForecastBaselineSpec,
    artifact: ForecastBaselineArtifact,
    evidence: ResearchTrialEvidence,
) -> ResearchTrialAuthorization:
    expected_metrics = tuple(item.metric_code for item in spec.metric_rules)
    forecast_origin_at = min(item.as_of_time for item in artifact.forecasts)
    if (
        evidence.identity.version_ref != command.research_trial_ref
        or evidence.owner != "research"
        or evidence.capability != "r1"
        or evidence.purpose != "valuation"
        or evidence.status != "running"
        or evidence.baseline_spec_ref != command.spec_ref
        or evidence.baseline_spec_content_hash != spec.content_hash
        or evidence.expected_period_ends != spec.expected_period_ends
        or evidence.metric_codes != expected_metrics
        or evidence.calendar_schedule_hash != spec.calendar_schedule.content_hash
        or evidence.evaluation_policy != spec.evaluation_policy
        or evidence.baseline_spec_approved_at != spec.approved_at
        or evidence.forecast_origin_at != forecast_origin_at
        or evidence.split_spec_hash != forecast_baseline_trial_split_hash(spec)
        or evidence.parameter_hash != forecast_baseline_trial_parameter_hash(spec)
        or not (
            spec.approved_at <= evidence.activated_at <= evidence.recorded_at <= forecast_origin_at
        )
        or not evidence.activated_at <= command.as_of < evidence.valid_until
    ):
        raise ForecastBaselineEvidenceError("Research trial authorization is invalid")
    return ResearchTrialAuthorization(
        trial_id=evidence.identity.stable_id,
        trial_version=evidence.identity.version,
        trial_content_hash=evidence.identity.content_hash,
        owner=evidence.owner,
        capability=evidence.capability,
        purpose=evidence.purpose,
        status=evidence.status,
        split_spec_hash=evidence.split_spec_hash,
        parameter_hash=evidence.parameter_hash,
        baseline_spec_id=evidence.baseline_spec_ref.stable_id,
        baseline_spec_version=evidence.baseline_spec_ref.version,
        baseline_spec_content_hash=evidence.baseline_spec_content_hash,
        expected_period_ends=evidence.expected_period_ends,
        metric_codes=evidence.metric_codes,
        calendar_schedule_hash=evidence.calendar_schedule_hash,
        evaluation_policy=evidence.evaluation_policy,
        baseline_spec_approved_at=evidence.baseline_spec_approved_at,
        forecast_origin_at=evidence.forecast_origin_at,
        activated_at=evidence.activated_at,
        recorded_at=evidence.recorded_at,
        valid_until=evidence.valid_until,
    )


def _materialize_paired_rows(
    artifact: ForecastBaselineArtifact,
    actual_manifest: EvaluationActualManifest,
) -> tuple[PairedForecastBaselineRow, ...]:
    forecasts = {item.target_period_end: item for item in artifact.forecasts}
    predictions = {(item.period_end, item.metric_code): item for item in artifact.predictions}
    rows: list[PairedForecastBaselineRow] = []
    for actual in actual_manifest.members:
        forecast = forecasts.get(actual.period_end)
        prediction = predictions.get((actual.period_end, actual.metric_code))
        if forecast is None or prediction is None:
            raise ForecastBaselineEvidenceError(
                "actual manifest does not match forecast and baseline keys"
            )
        forecast_values = dict(forecast.metric_values)
        if actual.metric_code not in forecast_values:
            raise ForecastBaselineEvidenceError("forecast metric value is unavailable")
        rows.append(
            PairedForecastBaselineRow(
                period_end=actual.period_end,
                metric_code=actual.metric_code,
                forecast_id=forecast.forecast_id,
                forecast_content_hash=forecast.forecast_content_hash,
                forecast_value=forecast_values[actual.metric_code],
                baseline_value=prediction.value,
                actual=actual,
            )
        )
    return tuple(rows)


def forecast_baseline_trial_split_hash(spec: ForecastBaselineSpec) -> str:
    """Return the canonical Research split hash required by one baseline spec."""

    return _canonical_hash(
        {
            "schema": "r1-trial-split.v1",
            "training_window": [
                spec.training_window_start.isoformat(),
                spec.training_window_end.isoformat(),
            ],
            "evaluation_periods": [item.isoformat() for item in spec.expected_period_ends],
            "calendar_schedule_hash": spec.calendar_schedule.content_hash,
            "actual_selection_policy_hash": spec.evaluation_policy.policy_content_hash,
        }
    )


def forecast_baseline_trial_parameter_hash(spec: ForecastBaselineSpec) -> str:
    """Return the canonical Research parameter hash required by one baseline spec."""

    return _canonical_hash(
        {
            "schema": "r1-trial-parameters.v1",
            "baseline_spec": [spec.spec_id, spec.spec_version, spec.content_hash],
        }
    )


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "EvaluateForecastBaselineTrialCommand",
    "EvaluateForecastBaselineTrialUseCase",
    "EvaluationActualEvidenceProvider",
    "EvaluationActualManifestSnapshot",
    "ResearchTrialEvidence",
    "ResearchTrialEvidenceProvider",
    "forecast_baseline_trial_parameter_hash",
    "forecast_baseline_trial_split_hash",
]
