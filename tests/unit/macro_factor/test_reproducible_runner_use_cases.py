"""Application tests for typed, fail-closed R3 runner orchestration."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.macro_factor.application.reproducible_runner import (
    MacroFactorRunnerBlockerCode,
    MacroFactorRunnerStatus,
    RetireReproducibleMacroFactorRun,
    RetireReproducibleMacroFactorRunCommand,
    RunReproducibleMacroFactor,
    RunReproducibleMacroFactorCommand,
)
from apps.macro_factor.domain._runner_support import hash_payload
from apps.macro_factor.domain.entities import (
    PITInferenceCalendarPeriodEvidence,
    PITManifestEvidence,
    RetirementEvidence,
)
from apps.macro_factor.domain.reproducible_runner import (
    ExternalNestedCVArtifact,
    InputKnowledgeFreshnessPolicy,
    MacroFactorLifecycleEvent,
    MacroFactorRunnerSpec,
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


class WideInt(int):
    """Integer subtype whose comparisons conceal an out-of-policy magnitude."""

    def __le__(self, other: object) -> bool:
        return False

    def __gt__(self, other: object) -> bool:
        return False


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
        *,
        request: NestedCVExecutionRequest,
        dataset: PITResearchDataset,
        spec: MacroFactorRunnerSpec,
    ) -> ExternalNestedCVArtifact | None:
        self.requests.append(request)
        return self.value


class _LegacyExternalRunner:
    """Pre-Protocol-change adapter that only accepts the historical request."""

    def execute(
        self,
        request: NestedCVExecutionRequest,
    ) -> ExternalNestedCVArtifact | None:
        return external_runner_artifact()


class _MalformedExternalRunner:
    def execute(
        self,
        *,
        request: NestedCVExecutionRequest,
        dataset: PITResearchDataset,
        spec: MacroFactorRunnerSpec,
    ) -> object:
        return object()


class _MutatingExternalRunner:
    """Adapter double that changes only the copies supplied across its boundary."""

    def __init__(self, value: ExternalNestedCVArtifact) -> None:
        self.value = value

    def execute(
        self,
        *,
        request: NestedCVExecutionRequest,
        dataset: PITResearchDataset,
        spec: MacroFactorRunnerSpec,
    ) -> ExternalNestedCVArtifact:
        object.__setattr__(request, "dataset_hash", "f" * 64)
        object.__setattr__(dataset, "manifest_hash", "e" * 64)
        object.__setattr__(
            spec.input_knowledge_freshness_policy,
            "max_manifest_age_seconds",
            spec.input_knowledge_freshness_policy.max_manifest_age_seconds + 1,
        )
        return self.value


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _FailingManifestProvider:
    def get_manifest(self, manifest_id: str) -> object:
        raise RuntimeError(f"manifest provider failed for {manifest_id}")


class _FailingDatasetProvider:
    def get_dataset(
        self,
        *,
        manifest_id: str,
        manifest_hash: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
    ) -> object:
        raise RuntimeError(f"dataset provider failed for {manifest_id}")


class _MalformedDatasetProvider:
    def get_dataset(
        self,
        *,
        manifest_id: str,
        manifest_hash: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
    ) -> object:
        return object()


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
    spec = runner_spec()
    manifest = complete_manifest()
    freshness = spec.input_knowledge_freshness_policy
    return RunReproducibleMacroFactorCommand(
        spec=spec,
        expected_manifest_id="pit-r3-growth-v1",
        expected_manifest_hash="a" * 64,
        expected_manifest_content_hash=manifest.content_hash,
        expected_input_freshness_policy_version=freshness.policy_version,
        expected_input_freshness_policy_hash=freshness.content_hash,
        expected_max_manifest_age_seconds=freshness.max_manifest_age_seconds,
        expected_max_inference_age_seconds=freshness.max_inference_age_seconds,
        expected_maximum_allowed_age_seconds=freshness.maximum_allowed_age_seconds,
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


def test_same_manifest_identity_with_replaced_calendar_member_is_rejected() -> None:
    original = complete_manifest()
    member = original.inference_periods[0]
    replacement_member = PITInferenceCalendarPeriodEvidence.create(
        calendar_id=member.calendar_id,
        calendar_version=member.calendar_version,
        calendar_hash=member.calendar_hash,
        period_id=member.period_id,
        period_start=member.period_start,
        period_end=member.period_end + timedelta(days=1),
    )
    replacement = PITManifestEvidence.create(
        manifest_id=original.manifest_id,
        manifest_hash=original.manifest_hash,
        as_of_time=original.as_of_time,
        knowledge_scope=original.knowledge_scope,
        calendar_id=original.calendar_id,
        calendar_version=original.calendar_version,
        calendar_hash=original.calendar_hash,
        inference_periods=(replacement_member,),
        slices=original.slices,
        coverage_ratio=original.coverage_ratio,
        missing_count=original.missing_count,
        estimated_count=original.estimated_count,
        unknown_count=original.unknown_count,
        is_verified=original.is_verified,
    )
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(replacement),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=runner,
        repository=repository,
    ).execute(_command())

    assert replacement.manifest_hash == original.manifest_hash
    assert replacement.content_hash != original.content_hash
    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.PIT_MANIFEST_MISMATCH,)
    assert runner.requests == []
    assert repository.bundle is None


def test_freshness_governance_cap_and_live_policy_seal_are_required() -> None:
    with pytest.raises(ValueError, match="implementation cap"):
        InputKnowledgeFreshnessPolicy.create(
            policy_version="unbounded-input-freshness-v1",
            max_manifest_age_seconds=100 * 366 * 24 * 60 * 60,
            max_inference_age_seconds=100 * 366 * 24 * 60 * 60,
            maximum_allowed_age_seconds=100 * 366 * 24 * 60 * 60,
        )

    command = _command()
    object.__setattr__(
        command.spec.input_knowledge_freshness_policy,
        "max_manifest_age_seconds",
        200 * 366 * 24 * 60 * 60,
    )
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=runner,
        repository=repository,
    ).execute(command)

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert runner.requests == []
    assert repository.bundle is None


def test_freshness_policy_rejects_comparison_overriding_integer_subclasses() -> None:
    wide_age = WideInt(100 * 366 * 24 * 60 * 60)
    payload = {
        "policy_version": "wide-int-input-freshness-v1",
        "max_manifest_age_seconds": wide_age,
        "max_inference_age_seconds": 30 * 24 * 60 * 60,
        "maximum_allowed_age_seconds": wide_age,
    }

    with pytest.raises(ValueError, match="positive integer"):
        InputKnowledgeFreshnessPolicy.create(
            policy_version="wide-int-input-freshness-v1",
            max_manifest_age_seconds=wide_age,
            max_inference_age_seconds=30 * 24 * 60 * 60,
            maximum_allowed_age_seconds=wide_age,
        )
    with pytest.raises(ValueError, match="positive integer"):
        InputKnowledgeFreshnessPolicy(
            policy_version="wide-int-input-freshness-v1",
            max_manifest_age_seconds=wide_age,
            max_inference_age_seconds=30 * 24 * 60 * 60,
            maximum_allowed_age_seconds=wide_age,
            content_hash=hash_payload(payload),
        )


def test_command_live_validation_rejects_comparison_overriding_integer_subclass() -> None:
    command = _command()
    object.__setattr__(
        command,
        "expected_max_manifest_age_seconds",
        WideInt(command.expected_max_manifest_age_seconds),
    )
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=runner,
        repository=repository,
    ).execute(command)

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert runner.requests == []
    assert repository.bundle is None


def test_external_runner_receives_isolated_copies_and_mutation_prevents_write() -> None:
    source_dataset = runner_dataset()
    command = _command()
    source_dataset_hash = source_dataset.content_hash
    source_policy_hash = command.spec.input_knowledge_freshness_policy.content_hash
    repository = _Repository()

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(source_dataset),
        external_runner=_MutatingExternalRunner(external_runner_artifact()),
        repository=repository,
    ).execute(command)

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.EXTERNAL_ARTIFACT_INVALID,)
    assert source_dataset.content_hash == source_dataset_hash
    assert command.spec.input_knowledge_freshness_policy.content_hash == source_policy_hash
    assert repository.bundle is None


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


def test_legacy_external_runner_signature_is_blocked_without_writes() -> None:
    repository = _Repository()

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=_LegacyExternalRunner(),  # type: ignore[arg-type]
        repository=repository,
    ).execute(_command())

    assert assessment.status is MacroFactorRunnerStatus.BLOCKED
    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.EXTERNAL_RUNNER_UNAVAILABLE,)
    assert assessment.bundle is None
    assert repository.bundle is None


def test_future_evaluation_plan_is_blocked_before_numerical_execution_or_write() -> None:
    command = _command()
    spec = command.spec
    future_fold = replace(
        spec.plan.outer_folds[-1],
        evaluation_as_of=spec.calculated_at + timedelta(seconds=1),
    )
    object.__setattr__(
        spec,
        "plan",
        replace(
            spec.plan,
            outer_folds=(*spec.plan.outer_folds[:-1], future_fold),
        ),
    )
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=runner,
        repository=repository,
    ).execute(command)

    assert assessment.status is MacroFactorRunnerStatus.BLOCKED
    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert runner.requests == []
    assert repository.bundle is None

    manifest = complete_manifest()
    trusted_now = command.spec.calculated_at + timedelta(hours=1)
    object.__setattr__(manifest, "as_of_time", trusted_now + timedelta(microseconds=1))
    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(manifest),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=runner,
        repository=repository,
        clock=_Clock(trusted_now),
    ).execute(command)

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert runner.requests == []
    assert repository.bundle is None


def test_trusted_clock_rejects_future_calculation_and_owner_evidence() -> None:
    command = _command()
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())
    use_case = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=runner,
        repository=repository,
        clock=_Clock(command.spec.calculated_at - timedelta(microseconds=1)),
    )

    assessment = use_case.execute(command)

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert runner.requests == []
    assert repository.bundle is None


def test_missing_label_free_inference_row_is_blocked_before_runner_or_write() -> None:
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(replace(runner_dataset(), inference_row=None)),
        external_runner=runner,
        repository=repository,
        clock=_Clock(datetime(2026, 8, 9, tzinfo=UTC)),
    ).execute(_command())

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert runner.requests == []
    assert repository.bundle is None


@pytest.mark.parametrize(
    ("manifest_provider", "dataset_provider"),
    (
        (_FailingManifestProvider(), _DatasetProvider(runner_dataset())),
        (_ManifestProvider(object()), _DatasetProvider(runner_dataset())),
        (_ManifestProvider(complete_manifest()), _FailingDatasetProvider()),
        (_ManifestProvider(complete_manifest()), _MalformedDatasetProvider()),
    ),
)
def test_provider_failures_and_malformed_owner_objects_are_stably_blocked(
    manifest_provider: object,
    dataset_provider: object,
) -> None:
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())

    assessment = RunReproducibleMacroFactor(
        manifest_provider=manifest_provider,  # type: ignore[arg-type]
        dataset_provider=dataset_provider,  # type: ignore[arg-type]
        external_runner=runner,
        repository=repository,
        clock=_Clock(datetime(2026, 8, 9, tzinfo=UTC)),
    ).execute(_command())

    assert assessment.status is MacroFactorRunnerStatus.BLOCKED
    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert runner.requests == []
    assert repository.bundle is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("expected_manifest_id", object()),
        ("expected_manifest_hash", object()),
        ("expected_manifest_hash", "z" * 64),
    ),
)
def test_command_identity_is_revalidated_live_before_any_provider_or_runner_call(
    field: str,
    value: object,
) -> None:
    command = _command()
    object.__setattr__(command, field, value)
    repository = _Repository()
    runner = _ExternalRunner(external_runner_artifact())

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=runner,
        repository=repository,
        clock=_Clock(datetime(2026, 8, 9, tzinfo=UTC)),
    ).execute(command)

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.RUN_INPUT_INVALID,)
    assert runner.requests == []
    assert repository.bundle is None


def test_malformed_external_artifact_is_stably_blocked_without_a_write() -> None:
    repository = _Repository()

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=_MalformedExternalRunner(),  # type: ignore[arg-type]
        repository=repository,
        clock=_Clock(datetime(2026, 8, 9, tzinfo=UTC)),
    ).execute(_command())

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.EXTERNAL_ARTIFACT_INVALID,)
    assert repository.bundle is None


def test_external_artifact_is_resealed_live_before_output_persistence() -> None:
    repository = _Repository()
    artifact = external_runner_artifact()
    object.__setattr__(artifact.dated_outputs[0], "value", artifact.dated_outputs[0].value + 1)

    assessment = RunReproducibleMacroFactor(
        manifest_provider=_ManifestProvider(complete_manifest()),
        dataset_provider=_DatasetProvider(runner_dataset()),
        external_runner=_ExternalRunner(artifact),
        repository=repository,
        clock=_Clock(datetime(2026, 8, 9, tzinfo=UTC)),
    ).execute(_command())

    assert assessment.blocked_reasons == (MacroFactorRunnerBlockerCode.EXTERNAL_ARTIFACT_INVALID,)
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
        validity_policy=artifact.validity_policy,
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
