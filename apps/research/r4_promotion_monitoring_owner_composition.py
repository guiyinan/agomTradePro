"""Capability-isolated composition for Research R4 monitoring owner ledgers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.research.application.r4_promotion_monitoring_owner_registry import (
    R4MonitoringCalendarDefinitionProvider,
    R4MonitoringOwnerRegistryClock,
    R4MonitoringOwnerRegistryUnavailable,
    R4MonitoringOwnerSourceProvider,
    R4MonitoringPolicyDefinitionProvider,
    RegisterR4MonitoringCalendar,
    RegisterR4MonitoringCalendarCommand,
    RegisterR4MonitoringPolicy,
    RegisterR4MonitoringPolicyCommand,
)
from apps.research.infrastructure.r4_promotion_monitoring_owner_repository import (
    DjangoR4MonitoringCalendarProvider,
    DjangoR4MonitoringOwnerClock,
    DjangoR4MonitoringOwnerRegistryRepository,
    DjangoR4MonitoringPolicyProvider,
    _build_r4_monitoring_owner_store,
)


class UnavailableR4MonitoringPolicyRegistrationFacade:
    """Validate ID-only input then deny writes without canonical source owners."""

    __slots__ = ()

    def execute(self, command: RegisterR4MonitoringPolicyCommand) -> NoReturn:
        """Fail closed without constructing or persisting a policy."""

        try:
            if type(command) is not RegisterR4MonitoringPolicyCommand:
                raise TypeError("policy command type is invalid")
            RegisterR4MonitoringPolicyCommand.__post_init__(command)
        except Exception as error:
            raise R4MonitoringOwnerRegistryUnavailable(
                "malformed policy registration command"
            ) from error
        raise R4MonitoringOwnerRegistryUnavailable(
            "canonical policy definition/source provider is unavailable"
        )


class UnavailableR4MonitoringCalendarRegistrationFacade:
    """Validate ID-only input then deny writes without canonical source owners."""

    __slots__ = ()

    def execute(self, command: RegisterR4MonitoringCalendarCommand) -> NoReturn:
        """Fail closed without constructing or persisting a calendar."""

        try:
            if type(command) is not RegisterR4MonitoringCalendarCommand:
                raise TypeError("calendar command type is invalid")
            RegisterR4MonitoringCalendarCommand.__post_init__(command)
        except Exception as error:
            raise R4MonitoringOwnerRegistryUnavailable(
                "malformed calendar registration command"
            ) from error
        raise R4MonitoringOwnerRegistryUnavailable(
            "canonical calendar definition/source provider is unavailable"
        )


@dataclass(frozen=True)
class DjangoR4MonitoringOwnerRegistryRuntime:
    """Public exact reads plus deliberately inert owner registration surfaces."""

    register_policy: UnavailableR4MonitoringPolicyRegistrationFacade
    register_calendar: UnavailableR4MonitoringCalendarRegistrationFacade
    policy_provider: DjangoR4MonitoringPolicyProvider
    calendar_provider: DjangoR4MonitoringCalendarProvider


@dataclass(frozen=True)
class _DjangoR4MonitoringOwnerRegistrationRuntime:
    """Private source-injected runtime used only by owner contract tests."""

    register_policy: RegisterR4MonitoringPolicy
    register_calendar: RegisterR4MonitoringCalendar
    policy_provider: DjangoR4MonitoringPolicyProvider
    calendar_provider: DjangoR4MonitoringCalendarProvider


def build_django_r4_monitoring_owner_registry_runtime(
    *, using: str = "default"
) -> DjangoR4MonitoringOwnerRegistryRuntime:
    """Expose canonical exact reads while keeping public mutations inert."""

    repository = DjangoR4MonitoringOwnerRegistryRepository(using=using)
    return DjangoR4MonitoringOwnerRegistryRuntime(
        register_policy=UnavailableR4MonitoringPolicyRegistrationFacade(),
        register_calendar=UnavailableR4MonitoringCalendarRegistrationFacade(),
        policy_provider=DjangoR4MonitoringPolicyProvider(repository),
        calendar_provider=DjangoR4MonitoringCalendarProvider(repository),
    )


def _build_django_r4_monitoring_owner_registration_runtime(
    *,
    policy_definition_provider: R4MonitoringPolicyDefinitionProvider,
    calendar_definition_provider: R4MonitoringCalendarDefinitionProvider,
    policy_source_provider: R4MonitoringOwnerSourceProvider,
    calendar_source_provider: R4MonitoringOwnerSourceProvider,
    clock: R4MonitoringOwnerRegistryClock | None = None,
    using: str = "default",
) -> _DjangoR4MonitoringOwnerRegistrationRuntime:
    """Wire private source-backed registration without exporting its store."""

    store = _build_r4_monitoring_owner_store(using=using)
    read_repository = DjangoR4MonitoringOwnerRegistryRepository(using=using)
    trusted_clock = clock or DjangoR4MonitoringOwnerClock(using=using)
    return _DjangoR4MonitoringOwnerRegistrationRuntime(
        register_policy=RegisterR4MonitoringPolicy(
            definition_provider=policy_definition_provider,
            source_provider=policy_source_provider,
            store=store,
            clock=trusted_clock,
        ),
        register_calendar=RegisterR4MonitoringCalendar(
            definition_provider=calendar_definition_provider,
            source_provider=calendar_source_provider,
            store=store,
            clock=trusted_clock,
        ),
        policy_provider=DjangoR4MonitoringPolicyProvider(read_repository),
        calendar_provider=DjangoR4MonitoringCalendarProvider(read_repository),
    )


__all__ = [
    "DjangoR4MonitoringOwnerRegistryRuntime",
    "UnavailableR4MonitoringCalendarRegistrationFacade",
    "UnavailableR4MonitoringPolicyRegistrationFacade",
    "build_django_r4_monitoring_owner_registry_runtime",
]
