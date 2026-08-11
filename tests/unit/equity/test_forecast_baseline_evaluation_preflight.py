"""Read-only production preflight contracts for R1 baseline evaluation."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from apps.equity.application.forecast_baseline_evaluation import (
    EvaluateForecastBaselineTrialCommand,
    build_forecast_baseline_trial_candidate,
)
from apps.equity.application.forecast_baseline_evaluation_preflight import (
    EvaluateForecastBaselineTrialPreflight,
    ForecastBaselinePreflightBlockerCode,
    ForecastBaselinePreflightStatus,
)
from apps.equity.application.forecast_baseline_materialize import (
    ForecastBaselineEvidenceError,
    VersionRef,
)
from tests.unit.equity.test_forecast_baseline_application import (
    _actual_snapshot,
    _build_artifact,
    _research_trial,
)

AS_OF = datetime(2025, 3, 4, 12, tzinfo=UTC)


class _ReadUnitOfWork:
    unit_of_work_key = "test:r1-preflight"

    def __init__(self, spec: object | None = None, artifact: object | None = None) -> None:
        self.atomic_depth = 0
        self.atomic_entries = 0
        self.spec_calls = 0
        self.artifact_calls = 0
        self.spec = spec
        self.artifact = artifact
        self.clock_hook: Callable[[], None] | None = None

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        self.atomic_depth += 1
        try:
            yield
        finally:
            self.atomic_depth -= 1

    def server_now(self) -> datetime:
        assert self.atomic_depth == 1
        if self.clock_hook is not None:
            self.clock_hook()
        return AS_OF + timedelta(hours=1)

    def get_spec(self, spec_ref: VersionRef) -> object | None:
        del spec_ref
        assert self.atomic_depth == 1
        self.spec_calls += 1
        return self.spec

    def get_artifact(self, artifact_ref: VersionRef) -> object | None:
        del artifact_ref
        assert self.atomic_depth == 1
        self.artifact_calls += 1
        return self.artifact


class _ActualProvider:
    def __init__(self, snapshot: object | None = None) -> None:
        self.calls = 0
        self.values: list[object | None] = [snapshot]
        self.error: Exception | None = None
        self.key = "test:r1-preflight"

    @property
    def unit_of_work_key(self) -> str:
        return self.key

    def get_actual_manifest(
        self,
        manifest_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> object | None:
        del manifest_ref, as_of
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.values[min(self.calls - 1, len(self.values) - 1)]


class _ResearchProvider:
    def __init__(self, evidence: object | None = None) -> None:
        self.calls = 0
        self.evidence = evidence
        self.key = "test:r1-preflight"

    @property
    def unit_of_work_key(self) -> str:
        return self.key

    def get_trial(
        self,
        trial_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> object | None:
        del trial_ref, as_of
        self.calls += 1
        return self.evidence


def _command() -> EvaluateForecastBaselineTrialCommand:
    return EvaluateForecastBaselineTrialCommand(
        output_trial_ref=VersionRef("r1-output", "v1"),
        spec_ref=VersionRef("r1-spec", "v1"),
        artifact_ref=VersionRef("r1-artifact", "v1"),
        actual_manifest_ref=VersionRef("r1-actual", "v1"),
        research_trial_ref=VersionRef("r1-research-trial", "v1"),
        as_of=AS_OF,
    )


def _complete_command() -> tuple[
    EvaluateForecastBaselineTrialCommand,
    object,
    object,
    object,
    object,
]:
    spec, artifact, _, _ = _build_artifact()
    actual = _actual_snapshot()
    research = _research_trial(spec)
    return (
        EvaluateForecastBaselineTrialCommand(
            output_trial_ref=VersionRef("r1-preflight-output", "v1"),
            spec_ref=VersionRef(spec.spec_id, spec.spec_version),
            artifact_ref=VersionRef(artifact.artifact_id, artifact.artifact_version),
            actual_manifest_ref=actual.identity.version_ref,
            research_trial_ref=research.identity.version_ref,
            as_of=AS_OF,
        ),
        spec,
        artifact,
        actual,
        research,
    )


def test_empty_exact_owners_are_double_read_and_stably_blocked() -> None:
    read_uow = _ReadUnitOfWork()
    actual = _ActualProvider()
    research = _ResearchProvider()
    preflight = EvaluateForecastBaselineTrialPreflight(
        read_repository=read_uow,
        actual_provider=actual,
        research_trial_provider=research,
    )

    result = preflight.execute(_command())

    assert result.status is ForecastBaselinePreflightStatus.BLOCKED
    assert result.blocker_codes == (
        ForecastBaselinePreflightBlockerCode.ACTUAL_MANIFEST_UNAVAILABLE,
        ForecastBaselinePreflightBlockerCode.BASELINE_ARTIFACT_UNAVAILABLE,
        ForecastBaselinePreflightBlockerCode.BASELINE_SPEC_UNAVAILABLE,
        ForecastBaselinePreflightBlockerCode.RESEARCH_TRIAL_UNAVAILABLE,
    )
    assert (read_uow.spec_calls, read_uow.artifact_calls) == (2, 2)
    assert (actual.calls, research.calls) == (2, 2)
    assert read_uow.atomic_depth == 0
    assert result.research_only is True
    assert result.must_not_publish_current is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_execute is True


def test_complete_owner_graph_is_double_read_without_writes() -> None:
    command, spec, artifact, actual, research = _complete_command()
    read_uow = _ReadUnitOfWork(spec, artifact)
    actual_provider = _ActualProvider(actual)
    research_provider = _ResearchProvider(research)
    preflight = EvaluateForecastBaselineTrialPreflight(
        read_repository=read_uow,
        actual_provider=actual_provider,
        research_trial_provider=research_provider,
    )

    result = preflight.execute(command)

    assert result.status is ForecastBaselinePreflightStatus.EVIDENCE_GRAPH_COMPLETE
    assert result.blocker_codes == ()
    assert result.prospective_result_hash is not None
    assert (read_uow.spec_calls, read_uow.artifact_calls) == (2, 2)
    assert (actual_provider.calls, research_provider.calls) == (2, 2)
    assert not hasattr(read_uow, "append_trial")
    expected = build_forecast_baseline_trial_candidate(
        command=command,
        spec=spec,
        artifact=artifact,
        actual_snapshot=actual,
        research_trial=research,
        evaluated_at=AS_OF + timedelta(hours=1),
    )
    assert result.prospective_result_hash == expected.content_hash


def test_owner_replacement_and_provider_failure_are_stably_blocked() -> None:
    command, spec, artifact, actual, research = _complete_command()
    changed = _actual_snapshot()
    object.__setattr__(changed, "owner", "substituted")
    actual_provider = _ActualProvider(actual)
    actual_provider.values = [actual, changed]
    changed_result = EvaluateForecastBaselineTrialPreflight(
        read_repository=_ReadUnitOfWork(spec, artifact),
        actual_provider=actual_provider,
        research_trial_provider=_ResearchProvider(research),
    ).execute(command)

    assert changed_result.blocker_codes == (
        ForecastBaselinePreflightBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
    )

    failed_actual = _ActualProvider(actual)
    failed_actual.error = ForecastBaselineEvidenceError("corrupt exact owner row")
    failed = EvaluateForecastBaselineTrialPreflight(
        read_repository=_ReadUnitOfWork(spec, artifact),
        actual_provider=failed_actual,
        research_trial_provider=_ResearchProvider(research),
    ).execute(command)
    assert failed.blocker_codes == (
        ForecastBaselinePreflightBlockerCode.OWNER_PROVIDER_UNAVAILABLE,
    )


def test_malformed_or_subclassed_command_is_rejected_before_any_owner_read() -> None:
    class _CommandSubclass(EvaluateForecastBaselineTrialCommand):
        def __post_init__(self) -> None:
            pass

    read_uow = _ReadUnitOfWork()
    actual = _ActualProvider()
    research = _ResearchProvider()
    preflight = EvaluateForecastBaselineTrialPreflight(
        read_repository=read_uow,
        actual_provider=actual,
        research_trial_provider=research,
    )
    malformed = _command()
    object.__setattr__(malformed.output_trial_ref, "stable_id", "")

    with pytest.raises(ForecastBaselineEvidenceError):
        preflight.execute(malformed)
    with pytest.raises(ForecastBaselineEvidenceError):
        preflight.execute(
            _CommandSubclass(
                output_trial_ref=VersionRef("subclass-output", "v1"),
                spec_ref=VersionRef("r1-spec", "v1"),
                artifact_ref=VersionRef("r1-artifact", "v1"),
                actual_manifest_ref=VersionRef("r1-actual", "v1"),
                research_trial_ref=VersionRef("r1-research", "v1"),
                as_of=AS_OF,
            )
        )

    assert read_uow.atomic_entries == 0
    assert (read_uow.spec_calls, read_uow.artifact_calls) == (0, 0)
    assert (actual.calls, research.calls) == (0, 0)


def test_future_cutoff_is_rejected_before_owner_reads() -> None:
    command = _command()
    object.__setattr__(command, "as_of", AS_OF + timedelta(hours=2))
    read_uow = _ReadUnitOfWork()
    actual = _ActualProvider()
    research = _ResearchProvider()

    with pytest.raises(ForecastBaselineEvidenceError):
        EvaluateForecastBaselineTrialPreflight(
            read_repository=read_uow,
            actual_provider=actual,
            research_trial_provider=research,
        ).execute(command)

    assert read_uow.atomic_entries == 1
    assert (read_uow.spec_calls, read_uow.artifact_calls) == (0, 0)
    assert (actual.calls, research.calls) == (0, 0)


def test_live_unit_of_work_drift_is_blocked_after_trusted_clock() -> None:
    read_uow = _ReadUnitOfWork()
    actual = _ActualProvider()
    research = _ResearchProvider()
    read_uow.clock_hook = lambda: setattr(actual, "key", "test:substituted-uow")

    result = EvaluateForecastBaselineTrialPreflight(
        read_repository=read_uow,
        actual_provider=actual,
        research_trial_provider=research,
    ).execute(_command())

    assert result.blocker_codes == (ForecastBaselinePreflightBlockerCode.UNIT_OF_WORK_CHANGED,)
    assert (read_uow.spec_calls, read_uow.artifact_calls) == (0, 0)
    assert (actual.calls, research.calls) == (0, 0)


def test_complete_but_invalid_owner_graph_is_stably_blocked() -> None:
    command, spec, artifact, actual, research = _complete_command()
    object.__setattr__(research, "owner", "substituted")

    result = EvaluateForecastBaselineTrialPreflight(
        read_repository=_ReadUnitOfWork(spec, artifact),
        actual_provider=_ActualProvider(actual),
        research_trial_provider=_ResearchProvider(research),
    ).execute(command)

    assert result.blocker_codes == (ForecastBaselinePreflightBlockerCode.OWNER_GRAPH_INVALID,)
    assert result.prospective_result_hash is None
