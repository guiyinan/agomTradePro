"""Capability-isolated composition for Research R5 monitoring owner ledgers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.research.application.r5_monitoring_owner_registry import (
    R5MonitoringCalendarDefinitionProvider,
    R5MonitoringOwnerRegistryClock,
    R5MonitoringOwnerRegistryUnavailable,
    R5MonitoringOwnerSourceProvider,
    R5MonitoringPolicyDefinitionProvider,
    RegisterR5MonitoringCalendar,
    RegisterR5MonitoringCalendarCommand,
    RegisterR5MonitoringPolicy,
    RegisterR5MonitoringPolicyCommand,
)
from apps.research.infrastructure.r5_monitoring_owner_repository import (
    DjangoR5MonitoringCalendarProvider,
    DjangoR5MonitoringOwnerClock,
    DjangoR5MonitoringOwnerRegistryRepository,
    DjangoR5MonitoringPolicyProvider,
    _build_r5_monitoring_owner_store,
)


class UnavailableR5MonitoringPolicyRegistrationFacade:
    """Validate identity-only input then deny public owner mutation."""

    __slots__ = ()

    def execute(self, command: RegisterR5MonitoringPolicyCommand) -> NoReturn:
        """Fail closed without retaining a definition, source, clock, or store."""

        try:
            if type(command) is not RegisterR5MonitoringPolicyCommand:
                raise TypeError("R5 monitoring policy command type differs")
            RegisterR5MonitoringPolicyCommand.__post_init__(command)
        except Exception as error:
            raise R5MonitoringOwnerRegistryUnavailable(
                "malformed R5 monitoring policy registration command"
            ) from error
        raise R5MonitoringOwnerRegistryUnavailable(
            "canonical R5 monitoring policy definition/source is unavailable"
        )


class UnavailableR5MonitoringCalendarRegistrationFacade:
    """Validate identity-only input then deny public owner mutation."""

    __slots__ = ()

    def execute(self, command: RegisterR5MonitoringCalendarCommand) -> NoReturn:
        """Fail closed without retaining a definition, source, clock, or store."""

        try:
            if type(command) is not RegisterR5MonitoringCalendarCommand:
                raise TypeError("R5 monitoring calendar command type differs")
            RegisterR5MonitoringCalendarCommand.__post_init__(command)
        except Exception as error:
            raise R5MonitoringOwnerRegistryUnavailable(
                "malformed R5 monitoring calendar registration command"
            ) from error
        raise R5MonitoringOwnerRegistryUnavailable(
            "canonical R5 monitoring calendar definition/source is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR5MonitoringOwnerRegistryRuntime:
    """Public exact reads plus deliberately inert registration surfaces."""

    register_policy: UnavailableR5MonitoringPolicyRegistrationFacade
    register_calendar: UnavailableR5MonitoringCalendarRegistrationFacade
    policy_provider: DjangoR5MonitoringPolicyProvider
    calendar_provider: DjangoR5MonitoringCalendarProvider


@dataclass(frozen=True, slots=True)
class _DjangoR5MonitoringOwnerRegistrationRuntime:
    """Private source-injected runtime proving owner contracts in tests."""

    register_policy: RegisterR5MonitoringPolicy
    register_calendar: RegisterR5MonitoringCalendar
    policy_provider: DjangoR5MonitoringPolicyProvider
    calendar_provider: DjangoR5MonitoringCalendarProvider


def build_django_r5_monitoring_owner_registry_runtime(
    *,
    using: str = "default",
) -> DjangoR5MonitoringOwnerRegistryRuntime:
    """Expose canonical exact reads while retaining no public write authority."""

    repository = DjangoR5MonitoringOwnerRegistryRepository(using=using)
    return DjangoR5MonitoringOwnerRegistryRuntime(
        register_policy=UnavailableR5MonitoringPolicyRegistrationFacade(),
        register_calendar=UnavailableR5MonitoringCalendarRegistrationFacade(),
        policy_provider=DjangoR5MonitoringPolicyProvider(repository),
        calendar_provider=DjangoR5MonitoringCalendarProvider(repository),
    )


def _build_django_r5_monitoring_owner_registration_runtime(
    *,
    policy_definition_provider: R5MonitoringPolicyDefinitionProvider,
    calendar_definition_provider: R5MonitoringCalendarDefinitionProvider,
    policy_source_provider: R5MonitoringOwnerSourceProvider,
    calendar_source_provider: R5MonitoringOwnerSourceProvider,
    clock: R5MonitoringOwnerRegistryClock | None = None,
    using: str = "default",
) -> _DjangoR5MonitoringOwnerRegistrationRuntime:
    """Wire private source-backed registration without exporting its store."""

    trusted_clock = clock or DjangoR5MonitoringOwnerClock(using=using)
    store = _build_r5_monitoring_owner_store(using=using, clock=trusted_clock)
    read_repository = DjangoR5MonitoringOwnerRegistryRepository(
        using=using,
        clock=trusted_clock,
    )
    return _DjangoR5MonitoringOwnerRegistrationRuntime(
        register_policy=RegisterR5MonitoringPolicy(
            definition_provider=policy_definition_provider,
            source_provider=policy_source_provider,
            store=store,
            clock=trusted_clock,
        ),
        register_calendar=RegisterR5MonitoringCalendar(
            definition_provider=calendar_definition_provider,
            source_provider=calendar_source_provider,
            store=store,
            clock=trusted_clock,
        ),
        policy_provider=DjangoR5MonitoringPolicyProvider(read_repository),
        calendar_provider=DjangoR5MonitoringCalendarProvider(read_repository),
    )


__all__ = [
    "DjangoR5MonitoringOwnerRegistryRuntime",
    "UnavailableR5MonitoringCalendarRegistrationFacade",
    "UnavailableR5MonitoringPolicyRegistrationFacade",
    "build_django_r5_monitoring_owner_registry_runtime",
]
