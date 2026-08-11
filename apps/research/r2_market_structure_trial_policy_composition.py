"""Production-inert composition for the Research R2 trial-policy registry."""

from __future__ import annotations

from dataclasses import dataclass

from apps.research.application.r2_market_structure_trial_policy_registry import (
    ExactR2TrialPolicyDefinitionProvider,
    R2TrialPolicyRegistryClock,
    R2TrialPolicyRegistryUnavailable,
    RegisterR2MarketStructureTrialPolicy,
    RegisterR2MarketStructureTrialPolicyCommand,
)
from apps.research.domain.r2_market_structure_trial_policy_registry import (
    PersistedR2MarketStructureTrialPolicy,
)
from apps.research.infrastructure.r2_market_structure_trial_policy_repository import (
    DjangoExactR2TrialPolicyProvider,
    DjangoR2TrialPolicyDefinitionProvider,
    DjangoR2TrialPolicyRegistryClock,
    DjangoR2TrialPolicyRegistryRepository,
    _DjangoR2TrialPolicyRegistryStore,
)


class _UnavailableR2TrialPolicyRegistrationFacade:
    """State-free public writer while no canonical definition owner is composed."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterR2MarketStructureTrialPolicyCommand,
    ) -> PersistedR2MarketStructureTrialPolicy:
        """Validate the ID-only selector, then fail without constructing a store."""

        try:
            if type(command) is not RegisterR2MarketStructureTrialPolicyCommand:
                raise TypeError("R2 policy registration command type differs")
            RegisterR2MarketStructureTrialPolicyCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R2TrialPolicyRegistryUnavailable(
                "R2 trial-policy registration command is invalid"
            ) from error
        raise R2TrialPolicyRegistryUnavailable(
            "R2 trial-policy canonical definition provider is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR2TrialPolicyRegistryRuntime:
    """Inert production registration plus exact read-only provider capability."""

    register: _UnavailableR2TrialPolicyRegistrationFacade
    provider: DjangoExactR2TrialPolicyProvider


@dataclass(frozen=True, slots=True)
class _DjangoR2TrialPolicyRegistryTestRuntime:
    """Private injectable runtime reserved for component tests."""

    register: RegisterR2MarketStructureTrialPolicy
    provider: DjangoExactR2TrialPolicyProvider
    repository: DjangoR2TrialPolicyRegistryRepository


def build_django_r2_trial_policy_registry_runtime(
    *,
    using: str = "default",
) -> DjangoR2TrialPolicyRegistryRuntime:
    """Build a public object graph with no writer store or owner dependency."""

    repository = DjangoR2TrialPolicyRegistryRepository(using=using)
    return DjangoR2TrialPolicyRegistryRuntime(
        register=_UnavailableR2TrialPolicyRegistrationFacade(),
        provider=DjangoExactR2TrialPolicyProvider(repository),
    )


def _build_django_r2_trial_policy_registry_test_runtime(
    *,
    definition_provider: ExactR2TrialPolicyDefinitionProvider,
    using: str = "default",
    clock: R2TrialPolicyRegistryClock | None = None,
) -> _DjangoR2TrialPolicyRegistryTestRuntime:
    """Build the private same-UoW writer graph for synthetic component tests."""

    trusted_clock = clock or DjangoR2TrialPolicyRegistryClock(using=using)
    repository = DjangoR2TrialPolicyRegistryRepository(
        using=using,
        clock=trusted_clock,
    )
    owner = DjangoR2TrialPolicyDefinitionProvider(definition_provider)
    store = _DjangoR2TrialPolicyRegistryStore(using=using)
    keys = {
        owner.unit_of_work_key,
        store.unit_of_work_key,
        trusted_clock.unit_of_work_key,
        repository.unit_of_work_key,
    }
    if len(keys) != 1:
        raise R2TrialPolicyRegistryUnavailable(
            "R2 trial-policy runtime requires one shared unit of work"
        )
    return _DjangoR2TrialPolicyRegistryTestRuntime(
        register=RegisterR2MarketStructureTrialPolicy(
            definition_provider=owner,
            store=store,
            clock=trusted_clock,
        ),
        provider=DjangoExactR2TrialPolicyProvider(repository),
        repository=repository,
    )


__all__ = [
    "DjangoR2TrialPolicyRegistryRuntime",
    "build_django_r2_trial_policy_registry_runtime",
]
