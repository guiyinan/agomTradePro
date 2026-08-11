"""Production-safe composition for R1 evaluation actual evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError

from apps.data_center.application.evaluation_actual_manifest import (
    EvaluationActualAtomicStore,
    EvaluationActualClock,
    EvaluationActualConflict,
    EvaluationActualReadRepository,
    EvaluationActualUnavailable,
    ExactEvaluationActualGraphProvider,
    ExactEvaluationActualSourceDefinitionProvider,
    GetExactEvaluationActualSource,
    MaterializeEvaluationActualManifest,
    MaterializeEvaluationActualManifestCommand,
    RegisterEvaluationActualSource,
    RegisterEvaluationActualSourceCommand,
)
from apps.data_center.domain.evaluation_actual_manifest import (
    CanonicalEvaluationActualGraph,
    EvaluationActualSourceDefinition,
    MaterializedEvaluationActualManifest,
    PersistedEvaluationActualSourceDefinition,
)
from apps.data_center.infrastructure.evaluation_actual_manifest_repository import (
    DjangoEvaluationActualClock,
    DjangoEvaluationActualEvidenceProvider,
    DjangoEvaluationActualGraphProvider,
    DjangoEvaluationActualRepository,
    DjangoEvaluationActualSourceDefinitionProvider,
    _DjangoEvaluationActualStore,
)


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise EvaluationActualUnavailable("evaluation actual unit of work is invalid")
    return value


def _trusted_now(clock: EvaluationActualClock) -> datetime:
    now = clock.now()
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise EvaluationActualUnavailable("evaluation actual server clock is naive")
    return now


def _validate_registration_command(command: RegisterEvaluationActualSourceCommand) -> None:
    try:
        if type(command) is not RegisterEvaluationActualSourceCommand:
            raise TypeError
        RegisterEvaluationActualSourceCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise EvaluationActualUnavailable(
            "evaluation actual source registration command is invalid"
        ) from error


def _validate_materialization_command(
    command: MaterializeEvaluationActualManifestCommand,
) -> None:
    try:
        if type(command) is not MaterializeEvaluationActualManifestCommand:
            raise TypeError
        MaterializeEvaluationActualManifestCommand.__post_init__(command)
    except (AttributeError, TypeError, ValueError) as error:
        raise EvaluationActualUnavailable(
            "evaluation actual materialization command is invalid"
        ) from error


class _EvaluationActualSourceRegistrationWriter:
    """Private source writer that double-reads one owner inside one UoW."""

    __slots__ = (
        "_clock",
        "_definition_provider",
        "_expected_uow_key",
        "_store",
    )

    def __init__(
        self,
        *,
        definition_provider: ExactEvaluationActualSourceDefinitionProvider,
        store: EvaluationActualAtomicStore,
        clock: EvaluationActualClock,
    ) -> None:
        self._definition_provider = definition_provider
        self._store = store
        self._clock = clock
        self._expected_uow_key = self._validate_uow()

    def register(
        self,
        command: RegisterEvaluationActualSourceCommand,
    ) -> PersistedEvaluationActualSourceDefinition:
        """Resolve only IDs, double-read the owner and append atomically."""

        _validate_registration_command(command)
        try:
            self._validate_uow()
            with self._store.atomic():
                self._validate_uow()
                first = self._read_definition(command, as_of=command.as_of)
                self._validate_uow()
                recorded_at = _trusted_now(self._clock)
                if command.as_of > recorded_at:
                    raise EvaluationActualUnavailable(
                        "future evaluation actual source registration cutoff"
                    )
                second = self._read_definition(command, as_of=recorded_at)
                if first != second:
                    raise EvaluationActualUnavailable(
                        "evaluation actual source changed during registration"
                    )
                if not (second.registered_at <= command.as_of and recorded_at < second.valid_until):
                    raise EvaluationActualUnavailable(
                        "evaluation actual source is outside its owner validity"
                    )
                record = PersistedEvaluationActualSourceDefinition.create(
                    definition=second,
                    ledger_recorded_at=recorded_at,
                )
                self._validate_uow()
                winner = self._store.append_source_definition(record)
                self._validate_uow()
                if winner != record:
                    raise EvaluationActualUnavailable(
                        "source repository did not preserve the exact record"
                    )
                return winner
        except (EvaluationActualConflict, EvaluationActualUnavailable):
            raise
        except IntegrityError as error:
            raise EvaluationActualConflict("evaluation actual source append race lost") from error
        except Exception as error:
            raise EvaluationActualUnavailable(
                "evaluation actual canonical owner, clock, or store is unavailable"
            ) from error

    def _read_definition(
        self,
        command: RegisterEvaluationActualSourceCommand,
        *,
        as_of: datetime,
    ) -> EvaluationActualSourceDefinition:
        definition = self._definition_provider.get_exact(
            source_id=command.source_id,
            source_version=command.source_version,
            as_of=as_of,
        )
        if definition is None:
            raise EvaluationActualUnavailable(
                "exact evaluation actual source definition is unavailable"
            )
        if type(definition) is not EvaluationActualSourceDefinition:
            raise EvaluationActualUnavailable(
                "evaluation actual source definition type is not exact"
            )
        validated = definition.validated_copy()
        if (
            validated.source_id != command.source_id
            or validated.source_version != command.source_version
        ):
            raise EvaluationActualUnavailable(
                "evaluation actual source owner identity substitution"
            )
        return validated

    def _validate_uow(self) -> str:
        keys = {
            _exact_uow_key(self._definition_provider.unit_of_work_key),
            _exact_uow_key(self._store.unit_of_work_key),
            _exact_uow_key(self._clock.unit_of_work_key),
        }
        if len(keys) != 1:
            raise EvaluationActualUnavailable(
                "evaluation actual source owners require one unit of work"
            )
        key = next(iter(keys))
        if hasattr(self, "_expected_uow_key") and key != self._expected_uow_key:
            raise EvaluationActualUnavailable("evaluation actual source unit of work changed")
        return key


class _EvaluationActualManifestMaterializationWriter:
    """Private writer that double-reads canonical fact/member evidence."""

    __slots__ = (
        "_clock",
        "_expected_uow_key",
        "_graph_provider",
        "_repository",
        "_store",
    )

    def __init__(
        self,
        *,
        repository: EvaluationActualReadRepository,
        graph_provider: ExactEvaluationActualGraphProvider,
        store: EvaluationActualAtomicStore,
        clock: EvaluationActualClock,
    ) -> None:
        self._repository = repository
        self._graph_provider = graph_provider
        self._store = store
        self._clock = clock
        self._expected_uow_key = self._validate_uow()

    def materialize(
        self,
        command: MaterializeEvaluationActualManifestCommand,
    ) -> MaterializedEvaluationActualManifest:
        """Build a complete snapshot internally from two exact owner reads."""

        _validate_materialization_command(command)
        try:
            self._validate_uow()
            with self._store.atomic():
                self._validate_uow()
                first_definition = self._read_definition(command)
                first_graph = self._read_graph(first_definition, command.as_of)
                self._validate_uow()
                produced_at = _trusted_now(self._clock)
                if command.as_of > produced_at:
                    raise EvaluationActualUnavailable(
                        "future evaluation actual materialization cutoff"
                    )
                second_definition = self._read_definition(command)
                second_graph = self._read_graph(second_definition, command.as_of)
                if first_definition != second_definition or first_graph != second_graph:
                    raise EvaluationActualUnavailable(
                        "evaluation actual owner graph changed during materialization"
                    )
                manifest = MaterializedEvaluationActualManifest.materialize(
                    manifest_id=command.manifest_id,
                    manifest_version=command.manifest_version,
                    definition=second_definition,
                    graph=second_graph,
                    produced_at=produced_at,
                )
                self._validate_uow()
                winner = self._store.append_manifest(manifest)
                self._validate_uow()
                if winner != manifest:
                    raise EvaluationActualUnavailable(
                        "manifest repository did not preserve the exact receipt"
                    )
                return winner
        except (EvaluationActualConflict, EvaluationActualUnavailable):
            raise
        except IntegrityError as error:
            raise EvaluationActualConflict("evaluation actual manifest append race lost") from error
        except Exception as error:
            raise EvaluationActualUnavailable(
                "evaluation actual canonical owner, clock, or store is unavailable"
            ) from error

    def _read_definition(
        self,
        command: MaterializeEvaluationActualManifestCommand,
    ) -> EvaluationActualSourceDefinition:
        record = self._repository.get_source_definition(
            source_id=command.source_id,
            source_version=command.source_version,
            as_of=command.as_of,
        )
        if record is None:
            raise EvaluationActualUnavailable(
                "registered evaluation actual source definition is unavailable"
            )
        if type(record) is not PersistedEvaluationActualSourceDefinition:
            raise EvaluationActualUnavailable(
                "registered evaluation actual source record type is not exact"
            )
        validated = record.validated_copy().definition
        if (
            validated.source_id != command.source_id
            or validated.source_version != command.source_version
        ):
            raise EvaluationActualUnavailable(
                "registered evaluation actual source identity substitution"
            )
        return validated

    def _read_graph(
        self,
        definition: EvaluationActualSourceDefinition,
        as_of: datetime,
    ) -> CanonicalEvaluationActualGraph:
        graph = self._graph_provider.get_exact(definition=definition, as_of=as_of)
        if graph is None:
            raise EvaluationActualUnavailable(
                "canonical evaluation actual fact/member graph is unavailable"
            )
        if type(graph) is not CanonicalEvaluationActualGraph:
            raise EvaluationActualUnavailable("canonical evaluation actual graph type is not exact")
        return graph.validated_copy()

    def _validate_uow(self) -> str:
        keys = {
            _exact_uow_key(self._repository.unit_of_work_key),
            _exact_uow_key(self._graph_provider.unit_of_work_key),
            _exact_uow_key(self._store.unit_of_work_key),
            _exact_uow_key(self._clock.unit_of_work_key),
        }
        if len(keys) != 1:
            raise EvaluationActualUnavailable(
                "evaluation actual materialization requires one unit of work"
            )
        key = next(iter(keys))
        if hasattr(self, "_expected_uow_key") and key != self._expected_uow_key:
            raise EvaluationActualUnavailable(
                "evaluation actual materialization unit of work changed"
            )
        return key


class _UnavailableEvaluationActualSourceRegistration:
    """State-free production writer while no canonical owner is composed."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterEvaluationActualSourceCommand,
    ) -> PersistedEvaluationActualSourceDefinition:
        """Validate the ID-only command, then fail without a store graph."""

        _validate_registration_command(command)
        raise EvaluationActualUnavailable(
            "evaluation actual canonical owner definition provider is unavailable"
        )


