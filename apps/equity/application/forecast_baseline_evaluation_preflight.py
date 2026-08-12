"""Read-only production preflight for an exact R1 baseline evaluation graph."""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from apps.equity.domain.forecast_baseline import (
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
)

from .forecast_baseline_evaluation import (
    EvaluateForecastBaselineTrialCommand,
    EvaluationActualEvidenceProvider,
    EvaluationActualManifestSnapshot,
    ResearchTrialEvidence,
    ResearchTrialEvidenceProvider,
    build_forecast_baseline_trial_candidate,
)
from .forecast_baseline_materialize import (
    ForecastBaselineEvidenceError,
    VersionRef,
    _require_aware,
)


class ForecastBaselinePreflightStatus(StrEnum):
    """Non-authoritative research evidence completeness states."""

    EVIDENCE_GRAPH_COMPLETE = "evidence_graph_complete"
    BLOCKED = "blocked"


class ForecastBaselinePreflightBlockerCode(StrEnum):
    """Stable fail-closed reasons that never grant consumer authority."""

    ACTUAL_MANIFEST_UNAVAILABLE = "actual_manifest_unavailable"
    BASELINE_ARTIFACT_UNAVAILABLE = "baseline_artifact_unavailable"
    BASELINE_SPEC_UNAVAILABLE = "baseline_spec_unavailable"
    OWNER_GRAPH_CHANGED_DURING_PREFLIGHT = "owner_graph_changed_during_preflight"
    OWNER_GRAPH_INVALID = "owner_graph_invalid"
    OWNER_PROVIDER_UNAVAILABLE = "owner_provider_unavailable"
    RESEARCH_TRIAL_UNAVAILABLE = "research_trial_unavailable"
    UNIT_OF_WORK_CHANGED = "unit_of_work_changed"


@dataclass(frozen=True)
class ForecastBaselineEvaluationPreflightResult:
    """Read-only assessment; never a trial receipt, Promotion, or decision."""

    output_trial_ref: VersionRef
    as_of: datetime
    checked_at: datetime
    status: ForecastBaselinePreflightStatus
    blocker_codes: tuple[ForecastBaselinePreflightBlockerCode, ...]
    prospective_result_hash: str | None
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if type(self.output_trial_ref) is not VersionRef:
            raise TypeError("R1 preflight output trial reference type differs")
        VersionRef.__post_init__(self.output_trial_ref)
        _require_aware(self.as_of, "R1 preflight as_of")
        _require_aware(self.checked_at, "R1 preflight checked_at")
        if self.as_of > self.checked_at:
            raise ValueError("R1 preflight cutoff is from the future")
        if type(self.status) is not ForecastBaselinePreflightStatus:
            raise TypeError("R1 preflight status type differs")
        if type(self.blocker_codes) is not tuple or self.blocker_codes != tuple(
            sorted(set(self.blocker_codes), key=lambda item: item.value)
        ):
            raise ValueError("R1 preflight blockers are not canonical")
        if any(
            type(item) is not ForecastBaselinePreflightBlockerCode for item in self.blocker_codes
        ):
            raise TypeError("R1 preflight blocker type differs")
        blocked = self.status is ForecastBaselinePreflightStatus.BLOCKED
        if blocked != bool(self.blocker_codes):
            raise ValueError("R1 preflight status and blockers differ")
        if blocked != (self.prospective_result_hash is None):
            raise ValueError("R1 preflight prospective hash and status differ")
        if self.prospective_result_hash is not None and not _is_hash(self.prospective_result_hash):
            raise ValueError("R1 preflight prospective result hash is invalid")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R1 preflight safety boundary differs")


