"""ID-only registration of Research-owned R1 trial preregistration evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.equity.application.forecast_baseline_evaluation import (
    forecast_baseline_trial_parameter_hash,
    forecast_baseline_trial_split_hash,
)
from apps.equity.domain.forecast_baseline import (
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
)
from apps.research.domain.r1_forecast_trial_evidence import (
    PersistedR1ForecastTrialEvidence,
    R1ForecastTrialDefinition,
)


class R1ForecastTrialEvidenceUnavailable(RuntimeError):
    """Exact owner inputs, transaction identity, or append result was unavailable."""


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


class _UowBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return one exact shared transaction identity."""


class R1ForecastTrialDefinitionProvider(_UowBound, Protocol):
    """Canonical Research owner provider for versioned trial definitions."""

    def get_exact(
        self,
        *,
        definition_id: str,
        definition_version: str,
        as_of: datetime,
    ) -> R1ForecastTrialDefinition | None:
        """Return one exact owner definition at the PIT cutoff."""


class R1ForecastBaselineEvidenceProvider(_UowBound, Protocol):
    """Exact Equity owner reader for approved specs and materialized artifacts."""

    def get_spec(
        self,
        *,
        spec_id: str,
        spec_version: str,
        as_of: datetime,
    ) -> ForecastBaselineSpec | None:
        """Return one exact approved baseline spec at the PIT cutoff."""

    def get_artifact(
        self,
        *,
        artifact_id: str,
        artifact_version: str,
        as_of: datetime,
    ) -> ForecastBaselineArtifact | None:
        """Return one exact baseline artifact at the PIT cutoff."""


class R1ForecastTrialEvidenceStore(_UowBound, Protocol):
    """Private append capability retained only by private composition."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one shared registration transaction."""

    def append(
        self, evidence: PersistedR1ForecastTrialEvidence
    ) -> PersistedR1ForecastTrialEvidence:
        """Append one exact preregistration receipt."""


class R1ForecastTrialEvidenceClock(_UowBound, Protocol):
    """Trusted server clock for the registration timestamp."""

    def now(self) -> datetime:
        """Return the exact timezone-aware server timestamp."""


@dataclass(frozen=True)
class RegisterR1ForecastTrialEvidenceCommand:
    """Identity-only request; no caller-authored authorization is accepted."""

    evidence_id: str
    evidence_version: str
    definition_id: str
    definition_version: str
    spec_id: str
    spec_version: str
    artifact_id: str
    artifact_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_id",
            "evidence_version",
            "definition_id",
            "definition_version",
            "spec_id",
            "spec_version",
            "artifact_id",
            "artifact_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_aware(self.as_of, "as_of")


