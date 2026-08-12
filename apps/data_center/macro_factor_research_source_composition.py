"""Production-safe composition for the canonical R3 PIT source projection."""

from __future__ import annotations

from dataclasses import dataclass

from apps.data_center.application.macro_factor_research_source import (
    ExactMacroFactorResearchSourceDefinitionOwner,
    MacroFactorResearchSourceClock,
    MacroFactorResearchSourceUnavailable,
    RegisterMacroFactorResearchSource,
    RegisterMacroFactorResearchSourceCommand,
)
from apps.data_center.domain.macro_factor_research_source import (
    PersistedMacroFactorResearchSourceDefinition,
)
from apps.data_center.infrastructure.macro_factor_research_source_repository import (
    DjangoMacroFactorResearchSourceClock,
    DjangoMacroFactorResearchSourceDefinitionOwner,
    DjangoMacroFactorResearchSourceReadRepository,
    _DjangoMacroFactorResearchSourceStore,
)


class _UnavailableMacroFactorResearchSourceRegistration:
    """State-free production mutation while no canonical owner is composed."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterMacroFactorResearchSourceCommand,
    ) -> PersistedMacroFactorResearchSourceDefinition:
        """Validate the ID-only command, then fail without a writer graph."""

        try:
            if type(command) is not RegisterMacroFactorResearchSourceCommand:
                raise TypeError("macro-factor source registration command type differs")
            RegisterMacroFactorResearchSourceCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise MacroFactorResearchSourceUnavailable(
                "macro-factor source registration command is malformed"
            ) from error
        raise MacroFactorResearchSourceUnavailable(
            "macro-factor source canonical owner provider is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoMacroFactorResearchSourceRuntime:
    """Public inert mutation plus using-only exact read capabilities."""

    register_source: _UnavailableMacroFactorResearchSourceRegistration
    source_repository: DjangoMacroFactorResearchSourceReadRepository
    projection_provider: DjangoMacroFactorResearchSourceReadRepository


@dataclass(frozen=True, slots=True)
class _DjangoMacroFactorResearchSourceTestRuntime:
    """Private injectable runtime used only for synthetic owner tests."""

    register_source: RegisterMacroFactorResearchSource
    source_repository: DjangoMacroFactorResearchSourceReadRepository
    projection_provider: DjangoMacroFactorResearchSourceReadRepository


def build_django_macro_factor_research_source_runtime(
    *,
    using: str = "default",
) -> DjangoMacroFactorResearchSourceRuntime:
    """Build no mutation/store graph while exposing strict empty-safe reads."""

    repository = DjangoMacroFactorResearchSourceReadRepository(using=using)
    return DjangoMacroFactorResearchSourceRuntime(
        register_source=_UnavailableMacroFactorResearchSourceRegistration(),
        source_repository=repository,
        projection_provider=repository,
    )


def _build_django_macro_factor_research_source_test_runtime(
    *,
    definition_provider: ExactMacroFactorResearchSourceDefinitionOwner,
    using: str = "default",
    clock: MacroFactorResearchSourceClock | None = None,
) -> _DjangoMacroFactorResearchSourceTestRuntime:
    """Compose the private shared-UoW writer used by isolated synthetic tests."""

    repository = DjangoMacroFactorResearchSourceReadRepository(using=using)
    store = _DjangoMacroFactorResearchSourceStore(using=using)
    authoritative_clock = clock or DjangoMacroFactorResearchSourceClock(using=using)
    owner = DjangoMacroFactorResearchSourceDefinitionOwner(
        definition_provider,
        token=store.token,
    )
    keys = {
        repository.unit_of_work_key,
        store.unit_of_work_key,
        owner.unit_of_work_key,
        authoritative_clock.unit_of_work_key,
    }
    if len(keys) != 1:
        raise MacroFactorResearchSourceUnavailable(
            "macro-factor source test runtime requires one shared unit of work"
        )
    return _DjangoMacroFactorResearchSourceTestRuntime(
        register_source=RegisterMacroFactorResearchSource(
            definition_provider=owner,
            store=store,
            clock=authoritative_clock,
        ),
        source_repository=repository,
        projection_provider=repository,
    )


__all__ = [
    "DjangoMacroFactorResearchSourceRuntime",
    "build_django_macro_factor_research_source_runtime",
]