class ForecastBaselineEvaluationReadRepository(Protocol):
    """Read-only Equity spec/artifact transaction and trusted clock."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner database identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared read transaction."""

    def server_now(self) -> datetime:
        """Return a trusted server clock within the transaction."""

    def get_spec(self, spec_ref: VersionRef) -> ForecastBaselineSpec | None:
        """Restore one exact immutable spec."""

    def get_artifact(
        self,
        artifact_ref: VersionRef,
    ) -> ForecastBaselineArtifact | None:
        """Restore one exact immutable artifact."""


@dataclass(frozen=True)
class _OwnerGraph:
    spec: ForecastBaselineSpec | None
    artifact: ForecastBaselineArtifact | None
    actual: EvaluationActualManifestSnapshot | None
    research_trial: ResearchTrialEvidence | None


class EvaluateForecastBaselineTrialPreflight:
    """Double-read the exact graph and emit no write-capable artifact."""

    def __init__(
        self,
        *,
        read_repository: ForecastBaselineEvaluationReadRepository,
        actual_provider: EvaluationActualEvidenceProvider,
        research_trial_provider: ResearchTrialEvidenceProvider,
    ) -> None:
        self._read_repository = read_repository
        self._actual_provider = actual_provider
        self._research_trial_provider = research_trial_provider
        self._participant_ids = tuple(
            id(item) for item in (read_repository, actual_provider, research_trial_provider)
        )
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise ForecastBaselineEvidenceError(
                "R1 preflight unit of work is unavailable"
            ) from error
        if len(set(keys)) != 1:
            raise ForecastBaselineEvidenceError(
                "R1 preflight owners require one shared unit of work"
            )
        self._expected_uow_key = keys[0]

    def execute(
        self,
        command: EvaluateForecastBaselineTrialCommand,
    ) -> ForecastBaselineEvaluationPreflightResult:
        """Return complete/blocked research evidence without appending a trial."""

        self._require_command(command)
        checked_at: datetime | None = None
        try:
            with self._read_repository.atomic():
                self._require_live_uow()
                server_now = self._read_repository.server_now()
                _require_aware(server_now, "R1 preflight server clock")
                checked_at = server_now
                if command.as_of > checked_at:
                    raise _FutureCutoff
                first = self._read_graph(command)
                self._require_live_uow()
                second = self._read_graph(command)
                self._require_live_uow()
        except _FutureCutoff as error:
            raise ForecastBaselineEvidenceError(
                "R1 preflight PIT cutoff is from the future"
            ) from error
        except _UnitOfWorkChanged as error:
            if checked_at is None:
                raise ForecastBaselineEvidenceError(
                    "R1 preflight unit of work changed before the trusted clock"
                ) from error
            return self._blocked(
                command,
                checked_at,
                ForecastBaselinePreflightBlockerCode.UNIT_OF_WORK_CHANGED,
            )
        except Exception as error:
            if checked_at is None:
                raise ForecastBaselineEvidenceError(
                    "R1 preflight trusted clock or transaction is unavailable"
                ) from error
            return self._blocked(
                command,
                checked_at,
                ForecastBaselinePreflightBlockerCode.OWNER_PROVIDER_UNAVAILABLE,
            )
        if checked_at is None:
            raise ForecastBaselineEvidenceError("R1 preflight trusted clock was not captured")
        if first != second:
            return self._blocked(
                command,
                checked_at,
                ForecastBaselinePreflightBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
            )
        return self._evaluate_graph(command, checked_at, second)

    def _read_graph(self, command: EvaluateForecastBaselineTrialCommand) -> _OwnerGraph:
        self._require_live_uow()
        spec = _copy_spec(self._read_repository.get_spec(command.spec_ref))
        self._require_live_uow()
        artifact = _copy_artifact(
            self._read_repository.get_artifact(command.artifact_ref),
            spec=spec,
        )
        self._require_live_uow()
        actual = _copy_actual(
            self._actual_provider.get_actual_manifest(
                command.actual_manifest_ref,
                as_of=command.as_of,
            )
        )
        self._require_live_uow()
        research_trial = _copy_research_trial(
            self._research_trial_provider.get_trial(
                command.research_trial_ref,
                as_of=command.as_of,
            )
        )
        self._require_live_uow()
        return _OwnerGraph(spec, artifact, actual, research_trial)

    def _evaluate_graph(
        self,
        command: EvaluateForecastBaselineTrialCommand,
        checked_at: datetime,
        graph: _OwnerGraph,
    ) -> ForecastBaselineEvaluationPreflightResult:
        blockers: list[ForecastBaselinePreflightBlockerCode] = []
        if graph.spec is None:
            blockers.append(ForecastBaselinePreflightBlockerCode.BASELINE_SPEC_UNAVAILABLE)
        if graph.artifact is None:
            blockers.append(ForecastBaselinePreflightBlockerCode.BASELINE_ARTIFACT_UNAVAILABLE)
        if graph.actual is None:
            blockers.append(ForecastBaselinePreflightBlockerCode.ACTUAL_MANIFEST_UNAVAILABLE)
        if graph.research_trial is None:
            blockers.append(ForecastBaselinePreflightBlockerCode.RESEARCH_TRIAL_UNAVAILABLE)
        if blockers:
            return self._blocked(command, checked_at, *blockers)
        try:
            if (
                graph.spec is None
                or graph.artifact is None
                or graph.actual is None
                or graph.research_trial is None
            ):
                raise TypeError("R1 preflight graph narrowing failed")
            candidate = build_forecast_baseline_trial_candidate(
                command=command,
                spec=graph.spec,
                artifact=graph.artifact,
                actual_snapshot=graph.actual,
                research_trial=graph.research_trial,
                evaluated_at=checked_at,
            )
        except Exception:
            return self._blocked(
                command,
                checked_at,
                ForecastBaselinePreflightBlockerCode.OWNER_GRAPH_INVALID,
            )
        return ForecastBaselineEvaluationPreflightResult(
            output_trial_ref=command.output_trial_ref,
            as_of=command.as_of,
            checked_at=checked_at,
            status=ForecastBaselinePreflightStatus.EVIDENCE_GRAPH_COMPLETE,
            blocker_codes=(),
            prospective_result_hash=candidate.content_hash,
        )

    @staticmethod
    def _blocked(
        command: EvaluateForecastBaselineTrialCommand,
        checked_at: datetime,
        *blockers: ForecastBaselinePreflightBlockerCode,
    ) -> ForecastBaselineEvaluationPreflightResult:
        return ForecastBaselineEvaluationPreflightResult(
            output_trial_ref=command.output_trial_ref,
            as_of=command.as_of,
            checked_at=checked_at,
            status=ForecastBaselinePreflightStatus.BLOCKED,
            blocker_codes=tuple(sorted(set(blockers), key=lambda item: item.value)),
            prospective_result_hash=None,
        )

    @staticmethod
    def _require_command(command: object) -> None:
        try:
            if type(command) is not EvaluateForecastBaselineTrialCommand:
                raise TypeError("R1 preflight command type differs")
            EvaluateForecastBaselineTrialCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise ForecastBaselineEvidenceError("R1 preflight command is malformed") from error

    def _current_uow_keys(self) -> tuple[str, str, str]:
        return (
            _exact_uow_key(self._read_repository.unit_of_work_key),
            _exact_uow_key(self._actual_provider.unit_of_work_key),
            _exact_uow_key(self._research_trial_provider.unit_of_work_key),
        )

    def _require_live_uow(self) -> None:
        participants = (
            self._read_repository,
            self._actual_provider,
            self._research_trial_provider,
        )
        if tuple(id(item) for item in participants) != self._participant_ids:
            raise _UnitOfWorkChanged
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise _UnitOfWorkChanged from error
        if any(key != self._expected_uow_key for key in keys):
            raise _UnitOfWorkChanged