class RegisterR1ForecastTrialEvidence:
    """Double-read the complete owner graph and append one server-stamped receipt."""

    def __init__(
        self,
        *,
        definition_provider: R1ForecastTrialDefinitionProvider,
        baseline_provider: R1ForecastBaselineEvidenceProvider,
        store: R1ForecastTrialEvidenceStore,
        clock: R1ForecastTrialEvidenceClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._baseline_provider = baseline_provider
        self._store = store
        self._clock = clock
        self._participants: tuple[_UowBound, ...] = (
            definition_provider,
            baseline_provider,
            store,
            clock,
        )
        try:
            self._expected_uow_key = _capture_shared_uow(self._participants)
            self._participant_ids = tuple(id(item) for item in self._participants)
            self._require_live_participants()
        except R1ForecastTrialEvidenceUnavailable:
            raise
        except Exception as error:
            raise R1ForecastTrialEvidenceUnavailable(
                "R1 trial preregistration dependencies are unavailable"
            ) from error

    def execute(
        self, command: RegisterR1ForecastTrialEvidenceCommand
    ) -> PersistedR1ForecastTrialEvidence:
        """Append one exact preregistration or fail atomically with no write."""

        try:
            if type(command) is not RegisterR1ForecastTrialEvidenceCommand:
                raise TypeError("registration command type differs")
            RegisterR1ForecastTrialEvidenceCommand.__post_init__(command)
            self._require_live_participants()
            with self._store.atomic():
                self._require_live_participants()
                recorded_at = self._clock.now()
                _require_aware(recorded_at, "clock.now")
                self._require_live_participants()
                if command.as_of > recorded_at:
                    raise R1ForecastTrialEvidenceUnavailable("future registration cutoff")
                first_graph = deepcopy(self._read_graph(command))
                self._require_live_participants()
                second_graph = self._read_graph(command)
                self._require_live_participants()
                if second_graph != first_graph:
                    raise R1ForecastTrialEvidenceUnavailable(
                        "R1 trial owner graph changed during registration"
                    )
                definition, spec, artifact = first_graph
                _validate_exact_graph(
                    command,
                    definition,
                    spec,
                    artifact,
                    recorded_at=recorded_at,
                )
                evidence = PersistedR1ForecastTrialEvidence.create(
                    evidence_id=command.evidence_id,
                    evidence_version=command.evidence_version,
                    definition=definition,
                    baseline_spec_approved_at=spec.approved_at,
                    forecast_origin_at=min(item.as_of_time for item in artifact.forecasts),
                    recorded_at=recorded_at,
                )
                self._require_live_participants()
                result = self._store.append(evidence)
                self._require_live_participants()
                if type(result) is not PersistedR1ForecastTrialEvidence or result != evidence:
                    raise R1ForecastTrialEvidenceUnavailable(
                        "R1 trial evidence store substituted the receipt"
                    )
                PersistedR1ForecastTrialEvidence.__post_init__(result)
                return result
        except R1ForecastTrialEvidenceUnavailable:
            raise
        except Exception as error:
            raise R1ForecastTrialEvidenceUnavailable(
                "R1 trial preregistration is unavailable"
            ) from error

    def _read_graph(
        self, command: RegisterR1ForecastTrialEvidenceCommand
    ) -> tuple[R1ForecastTrialDefinition, ForecastBaselineSpec, ForecastBaselineArtifact]:
        definition = self._definition_provider.get_exact(
            definition_id=command.definition_id,
            definition_version=command.definition_version,
            as_of=command.as_of,
        )
        spec = self._baseline_provider.get_spec(
            spec_id=command.spec_id,
            spec_version=command.spec_version,
            as_of=command.as_of,
        )
        artifact = self._baseline_provider.get_artifact(
            artifact_id=command.artifact_id,
            artifact_version=command.artifact_version,
            as_of=command.as_of,
        )
        if type(definition) is not R1ForecastTrialDefinition:
            raise R1ForecastTrialEvidenceUnavailable("exact R1 trial definition is unavailable")
        if type(spec) is not ForecastBaselineSpec:
            raise R1ForecastTrialEvidenceUnavailable("exact baseline spec is unavailable")
        if type(artifact) is not ForecastBaselineArtifact:
            raise R1ForecastTrialEvidenceUnavailable("exact baseline artifact is unavailable")
        R1ForecastTrialDefinition.__post_init__(definition)
        ForecastBaselineSpec.__post_init__(spec)
        ForecastBaselineArtifact.__post_init__(artifact)
        return definition, spec, artifact

    def _require_live_participants(self) -> None:
        participants: tuple[_UowBound, ...] = (
            self._definition_provider,
            self._baseline_provider,
            self._store,
            self._clock,
        )
        if tuple(id(item) for item in participants) != self._participant_ids:
            raise R1ForecastTrialEvidenceUnavailable(
                "R1 trial preregistration participant was replaced"
            )
        if _capture_shared_uow(participants) != self._expected_uow_key:
            raise R1ForecastTrialEvidenceUnavailable("R1 trial preregistration UoW changed")


def _capture_shared_uow(participants: tuple[_UowBound, ...]) -> str:
    keys: list[str] = []
    for participant in participants:
        key = participant.unit_of_work_key
        if type(key) is not str or not key.strip():
            raise R1ForecastTrialEvidenceUnavailable("R1 trial preregistration UoW is invalid")
        keys.append(key)
    if len(set(keys)) != 1:
        raise R1ForecastTrialEvidenceUnavailable("R1 trial preregistration requires one shared UoW")
    return keys[0]


def _validate_exact_graph(
    command: RegisterR1ForecastTrialEvidenceCommand,
    definition: R1ForecastTrialDefinition,
    spec: ForecastBaselineSpec,
    artifact: ForecastBaselineArtifact,
    *,
    recorded_at: datetime,
) -> None:
    metrics = tuple(item.metric_code for item in spec.metric_rules)
    forecast_origin_at = min(item.as_of_time for item in artifact.forecasts)
    if (
        (definition.definition_id, definition.definition_version)
        != (command.definition_id, command.definition_version)
        or (spec.spec_id, spec.spec_version) != (command.spec_id, command.spec_version)
        or (artifact.artifact_id, artifact.artifact_version)
        != (command.artifact_id, command.artifact_version)
        or (
            definition.baseline_spec_id,
            definition.baseline_spec_version,
            definition.baseline_spec_content_hash,
        )
        != (spec.spec_id, spec.spec_version, spec.content_hash)
        or (
            definition.baseline_artifact_id,
            definition.baseline_artifact_version,
            definition.baseline_artifact_content_hash,
        )
        != (artifact.artifact_id, artifact.artifact_version, artifact.content_hash)
        or (artifact.spec_id, artifact.spec_version, artifact.spec_content_hash)
        != (spec.spec_id, spec.spec_version, spec.content_hash)
        or definition.split_spec_hash != forecast_baseline_trial_split_hash(spec)
        or definition.parameter_hash != forecast_baseline_trial_parameter_hash(spec)
        or definition.expected_period_ends != spec.expected_period_ends
        or definition.metric_codes != metrics
        or definition.evaluation_keys
        != tuple(
            (period_end, metric_code)
            for period_end in spec.expected_period_ends
            for metric_code in metrics
        )
        or (
            definition.calendar_id,
            definition.calendar_version,
            definition.calendar_schedule_hash,
        )
        != (
            spec.calendar_schedule.calendar_id,
            spec.calendar_schedule.calendar_version,
            spec.calendar_schedule.content_hash,
        )
        or definition.evaluation_policy != spec.evaluation_policy
        or artifact.evaluation_policy != spec.evaluation_policy
        or artifact.expected_period_ends != spec.expected_period_ends
        or artifact.metric_codes != metrics
        or artifact.calendar_schedule != spec.calendar_schedule
        or not (
            spec.approval_recorded_at <= command.as_of
            and definition.activated_at <= command.as_of
            and spec.approved_at
            <= definition.activated_at
            <= recorded_at
            <= forecast_origin_at
            < definition.valid_until
            <= min(spec.valid_until, artifact.valid_until, spec.evaluation_policy.valid_until)
        )
        or not (
            spec.research_only
            and spec.must_not_use_for_decision
            and spec.must_not_execute
            and artifact.research_only
            and artifact.must_not_use_for_decision
            and artifact.must_not_execute
        )
    ):
        raise R1ForecastTrialEvidenceUnavailable(
            "R1 trial owner graph is substituted or chronologically invalid"
        )


__all__ = [
    "R1ForecastBaselineEvidenceProvider",
    "R1ForecastTrialDefinitionProvider",
    "R1ForecastTrialEvidenceClock",
    "R1ForecastTrialEvidenceStore",
    "R1ForecastTrialEvidenceUnavailable",
    "RegisterR1ForecastTrialEvidence",
    "RegisterR1ForecastTrialEvidenceCommand",
]
