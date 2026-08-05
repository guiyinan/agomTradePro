"""Application tests for typed, fail-closed R3 runner orchestration."""

from datetime import timedelta

from apps.macro_factor.application.reproducible_runner import (
    MacroFactorRunnerBlockerCode,
    MacroFactorRunnerStatus,
    RetireReproducibleMacroFactorRun,
    RetireReproducibleMacroFactorRunCommand,
    RunReproducibleMacroFactor,
    RunReproducibleMacroFactorCommand,
)
from apps.macro_factor.domain.entities import RetirementEvidence
from apps.macro_factor.domain.reproducible_runner import (
    ExternalNestedCVArtifact,
    MacroFactorLifecycleEvent,
    NestedCVExecutionRequest,
    PITResearchDataset,
    ReproducibleMacroFactorRunArtifact,
    ReproducibleMacroFactorRunBundle,
)
from tests.unit.macro_factor.factories import complete_manifest
from tests.unit.macro_factor.runner_factories import (
    external_runner_artifact,
    retirement_owner_attestation,
    runner_dataset,
    runner_spec,
)


class _ManifestProvider:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def get_manifest(self, manifest_id: str):  # type: ignore[no-untyped-def]
        assert manifest_id == "pit-r3-growth-v1"
        return self.value


class _DatasetProvider:
    def __init__(self, value: PITResearchDataset | None) -> None:
        self.value = value

    def get_dataset(
        self,
        *,
        manifest_id: str,
        manifest_hash: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
    ) -> PITResearchDataset | None:
        assert manifest_id == "pit-r3-growth-v1"
        assert manifest_hash == "a" * 64
        assert target_code == "growth_nowcast_1m"
        assert candidate_asset_codes == ("ETF_CREDIT", "FUTURE_COPPER")
        return self.value


class _ExternalRunner:
    def __init__(self, value: ExternalNestedCVArtifact | None) -> None:
        self.value = value
        self.requests: list[NestedCVExecutionRequest] = []

    def execute(
        self,
        request: NestedCVExecutionRequest,
    ) -> ExternalNestedCVArtifact | None:
        self.requests.append(request)
        return self.value


class _Repository:
    def __init__(self) -> None:
        self.bundle: ReproducibleMacroFactorRunBundle | None = None
        self.events: list[MacroFactorLifecycleEvent] = []

    def append_bundle(
        self,
        bundle: ReproducibleMacroFactorRunBundle,
    ) -> ReproducibleMacroFactorRunBundle:
        self.bundle = bundle
        self.events = list(bundle.lifecycle_events)
        return bundle

    def get_artifact(
        self,
        artifact_id: str,
    ) -> ReproducibleMacroFactorRunArtifact | None:
        if self.bundle is None or self.bundle.artifact.artifact_id != artifact_id:
            return None
        return self.bundle.artifact

    def list_lifecycle_events(self, artifact_id: str) -> tuple[MacroFactorLifecycleEvent, ...]:
        assert self.bundle is not None
        assert self.bundle.artifact.artifact_id == artifact_id
        return tuple(self.events)

    def append_lifecycle_event(
        self,
        event: MacroFactorLifecycleEvent,
    ) -> MacroFactorLifecycleEvent:
        self.events.append(event)
        return event


def _command() -> RunReproducibleMacroFactorCommand:
    return RunReproducibleMacroFactorCommand(
        spec=runner_spec(),
        expected_manifest_id="pit-r3-growth-v1",
        expected_manifest_hash="a" * 64,
    )


def test_use_case_runs_typed_external_executor_and_persists_research_bundle() -> None:
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())
    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=runner,
        repository=repository,
    ).execute(_command())

    assert assessment.status is MacroFactorRunnerStatus.RECORDED
    assert assessment.blocked_reasons == ()
    assert assessment.bundle is repository.bundle
    assert len(runner.requests) == 1
    assert runner.requests[0].pit_manifest_hash == "a" * 64
    assert assessment.research_only is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.must_not_execute is True


def test_missing_manifest_dataset_or_runner_fails_closed_without_writes() -> None:
    cases = (
        (
            _ManifestProvider(None),
            _DatasetProvider(runner_dataset()),
            _ExternalRunner(external_runner_artifact()),
            MacroFactorRunnerBlockerCode.PIT_MANIFEST_MISSING,
        ),
        (
            _ManifestProvider(complete_manifest()),
            _DatasetProvider(None),
            _ExternalRunner(external_runner_artifact()),
            MacroFactorRunnerBlockerCode.PIT_DATASET_MISSING,
        ),
        (
            _ManifestProvider(complete_manifest()),
            _DatasetProvider(runner_dataset()),
            _ExternalRunner(None),
            MacroFactorRunnerBlockerCode.EXTERNAL_RUNNER_UNAVAILABLE,
        ),
    )
    for manifest_provider, dataset_provider, runner, expected in cases:
        repository = _Repository()
        assessment = RunReproducibleMacroFactor(
            manifest_provider=manifest_provider,
            dataset_provider=dataset_provider,
            external_runner=runner,
            repository=repository,
        ).execute(_command())
        assert assessment.status is MacroFactorRunnerStatus.BLOCKED
        assert assessment.blocked_reasons == (expected,)
        assert assessment.bundle is None
        assert repository.bundle is None


def test_external_runner_request_mismatch_is_blocked_not_persisted() -> None:
    artifact = external_runner_artifact()
    mismatched = ExternalNestedCVArtifact.create(
        evidence_id=artifact.evidence_id,
        producer_ref=artifact.producer_ref,
        produced_at=artifact.produced_at,
        request_hash="8" * 64,
        result=artifact.result,
        fold_selections=artifact.fold_selections,
        predictions=artifact.predictions,
        dated_outputs=artifact.dated_outputs,
    )
    repository = _Repository()
    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=_ExternalRunner(mismatched),
        repository=repository,
    ).execute(_command())

    assert assessment.status is MacroFactorRunnerStatus.BLOCKED
    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.EXTERNAL_ARTIFACT_INVALID,)
    assert repository.bundle is None


def test_retirement_appends_event_without_mutating_run_or_source_result() -> None:
    repository = _Repository()
    recorded = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=_ExternalRunner(external_runner_artifact()),
        repository=repository,
    ).execute(_command())
    assert recorded.bundle is not None
    artifact = recorded.bundle.artifact
    result = recorded.bundle.source_result
    retirement = RetirementEvidence(
        event_id="retire-growth-run-v1",
        retired_at=artifact.produced_at + timedelta(days=1),
        policy_version=result.retirement_policy.policy_version,
        reason_codes=(result.retirement_policy.rules[0].rule_id,),
        evidence_hash="9" * 64,
    )
    assessment = RetireReproducibleMacroFactorRun(repository=repository).execute(
        RetireReproducibleMacroFactorRunCommand(
            artifact_id=artifact.artifact_id,
            expected_artifact_hash=artifact.content_hash,
            source_result=result,
            retirement=retirement,
            owner_attestation=retirement_owner_attestation(
                artifact,
                result,
                retirement,
            ),
            recorded_at=retirement.retired_at,
        )
    )

    assert assessment.status is MacroFactorRunnerStatus.RETIRED
    assert assessment.lifecycle_event is repository.events[-1]
    assert repository.bundle.artifact.content_hash == artifact.content_hash
    assert repository.bundle.source_result.lifecycle_status.value == "research_only"