class _UnitOfWorkChanged(RuntimeError):
    pass


class _FutureCutoff(RuntimeError):
    pass


def _copy_spec(value: object) -> ForecastBaselineSpec | None:
    if value is None:
        return None
    if type(value) is not ForecastBaselineSpec:
        raise TypeError("R1 preflight spec type differs")
    copied = deepcopy(value)
    rebuilt = ForecastBaselineSpec.create(
        spec_id=copied.spec_id,
        spec_version=copied.spec_version,
        owner=copied.owner,
        approval_evidence_id=copied.approval_evidence_id,
        approval_evidence_version=copied.approval_evidence_version,
        approval_evidence_content_hash=copied.approval_evidence_content_hash,
        approval_owner=copied.approval_owner,
        approval_status=copied.approval_status,
        evaluation_policy=copied.evaluation_policy,
        subject_code=copied.subject_code,
        industry_code=copied.industry_code,
        candidate_scenario=copied.candidate_scenario,
        horizon_quarters=copied.horizon_quarters,
        family=copied.family,
        computation_method=copied.computation_method,
        computation_code_version=copied.computation_code_version,
        family_parameter_version=copied.family_parameter_version,
        family_parameter_hash=copied.family_parameter_hash,
        seasonal_lag_periods=copied.seasonal_lag_periods,
        pit_inputs=copied.pit_inputs,
        training_window_start=copied.training_window_start,
        training_window_end=copied.training_window_end,
        expected_period_ends=copied.expected_period_ends,
        calendar_schedule=copied.calendar_schedule,
        period_horizons=copied.period_horizons,
        metric_rules=copied.metric_rules,
        metric_evaluation_order=copied.metric_evaluation_order,
        tie_break_rule=copied.tie_break_rule,
        cost_rule=copied.cost_rule,
        invalidation_applicability=copied.invalidation_applicability,
        invalidation_rules=copied.invalidation_rules,
        invalidation_not_applicable_reason=copied.invalidation_not_applicable_reason,
        approved_at=copied.approved_at,
        approval_recorded_at=copied.approval_recorded_at,
        valid_until=copied.valid_until,
    )
    if rebuilt != copied or rebuilt != value:
        raise ValueError("R1 preflight spec live seal differs")
    return rebuilt


