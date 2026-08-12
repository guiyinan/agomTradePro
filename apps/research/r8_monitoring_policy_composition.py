"""Capability-isolated composition for the Research R8 monitoring policy owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.research.application.r8_monitoring_policy_registry import (
    R8MonitoringPolicyDefinitionProvider,
    R8MonitoringPolicyRegistryClock,
    R8MonitoringPolicyRegistryUnavailable,
    R8MonitoringPolicySourceProvider,
    RegisterR8MonitoringPolicy,
    RegisterR8MonitoringPolicyCommand,
)
from apps.research.infrastructure.r8_monitoring_policy_repository import (
    DjangoR8MonitoringPolicyClock,
    DjangoR8MonitoringPolicyRepository,
    _build_r8_monitoring_policy_store,
)


class UnavailableR8MonitoringPolicyRegistrationFacade:
    """Stateless production facade that cannot retain policy write authority."""

    __slots__ = ()

    def execute(self, command: RegisterR8MonitoringPolicyCommand) -> NoReturn:
        """Validate an exact identity command and stop before database access."""

        try:
            if type(command) is not RegisterR8MonitoringPolicyCommand:
                raise TypeError("R8 monitoring policy command type differs")
            RegisterR8MonitoringPolicyCommand.__post_init__(command)
            rebuilt = RegisterR8MonitoringPolicyCommand(
                policy_id=command.policy_id,
                policy_version=command.policy_version,
            )
            if rebuilt != command:
                raise ValueError("R8 monitoring policy command differs after replay")
        except (AttributeError, TypeError, ValueError) as error:
            raise R8MonitoringPolicyRegistryUnavailable(
                "malformed R8 monitoring policy registration command"
            ) from error
        raise R8MonitoringPolicyRegistryUnavailable(
            "canonical R8 monitoring policy definition/source is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR8MonitoringPolicyRegistryRuntime:
    """Public exact policy reads plus deliberately inert registration."""

    register: UnavailableR8MonitoringPolicyRegistrationFacade
    policy_provider: DjangoR8MonitoringPolicyRepository


@dataclass(frozen=True, slots=True)
class _DjangoR8MonitoringPolicyRegistrationRuntime:
    """Private source-backed registration graph used by owner component tests."""

    register: RegisterR8MonitoringPolicy
    policy_provider: DjangoR8MonitoringPolicyRepository


def build_django_r8_monitoring_policy_registry_runtime(
    *, using: str = "default"
) -> DjangoR8MonitoringPolicyRegistryRuntime:
    """Expose exact policy reads without a source, clock, store, or write token."""

    return DjangoR8MonitoringPolicyRegistryRuntime(
        register=UnavailableR8MonitoringPolicyRegistrationFacade(),
        policy_provider=DjangoR8MonitoringPolicyRepository(using=using),
    )


def _build_django_r8_monitoring_policy_registration_runtime(
    *,
    definition_provider: R8MonitoringPolicyDefinitionProvider,
    source_provider: R8MonitoringPolicySourceProvider,
    clock: R8MonitoringPolicyRegistryClock | None = None,
    using: str = "default",
) -> _DjangoR8MonitoringPolicyRegistrationRuntime:
    """Wire the private owner source graph without exporting its store or token."""

    trusted_clock = clock or DjangoR8MonitoringPolicyClock(using=using)
    return _DjangoR8MonitoringPolicyRegistrationRuntime(
        register=RegisterR8MonitoringPolicy(
            definition_provider=definition_provider,
            source_provider=source_provider,
            store=_build_r8_monitoring_policy_store(
                using=using,
                clock=trusted_clock,
            ),
            clock=trusted_clock,
        ),
        policy_provider=DjangoR8MonitoringPolicyRepository(using=using),
    )


__all__ = [
    "DjangoR8MonitoringPolicyRegistryRuntime",
    "UnavailableR8MonitoringPolicyRegistrationFacade",
    "build_django_r8_monitoring_policy_registry_runtime",
]