class _UnavailableEvaluationActualManifestMaterialization:
    """State-free production writer while canonical fact owners are absent."""

    __slots__ = ()

    def execute(
        self,
        command: MaterializeEvaluationActualManifestCommand,
    ) -> MaterializedEvaluationActualManifest:
        """Validate the ID-only command, then fail without a store graph."""

        _validate_materialization_command(command)
        raise EvaluationActualUnavailable(
            "evaluation actual canonical owner fact/member provider is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoEvaluationActualRuntime:
    """Production inert mutations plus exact read-only capabilities."""

    register_source: _UnavailableEvaluationActualSourceRegistration
    materialize: _UnavailableEvaluationActualManifestMaterialization
    get_source: GetExactEvaluationActualSource
    actual_provider: DjangoEvaluationActualEvidenceProvider


@dataclass(frozen=True, slots=True)
class _DjangoEvaluationActualTestRuntime:
    """Private injectable runtime used only by synthetic persistence tests."""

    register_source: RegisterEvaluationActualSource
    materialize: MaterializeEvaluationActualManifest
    get_source: GetExactEvaluationActualSource
    actual_provider: DjangoEvaluationActualEvidenceProvider
    repository: DjangoEvaluationActualRepository


def build_django_evaluation_actual_runtime(
    *,
    using: str = "default",
) -> DjangoEvaluationActualRuntime:
    """Build no mutation/store graph while canonical owners are unavailable."""

    repository = DjangoEvaluationActualRepository(using=using)
    return DjangoEvaluationActualRuntime(
        register_source=_UnavailableEvaluationActualSourceRegistration(),
        materialize=_UnavailableEvaluationActualManifestMaterialization(),
        get_source=GetExactEvaluationActualSource(repository),
        actual_provider=DjangoEvaluationActualEvidenceProvider(repository),
    )


def _build_django_evaluation_actual_test_runtime(
    *,
    definition_provider: ExactEvaluationActualSourceDefinitionProvider,
    graph_provider: ExactEvaluationActualGraphProvider,
    using: str = "default",
    clock: EvaluationActualClock | None = None,
) -> _DjangoEvaluationActualTestRuntime:
    """Build the private shared-UoW runtime for synthetic owner tests."""

    authoritative_clock = clock or DjangoEvaluationActualClock(using=using)
    repository = DjangoEvaluationActualRepository(
        using=using,
        clock=authoritative_clock,
    )
    store = _DjangoEvaluationActualStore(using=using)
    source = DjangoEvaluationActualSourceDefinitionProvider(definition_provider)
    graph = DjangoEvaluationActualGraphProvider(graph_provider)
    keys = {
        _exact_uow_key(repository.unit_of_work_key),
        _exact_uow_key(store.unit_of_work_key),
        _exact_uow_key(source.unit_of_work_key),
        _exact_uow_key(graph.unit_of_work_key),
        _exact_uow_key(authoritative_clock.unit_of_work_key),
    }
    if len(keys) != 1:
        raise EvaluationActualUnavailable(
            "evaluation actual test runtime requires one shared unit of work"
        )
    return _DjangoEvaluationActualTestRuntime(
        register_source=RegisterEvaluationActualSource(
            _EvaluationActualSourceRegistrationWriter(
                definition_provider=source,
                store=store,
                clock=authoritative_clock,
            )
        ),
        materialize=MaterializeEvaluationActualManifest(
            _EvaluationActualManifestMaterializationWriter(
                repository=repository,
                graph_provider=graph,
                store=store,
                clock=authoritative_clock,
            )
        ),
        get_source=GetExactEvaluationActualSource(repository),
        actual_provider=DjangoEvaluationActualEvidenceProvider(repository),
        repository=repository,
    )


__all__ = [
    "DjangoEvaluationActualRuntime",
    "build_django_evaluation_actual_runtime",
]