def _copy_artifact(
    value: object,
    *,
    spec: ForecastBaselineSpec | None,
) -> ForecastBaselineArtifact | None:
    if value is None:
        return None
    if type(value) is not ForecastBaselineArtifact:
        raise TypeError("R1 preflight artifact type differs")
    copied = deepcopy(value)
    if spec is None:
        return copied
    rebuilt = ForecastBaselineArtifact.create(
        artifact_id=copied.artifact_id,
        artifact_version=copied.artifact_version,
        owner=copied.owner,
        spec=spec,
        forecasts=copied.forecasts,
        predictions=copied.predictions,
        knowledge_as_of=copied.knowledge_as_of,
        produced_at=copied.produced_at,
        valid_until=copied.valid_until,
    )
    if rebuilt != copied or rebuilt != value:
        raise ValueError("R1 preflight artifact live seal differs")
    return rebuilt


def _copy_actual(value: object) -> EvaluationActualManifestSnapshot | None:
    if value is None:
        return None
    if type(value) is not EvaluationActualManifestSnapshot:
        raise TypeError("R1 preflight actual snapshot type differs")
    return deepcopy(value)


def _copy_research_trial(value: object) -> ResearchTrialEvidence | None:
    if value is None:
        return None
    if type(value) is not ResearchTrialEvidence:
        raise TypeError("R1 preflight Research trial type differs")
    return deepcopy(value)


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise TypeError("R1 preflight unit_of_work_key must be an exact string")
    return value


def _is_hash(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "EvaluateForecastBaselineTrialPreflight",
    "ForecastBaselineEvaluationPreflightResult",
    "ForecastBaselineEvaluationReadRepository",
    "ForecastBaselinePreflightBlockerCode",
    "ForecastBaselinePreflightStatus",
]
