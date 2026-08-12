"""R1 Research-owned forecast-trial preregistration contracts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.equity.application.forecast_baseline_evaluation import (
    forecast_baseline_trial_parameter_hash,
    forecast_baseline_trial_split_hash,
)
from apps.equity.domain.forecast_baseline import (
    ForecastBaselineArtifact,
    ForecastBaselineSpec,
)
from apps.research.application.r1_forecast_trial_evidence import (
    R1ForecastTrialEvidenceUnavailable,
    RegisterR1ForecastTrialEvidence,
    RegisterR1ForecastTrialEvidenceCommand,
)
from apps.research.domain.r1_forecast_trial_evidence import (
    PersistedR1ForecastTrialEvidence,
    R1ForecastTrialDefinition,
)
from apps.research.infrastructure.r1_forecast_trial_evidence_codec import (
    R1ForecastTrialEvidenceCodecError,
    decode_r1_forecast_trial_evidence,
    encode_r1_forecast_trial_evidence,
)
from tests.unit.equity.test_forecast_baseline_application import ORIGIN, _build_artifact


class _DefinitionProvider:
    def __init__(
        self,
        definition: R1ForecastTrialDefinition | None,
        *,
        reads: tuple[R1ForecastTrialDefinition | None, ...] | None = None,
        unit_of_work_key: object = "default",
    ) -> None:
        self.definition = definition
        self.reads = reads
        self._unit_of_work_key = unit_of_work_key
        self.calls = 0

    @property
    def unit_of_work_key(self) -> object:
        return self._unit_of_work_key

    def get_exact(
        self,
        *,
        definition_id: str,
        definition_version: str,
        as_of: datetime,
    ) -> R1ForecastTrialDefinition | None:
        del definition_id, definition_version, as_of
        index = self.calls
        self.calls += 1
        if self.reads is not None:
            return self.reads[min(index, len(self.reads) - 1)]
        return self.definition


class _BaselineProvider:
    def __init__(
        self,
        spec: ForecastBaselineSpec | None,
        artifact: ForecastBaselineArtifact | None,
        *,
        unit_of_work_key: object = "default",
    ) -> None:
        self.spec = spec
        self.artifact = artifact
        self._unit_of_work_key = unit_of_work_key
        self.spec_calls = 0
        self.artifact_calls = 0

    @property
    def unit_of_work_key(self) -> object:
        return self._unit_of_work_key

    def get_spec(
        self,
        *,
        spec_id: str,
        spec_version: str,
        as_of: datetime,
    ) -> ForecastBaselineSpec | None:
        del spec_id, spec_version, as_of
        self.spec_calls += 1
        return self.spec

    def get_artifact(
        self,
        *,
        artifact_id: str,
        artifact_version: str,
        as_of: datetime,
    ) -> ForecastBaselineArtifact | None:
        del artifact_id, artifact_version, as_of
        self.artifact_calls += 1
        return self.artifact


class _Store:
    def __init__(self, *, unit_of_work_key: object = "default") -> None:
        self._unit_of_work_key = unit_of_work_key
        self.rows: list[PersistedR1ForecastTrialEvidence] = []
        self.substitute = False

    @property
    def unit_of_work_key(self) -> object:
        return self._unit_of_work_key

    @contextmanager
    def atomic(self) -> Iterator[None]:
        before = list(self.rows)
        try:
            yield
        except Exception:
            self.rows = before
            raise

    def append(
        self, evidence: PersistedR1ForecastTrialEvidence
    ) -> PersistedR1ForecastTrialEvidence:
        self.rows.append(evidence)
        if self.substitute:
            return PersistedR1ForecastTrialEvidence.create(
                evidence_id=evidence.evidence_id,
                evidence_version="substituted",
                definition=evidence.definition,
                baseline_spec_approved_at=evidence.baseline_spec_approved_at,
                forecast_origin_at=evidence.forecast_origin_at,
                recorded_at=evidence.recorded_at,
            )
        return evidence


class _Clock:
    def __init__(
        self,
        now: datetime = ORIGIN,
        *,
        unit_of_work_key: object = "default",
    ) -> None:
        self.value = now
        self._unit_of_work_key = unit_of_work_key
        self.calls = 0

    @property
    def unit_of_work_key(self) -> object:
        return self._unit_of_work_key

    def now(self) -> datetime:
        self.calls += 1
        return self.value


def _graph() -> tuple[
    ForecastBaselineSpec,
    ForecastBaselineArtifact,
    R1ForecastTrialDefinition,
]:
    spec, artifact, _, _ = _build_artifact()
    forecasts = tuple(replace(item, persisted_at=ORIGIN) for item in artifact.forecasts)
    artifact = ForecastBaselineArtifact.create(
        artifact_id=artifact.artifact_id,
        artifact_version=artifact.artifact_version,
        owner="equity",
        spec=spec,
        forecasts=forecasts,
        predictions=artifact.predictions,
        knowledge_as_of=ORIGIN,
        produced_at=ORIGIN,
        valid_until=artifact.valid_until,
    )
    definition = R1ForecastTrialDefinition.create(
        definition_id="research-trial-definition-001",
        definition_version="v1",
        baseline_spec_id=spec.spec_id,
        baseline_spec_version=spec.spec_version,
        baseline_spec_content_hash=spec.content_hash,
        baseline_artifact_id=artifact.artifact_id,
        baseline_artifact_version=artifact.artifact_version,
        baseline_artifact_content_hash=artifact.content_hash,
        split_spec_hash=forecast_baseline_trial_split_hash(spec),
        parameter_hash=forecast_baseline_trial_parameter_hash(spec),
        calendar_id=spec.calendar_schedule.calendar_id,
        calendar_version=spec.calendar_schedule.calendar_version,
        calendar_schedule_hash=spec.calendar_schedule.content_hash,
        expected_period_ends=spec.expected_period_ends,
        metric_codes=tuple(item.metric_code for item in spec.metric_rules),
        evaluation_policy=spec.evaluation_policy,
        activated_at=spec.approval_recorded_at,
        valid_until=artifact.valid_until - timedelta(seconds=1),
    )
    return spec, artifact, definition


def _command(*, as_of: datetime = ORIGIN) -> RegisterR1ForecastTrialEvidenceCommand:
    return RegisterR1ForecastTrialEvidenceCommand(
        evidence_id="research-trial-001",
        evidence_version="v1",
        definition_id="research-trial-definition-001",
        definition_version="v1",
        spec_id="baseline-spec:consumer",
        spec_version="spec.v1",
        artifact_id="baseline-artifact:consumer",
        artifact_version="artifact.v1",
        as_of=as_of,
    )


def _runtime(
    *,
    definition_provider: _DefinitionProvider | None = None,
    baseline_provider: _BaselineProvider | None = None,
    store: _Store | None = None,
    clock: _Clock | None = None,
) -> tuple[
    RegisterR1ForecastTrialEvidence,
    _DefinitionProvider,
    _BaselineProvider,
    _Store,
    _Clock,
]:
    spec, artifact, definition = _graph()
    definitions = definition_provider or _DefinitionProvider(definition)
    baselines = baseline_provider or _BaselineProvider(spec, artifact)
    ledger = store or _Store()
    trusted_clock = clock or _Clock()
    use_case = RegisterR1ForecastTrialEvidence(
        definition_provider=definitions,
        baseline_provider=baselines,
        store=ledger,
        clock=trusted_clock,
    )
    return use_case, definitions, baselines, ledger, trusted_clock


def test_registration_command_is_id_only_and_live_sealed() -> None:
    command = RegisterR1ForecastTrialEvidenceCommand(
        evidence_id="research-trial-001",
        evidence_version="v1",
        definition_id="research-trial-definition-001",
        definition_version="v1",
        spec_id="equity-baseline-spec-001",
        spec_version="v1",
        artifact_id="equity-baseline-artifact-001",
        artifact_version="v1",
        as_of=datetime(2025, 1, 26, 9, tzinfo=UTC),
    )

    assert tuple(command.__dataclass_fields__) == (
        "evidence_id",
        "evidence_version",
        "definition_id",
        "definition_version",
        "spec_id",
        "spec_version",
        "artifact_id",
        "artifact_version",
        "as_of",
    )

    object.__setattr__(command, "spec_id", "")
    with pytest.raises(ValueError, match="spec_id"):
        command.__post_init__()


def test_registration_double_reads_full_graph_and_uses_server_clock() -> None:
    use_case, definitions, baselines, store, clock = _runtime()

    result = use_case.execute(_command())

    assert result.recorded_at == ORIGIN
    assert result.definition.activated_at < result.recorded_at
    assert result.recorded_at == result.forecast_origin_at
    assert definitions.calls == 2
    assert baselines.spec_calls == 2
    assert baselines.artifact_calls == 2
    assert clock.calls == 1
    assert store.rows == [result]


@pytest.mark.parametrize("field_name", ["evidence_id", "definition_id", "artifact_version"])
def test_mutated_command_is_rejected_before_reads_or_writes(field_name: str) -> None:
    use_case, definitions, baselines, store, clock = _runtime()
    command = _command()
    object.__setattr__(command, field_name, "")

    with pytest.raises(R1ForecastTrialEvidenceUnavailable):
        use_case.execute(command)

    assert (definitions.calls, baselines.spec_calls, baselines.artifact_calls) == (0, 0, 0)
    assert clock.calls == 0
    assert store.rows == []


def test_command_subclass_with_noop_validator_is_rejected_before_reads() -> None:
    class _Bypass(RegisterR1ForecastTrialEvidenceCommand):
        def __post_init__(self) -> None:
            pass

    use_case, definitions, baselines, store, clock = _runtime()
    base = _command()
    command = _Bypass(**base.__dict__)

    with pytest.raises(R1ForecastTrialEvidenceUnavailable):
        use_case.execute(command)

    assert (definitions.calls, baselines.spec_calls, clock.calls, store.rows) == (0, 0, 0, [])


def test_future_cutoff_is_stable_failure_with_zero_owner_reads() -> None:
    use_case, definitions, baselines, store, clock = _runtime()

    with pytest.raises(R1ForecastTrialEvidenceUnavailable, match="future"):
        use_case.execute(_command(as_of=ORIGIN + timedelta(seconds=1)))

    assert (definitions.calls, baselines.spec_calls, clock.calls, store.rows) == (0, 0, 1, [])


def test_missing_owner_input_is_stable_failure_with_zero_write() -> None:
    use_case, definitions, baselines, store, _ = _runtime(
        definition_provider=_DefinitionProvider(None)
    )

    with pytest.raises(R1ForecastTrialEvidenceUnavailable, match="definition"):
        use_case.execute(_command())

    assert definitions.calls == 1
    assert baselines.spec_calls == 1
    assert store.rows == []


def test_owner_graph_change_between_reads_is_rejected() -> None:
    spec, artifact, definition = _graph()
    changed = R1ForecastTrialDefinition.create(
        definition_id=definition.definition_id,
        definition_version=definition.definition_version,
        baseline_spec_id=definition.baseline_spec_id,
        baseline_spec_version=definition.baseline_spec_version,
        baseline_spec_content_hash=definition.baseline_spec_content_hash,
        baseline_artifact_id=definition.baseline_artifact_id,
        baseline_artifact_version=definition.baseline_artifact_version,
        baseline_artifact_content_hash=definition.baseline_artifact_content_hash,
        split_spec_hash=definition.split_spec_hash,
        parameter_hash=definition.parameter_hash,
        calendar_id=definition.calendar_id,
        calendar_version=definition.calendar_version,
        calendar_schedule_hash=definition.calendar_schedule_hash,
        expected_period_ends=definition.expected_period_ends,
        metric_codes=definition.metric_codes,
        evaluation_policy=definition.evaluation_policy,
        activated_at=definition.activated_at + timedelta(seconds=1),
        valid_until=definition.valid_until,
    )
    provider = _DefinitionProvider(definition, reads=(definition, changed))
    use_case, _, _, store, _ = _runtime(
        definition_provider=provider,
        baseline_provider=_BaselineProvider(spec, artifact),
    )

    with pytest.raises(R1ForecastTrialEvidenceUnavailable, match="changed"):
        use_case.execute(_command())

    assert store.rows == []


def test_store_substitution_rolls_back_the_append() -> None:
    store = _Store()
    store.substitute = True
    use_case, _, _, _, _ = _runtime(store=store)

    with pytest.raises(R1ForecastTrialEvidenceUnavailable, match="substituted"):
        use_case.execute(_command())

    assert store.rows == []


@pytest.mark.parametrize("bad_key", ["other", "", 7])
def test_constructor_rejects_non_shared_or_non_exact_uow(bad_key: object) -> None:
    spec, artifact, definition = _graph()

    with pytest.raises(R1ForecastTrialEvidenceUnavailable):
        RegisterR1ForecastTrialEvidence(
            definition_provider=_DefinitionProvider(definition),
            baseline_provider=_BaselineProvider(spec, artifact),
            store=_Store(unit_of_work_key=bad_key),
            clock=_Clock(),
        )


def test_live_uow_replacement_is_rejected_before_clock_or_read() -> None:
    use_case, definitions, baselines, store, clock = _runtime()
    store._unit_of_work_key = "replaced"

    with pytest.raises(R1ForecastTrialEvidenceUnavailable, match="UoW"):
        use_case.execute(_command())

    assert (definitions.calls, baselines.spec_calls, clock.calls, store.rows) == (0, 0, 0, [])


def test_definition_live_seal_failure_is_normalized_with_zero_write() -> None:
    spec, artifact, definition = _graph()
    object.__setattr__(definition, "purpose", "execution")
    use_case, _, _, store, _ = _runtime(
        definition_provider=_DefinitionProvider(definition),
        baseline_provider=_BaselineProvider(spec, artifact),
    )

    with pytest.raises(R1ForecastTrialEvidenceUnavailable):
        use_case.execute(_command())

    assert store.rows == []


def test_codec_roundtrip_preserves_the_complete_owner_graph() -> None:
    use_case, _, _, _, _ = _runtime()
    evidence = use_case.execute(_command())

    restored = decode_r1_forecast_trial_evidence(encode_r1_forecast_trial_evidence(evidence))

    assert restored == evidence
    assert restored.definition.evaluation_keys == tuple(
        (period_end, metric_code)
        for period_end in restored.definition.expected_period_ends
        for metric_code in restored.definition.metric_codes
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("content_hash", "0" * 64), ("research_only", False)],
)
def test_codec_rejects_tampered_receipt_seals(field_name: str, value: object) -> None:
    use_case, _, _, _, _ = _runtime()
    payload = encode_r1_forecast_trial_evidence(use_case.execute(_command()))
    payload[field_name] = value

    with pytest.raises(R1ForecastTrialEvidenceCodecError):
        decode_r1_forecast_trial_evidence(payload)


def test_codec_rejects_extra_definition_authority_fields() -> None:
    use_case, _, _, _, _ = _runtime()
    payload = encode_r1_forecast_trial_evidence(use_case.execute(_command()))
    definition = payload["definition"]
    assert type(definition) is dict
    definition["caller_authorization"] = True

    with pytest.raises(R1ForecastTrialEvidenceCodecError):
        decode_r1_forecast_trial_evidence(payload)
