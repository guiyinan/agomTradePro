"""R1 Data Center actual-source and materialized-manifest contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.data_center.application.evaluation_actual_manifest import (
    EvaluationActualConflict,
    EvaluationActualUnavailable,
    MaterializeEvaluationActualManifestCommand,
    RegisterEvaluationActualSourceCommand,
)
from apps.data_center.domain.evaluation_actual_manifest import (
    ActualEvidenceIdentity,
    CanonicalEvaluationActualFact,
    CanonicalEvaluationActualGraph,
    EvaluationActualCoveragePolicy,
    EvaluationActualSourceDefinition,
    ExpectedActualMemberRule,
    MaterializedEvaluationActualManifest,
    PersistedEvaluationActualSourceDefinition,
)
from apps.data_center.evaluation_actual_manifest_composition import (
    _EvaluationActualManifestMaterializationWriter,
    _EvaluationActualSourceRegistrationWriter,
    build_django_evaluation_actual_runtime,
)
from apps.data_center.infrastructure.evaluation_actual_manifest_codec import (
    EvaluationActualCodecError,
    decode_materialized_evaluation_actual_manifest,
    decode_persisted_evaluation_actual_source_definition,
    encode_materialized_evaluation_actual_manifest,
    encode_persisted_evaluation_actual_source_definition,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
REGISTERED_AT = datetime(2025, 1, 1, 9, tzinfo=UTC)
AS_OF = datetime(2025, 3, 2, 9, tzinfo=UTC)
SERVER_NOW = datetime(2025, 3, 3, 9, tzinfo=UTC)
LEDGER_RECORDED_AT = datetime(2025, 1, 2, 9, tzinfo=UTC)
VALID_UNTIL = datetime(2026, 1, 1, 9, tzinfo=UTC)
PERIOD_END = date(2025, 2, 28)


def _identity(prefix: str, digest: str) -> ActualEvidenceIdentity:
    return ActualEvidenceIdentity(
        stable_id=f"{prefix}:revenue:2025-02",
        version=f"{prefix}.v1",
        content_hash=digest,
    )


def _definition(
    *,
    policy: EvaluationActualCoveragePolicy | None = None,
) -> EvaluationActualSourceDefinition:
    return EvaluationActualSourceDefinition.create(
        source_id="actual-source:600519",
        source_version="source.v1",
        owner="data_center",
        dataset="research.operating-actual.v1",
        subject_code="600519.SH",
        industry_code="consumer-staples",
        calendar=ActualEvidenceIdentity(
            stable_id="calendar:monthly",
            version="calendar.v1",
            content_hash=HASH_A,
        ),
        knowledge_scope="public",
        expected_members=(
            ExpectedActualMemberRule(
                period_end=PERIOD_END,
                metric_code="revenue",
                member=_identity("member", HASH_B),
                vintage=_identity("vintage", HASH_C),
            ),
        ),
        coverage_policy=policy
        or EvaluationActualCoveragePolicy(
            require_verified=True,
            minimum_coverage_ratio=Decimal("1"),
            maximum_missing_count=0,
            maximum_estimated_count=0,
            maximum_unknown_count=0,
        ),
        registered_at=REGISTERED_AT,
        valid_until=VALID_UNTIL,
    )


def _fact() -> CanonicalEvaluationActualFact:
    return CanonicalEvaluationActualFact(
        dataset="research.operating-actual.v1",
        subject_code="600519.SH",
        industry_code="consumer-staples",
        period_end=PERIOD_END,
        metric_code="revenue",
        value=Decimal("104"),
        unit="CNY",
        source_fact=_identity("fact", HASH_D),
        revision_number=1,
        effective_at=datetime(2025, 2, 28, 9, tzinfo=UTC),
        available_at=datetime(2025, 3, 1, 9, tzinfo=UTC),
        member=_identity("member", HASH_B),
        vintage=_identity("vintage", HASH_C),
        quality="verified",
    )


def _graph(
    *,
    facts: tuple[CanonicalEvaluationActualFact, ...] | None = None,
) -> CanonicalEvaluationActualGraph:
    definition = _definition()
    return CanonicalEvaluationActualGraph(
        source_definition=definition.identity,
        as_of_time=AS_OF,
        knowledge_scope="public",
        facts=facts if facts is not None else (_fact(),),
    )


class _Clock:
    unit_of_work_key = "django:default"

    def __init__(self, now: datetime = SERVER_NOW) -> None:
        self.value = now
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value


class _DefinitionProvider:
    unit_of_work_key = "django:default"

    def __init__(
        self,
        values: tuple[EvaluationActualSourceDefinition | None, ...],
    ) -> None:
        self.values = list(values)
        self.calls: list[tuple[str, str, datetime]] = []

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> EvaluationActualSourceDefinition | None:
        self.calls.append((source_id, source_version, as_of))
        return self.values.pop(0)


class _GraphProvider:
    unit_of_work_key = "django:default"

    def __init__(self, values: tuple[CanonicalEvaluationActualGraph | None, ...]) -> None:
        self.values = list(values)
        self.calls = 0

    def get_exact(
        self,
        *,
        definition: EvaluationActualSourceDefinition,
        as_of: datetime,
    ) -> CanonicalEvaluationActualGraph | None:
        self.calls += 1
        return self.values.pop(0)


class _Store:
    unit_of_work_key = "django:default"

    def __init__(self, *, fail_manifest: bool = False) -> None:
        self.definitions: list[PersistedEvaluationActualSourceDefinition] = []
        self.manifests: list[MaterializedEvaluationActualManifest] = []
        self.atomic_entries = 0
        self.fail_manifest = fail_manifest

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.atomic_entries += 1
        definition_count = len(self.definitions)
        manifest_count = len(self.manifests)
        try:
            yield
        except Exception:
            del self.definitions[definition_count:]
            del self.manifests[manifest_count:]
            raise

    def append_source_definition(
        self,
        record: PersistedEvaluationActualSourceDefinition,
    ) -> PersistedEvaluationActualSourceDefinition:
        self.definitions.append(record)
        return record

    def append_manifest(
        self,
        manifest: MaterializedEvaluationActualManifest,
    ) -> MaterializedEvaluationActualManifest:
        self.manifests.append(manifest)
        if self.fail_manifest:
            raise RuntimeError("append failed")
        return manifest


class _ReadRepository:
    unit_of_work_key = "django:default"

    def __init__(self, record: PersistedEvaluationActualSourceDefinition | None) -> None:
        self.record = record
        self.calls = 0

    def get_source_definition(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedEvaluationActualSourceDefinition | None:
        self.calls += 1
        return self.record


def _persisted_definition() -> PersistedEvaluationActualSourceDefinition:
    return PersistedEvaluationActualSourceDefinition.create(
        definition=_definition(),
        ledger_recorded_at=LEDGER_RECORDED_AT,
    )


def _registration_writer(
    provider: _DefinitionProvider,
    store: _Store,
    *,
    clock: _Clock | None = None,
) -> _EvaluationActualSourceRegistrationWriter:
    return _EvaluationActualSourceRegistrationWriter(
        definition_provider=provider,
        store=store,
        clock=clock or _Clock(),
    )


def _materialization_writer(
    graph_provider: _GraphProvider,
    store: _Store,
    *,
    repository: _ReadRepository | None = None,
    clock: _Clock | None = None,
) -> _EvaluationActualManifestMaterializationWriter:
    return _EvaluationActualManifestMaterializationWriter(
        repository=repository or _ReadRepository(_persisted_definition()),
        graph_provider=graph_provider,
        store=store,
        clock=clock or _Clock(),
    )


def test_definition_policy_is_versioned_not_hard_coded_to_r1_complete() -> None:
    permissive = EvaluationActualCoveragePolicy(
        require_verified=False,
        minimum_coverage_ratio=Decimal("0.5"),
        maximum_missing_count=2,
        maximum_estimated_count=1,
        maximum_unknown_count=1,
    )

    definition = _definition(policy=permissive)

    assert definition.coverage_policy == permissive
    assert definition.validated_copy() == definition


def test_source_registration_is_id_only_double_read_and_server_timed() -> None:
    definition = _definition()
    provider = _DefinitionProvider((definition, definition))
    store = _Store()
    command = RegisterEvaluationActualSourceCommand(
        source_id=definition.source_id,
        source_version=definition.source_version,
        as_of=AS_OF,
    )

    record = _registration_writer(provider, store).register(command)

    assert record.ledger_recorded_at == SERVER_NOW
    assert provider.calls == [
        (definition.source_id, definition.source_version, AS_OF),
        (definition.source_id, definition.source_version, SERVER_NOW),
    ]
    assert store.definitions == [record]


@pytest.mark.parametrize("failure", ["missing", "substitution", "future"])
def test_source_registration_failures_are_stable_and_zero_write(failure: str) -> None:
    definition = _definition()
    if failure == "missing":
        values = (None, None)
        as_of = AS_OF
    elif failure == "substitution":
        substituted = _definition()
        object.__setattr__(substituted, "industry_code", "substituted")
        values = (definition, substituted)
        as_of = AS_OF
    else:
        values = (definition, definition)
        as_of = SERVER_NOW.replace(year=2027)
    provider = _DefinitionProvider(values)
    store = _Store()

    with pytest.raises(EvaluationActualUnavailable):
        _registration_writer(provider, store).register(
            RegisterEvaluationActualSourceCommand(
                source_id=definition.source_id,
                source_version=definition.source_version,
                as_of=as_of,
            )
        )

    assert store.definitions == []


def test_materialization_double_reads_and_builds_complete_manifest_internally() -> None:
    graph = _graph()
    graph_provider = _GraphProvider((graph, graph))
    store = _Store()
    command = MaterializeEvaluationActualManifestCommand(
        manifest_id="actual-manifest:600519:2025-02",
        manifest_version="manifest.v1",
        source_id="actual-source:600519",
        source_version="source.v1",
        as_of=AS_OF,
    )

    manifest = _materialization_writer(graph_provider, store).materialize(command)

    assert graph_provider.calls == 2
    assert manifest.produced_at == SERVER_NOW
    assert manifest.coverage_ratio == Decimal("1")
    assert manifest.is_verified is True
    assert manifest.missing_count == manifest.estimated_count == manifest.unknown_count == 0
    assert manifest.facts == (_fact(),)
    assert store.manifests == [manifest]


@pytest.mark.parametrize("missing", ["member", "vintage"])
def test_missing_member_or_vintage_fails_closed_without_append(missing: str) -> None:
    fact = _fact()
    object.__setattr__(fact, missing, None)
    graph = _graph(facts=(fact,))
    store = _Store()

    with pytest.raises(EvaluationActualUnavailable):
        _materialization_writer(_GraphProvider((graph, graph)), store).materialize(
            MaterializeEvaluationActualManifestCommand(
                manifest_id="actual-manifest:600519:2025-02",
                manifest_version="manifest.v1",
                source_id="actual-source:600519",
                source_version="source.v1",
                as_of=AS_OF,
            )
        )

    assert store.manifests == []


def test_graph_substitution_and_append_failure_leave_zero_manifest_writes() -> None:
    graph = _graph()
    substituted = replace(graph, knowledge_scope="system")
    store = _Store()
    command = MaterializeEvaluationActualManifestCommand(
        manifest_id="actual-manifest:600519:2025-02",
        manifest_version="manifest.v1",
        source_id="actual-source:600519",
        source_version="source.v1",
        as_of=AS_OF,
    )

    with pytest.raises(EvaluationActualUnavailable):
        _materialization_writer(_GraphProvider((graph, substituted)), store).materialize(command)
    assert store.manifests == []

    rollback_store = _Store(fail_manifest=True)
    with pytest.raises(EvaluationActualUnavailable):
        _materialization_writer(_GraphProvider((graph, graph)), rollback_store).materialize(command)
    assert rollback_store.manifests == []


@pytest.mark.parametrize(
    "command_factory",
    [
        lambda: RegisterEvaluationActualSourceCommand(
            source_id="actual-source:600519", source_version="source.v1", as_of=AS_OF
        ),
        lambda: MaterializeEvaluationActualManifestCommand(
            manifest_id="actual-manifest:600519:2025-02",
            manifest_version="manifest.v1",
            source_id="actual-source:600519",
            source_version="source.v1",
            as_of=AS_OF,
        ),
    ],
)
def test_commands_have_live_exact_type_validation(
    command_factory: Callable[
        [],
        RegisterEvaluationActualSourceCommand | MaterializeEvaluationActualManifestCommand,
    ],
) -> None:
    command = command_factory()
    object.__setattr__(command, "as_of", datetime(2025, 1, 1))
    store = _Store()

    with pytest.raises(EvaluationActualUnavailable):
        if type(command) is RegisterEvaluationActualSourceCommand:
            _registration_writer(
                _DefinitionProvider((_definition(), _definition())), store
            ).register(command)
        else:
            _materialization_writer(_GraphProvider((_graph(), _graph())), store).materialize(
                command
            )

    assert store.atomic_entries == 0


def test_codecs_round_trip_and_reject_live_seal_or_shape_tampering() -> None:
    definition_record = _persisted_definition()
    encoded_definition = encode_persisted_evaluation_actual_source_definition(definition_record)
    assert (
        decode_persisted_evaluation_actual_source_definition(encoded_definition)
        == definition_record
    )

    manifest = _materialization_writer(_GraphProvider((_graph(), _graph())), _Store()).materialize(
        MaterializeEvaluationActualManifestCommand(
            manifest_id="actual-manifest:600519:2025-02",
            manifest_version="manifest.v1",
            source_id="actual-source:600519",
            source_version="source.v1",
            as_of=AS_OF,
        )
    )
    encoded_manifest = encode_materialized_evaluation_actual_manifest(manifest)
    assert decode_materialized_evaluation_actual_manifest(encoded_manifest) == manifest

    tampered = {**encoded_manifest, "receipt_hash": HASH_E}
    with pytest.raises(EvaluationActualCodecError):
        decode_materialized_evaluation_actual_manifest(tampered)
    with pytest.raises(EvaluationActualCodecError):
        decode_materialized_evaluation_actual_manifest({**encoded_manifest, "unexpected": True})


def test_production_runtime_has_inert_writes_and_read_only_provider() -> None:
    runtime = build_django_evaluation_actual_runtime()
    register_command = RegisterEvaluationActualSourceCommand(
        source_id="actual-source:600519",
        source_version="source.v1",
        as_of=AS_OF,
    )
    materialize_command = MaterializeEvaluationActualManifestCommand(
        manifest_id="actual-manifest:600519:2025-02",
        manifest_version="manifest.v1",
        source_id="actual-source:600519",
        source_version="source.v1",
        as_of=AS_OF,
    )

    with pytest.raises(EvaluationActualUnavailable, match="canonical owner"):
        runtime.register_source.execute(register_command)
    with pytest.raises(EvaluationActualUnavailable, match="canonical owner"):
        runtime.materialize.execute(materialize_command)
    assert not hasattr(runtime.actual_provider, "_store")


def test_domain_fork_is_not_equal_to_the_canonical_winner() -> None:
    winner = _persisted_definition()
    with pytest.raises(ValueError):
        replace(winner.definition, industry_code="other")
    assert winner.validated_copy() == winner
    assert EvaluationActualConflict.__mro__[1] is ValueError
