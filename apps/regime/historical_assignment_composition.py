"""Using-only public and private-test composition for historical assignments."""

from __future__ import annotations

from dataclasses import dataclass

from apps.regime.application.historical_assignment import (
    ExactCanonicalRegimeSourceFactProvider,
    ExactHistoricalRegimeAssignmentDefinitionOwner,
    ExactRegimeArtifactOOSProvider,
    HistoricalRegimeAssignmentClock,
    HistoricalRegimeAssignmentStore,
    HistoricalRegimeAssignmentUnavailable,
    MaterializeHistoricalRegimeAssignment,
    MaterializeHistoricalRegimeAssignmentCommand,
    RegisterHistoricalRegimeAssignmentDefinition,
    RegisterHistoricalRegimeAssignmentDefinitionCommand,
)
from apps.regime.domain.historical_assignment import (
    HistoricalRegimeAssignmentReceipt,
    PersistedHistoricalRegimeAssignmentDefinition,
)
from apps.regime.infrastructure.historical_assignment_repository import (
    DjangoHistoricalRegimeAssignmentClock,
    DjangoHistoricalRegimeAssignmentReadRepository,
    DjangoHistoricalRegimeAssignmentRepository,
)


class UnavailableHistoricalRegimeAssignmentMutation:
    """Stateless public facade that cannot register synthetic owner evidence."""

    __slots__ = ()

    def register_definition(
        self,
        command: RegisterHistoricalRegimeAssignmentDefinitionCommand,
    ) -> PersistedHistoricalRegimeAssignmentDefinition:
        """Reject production registration while no canonical definition owner exists."""

        raise HistoricalRegimeAssignmentUnavailable(
            "canonical historical assignment definition owner is unavailable"
        )

    def materialize(
        self,
        command: MaterializeHistoricalRegimeAssignmentCommand,
    ) -> HistoricalRegimeAssignmentReceipt:
        """Reject production materialization while canonical providers are incomplete."""

        raise HistoricalRegimeAssignmentUnavailable(
            "canonical historical assignment materialization owners are unavailable"
        )


@dataclass(frozen=True, slots=True)
class HistoricalRegimeAssignmentRuntime:
    """Public exact-read runtime without write token, provider, clock, or current surface."""

    mutation: UnavailableHistoricalRegimeAssignmentMutation
    repository: DjangoHistoricalRegimeAssignmentReadRepository


@dataclass(frozen=True, slots=True)
class _HistoricalRegimeAssignmentTestRuntime:
    register_definition: RegisterHistoricalRegimeAssignmentDefinition
    materialize: MaterializeHistoricalRegimeAssignment
    repository: DjangoHistoricalRegimeAssignmentRepository


def build_historical_regime_assignment_runtime(
    *,
    using: str = "default",
) -> HistoricalRegimeAssignmentRuntime:
    """Build the production using-only read path with inert mutation."""

    return HistoricalRegimeAssignmentRuntime(
        mutation=UnavailableHistoricalRegimeAssignmentMutation(),
        repository=DjangoHistoricalRegimeAssignmentReadRepository(using=using),
    )


def _build_historical_regime_assignment_runtime_for_test(
    *,
    using: str = "default",
    definition_provider: ExactHistoricalRegimeAssignmentDefinitionOwner,
    artifact_provider: ExactRegimeArtifactOOSProvider,
    fact_provider: ExactCanonicalRegimeSourceFactProvider,
    store: HistoricalRegimeAssignmentStore | None = None,
    clock: HistoricalRegimeAssignmentClock | None = None,
) -> _HistoricalRegimeAssignmentTestRuntime:
    """Compose injectable owner writers for isolated synthetic tests only."""

    repository = DjangoHistoricalRegimeAssignmentRepository(using=using)
    authoritative_store = store or repository
    authoritative_clock = clock or DjangoHistoricalRegimeAssignmentClock(using=using)
    return _HistoricalRegimeAssignmentTestRuntime(
        register_definition=RegisterHistoricalRegimeAssignmentDefinition(
            definition_provider=definition_provider,
            store=authoritative_store,
            clock=authoritative_clock,
        ),
        materialize=MaterializeHistoricalRegimeAssignment(
            definition_repository=repository,
            artifact_provider=artifact_provider,
            fact_provider=fact_provider,
            store=authoritative_store,
            clock=authoritative_clock,
        ),
        repository=repository,
    )


__all__ = [
    "HistoricalRegimeAssignmentRuntime",
    "UnavailableHistoricalRegimeAssignmentMutation",
    "build_historical_regime_assignment_runtime",
]
