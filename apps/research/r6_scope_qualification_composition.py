"""Capability-isolated composition for the R6 scope-qualification owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.research.application.r6_scope_qualification_registry import (
    R6ScopeQualificationDefinitionProvider,
    R6ScopeQualificationRegistryClock,
    R6ScopeQualificationRegistryUnavailable,
    R6ScopeQualificationSourceProvider,
    RegisterR6ScopeQualificationBinding,
    RegisterR6ScopeQualificationBindingCommand,
)
from apps.research.infrastructure.r6_scope_qualification_repository import (
    DjangoR6ScopeQualificationClock,
    DjangoR6ScopeQualificationRegistryRepository,
    _build_r6_scope_qualification_store,
)


class UnavailableR6ScopeQualificationRegistrationFacade:
    """Stateless production facade that cannot retain binding write authority."""

    __slots__ = ()

    def execute(
        self,
        command: RegisterR6ScopeQualificationBindingCommand,
    ) -> NoReturn:
        """Validate an identity-only command, then stop before database access."""

        try:
            if type(command) is not RegisterR6ScopeQualificationBindingCommand:
                raise TypeError("R6 binding command type differs")
            RegisterR6ScopeQualificationBindingCommand.__post_init__(command)
            rebuilt = RegisterR6ScopeQualificationBindingCommand(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
            )
            if rebuilt != command:
                raise ValueError("R6 binding command differs after replay")
        except (AttributeError, TypeError, ValueError) as error:
            raise R6ScopeQualificationRegistryUnavailable(
                "malformed R6 scope-qualification registration command"
            ) from error
        raise R6ScopeQualificationRegistryUnavailable(
            "canonical R6 binding definition/source is unavailable"
        )


@dataclass(frozen=True, slots=True)
class DjangoR6ScopeQualificationRegistryRuntime:
    """Public exact reads plus deliberately inert registration."""

    register: UnavailableR6ScopeQualificationRegistrationFacade
    owner_provider: DjangoR6ScopeQualificationRegistryRepository


@dataclass(frozen=True, slots=True)
class _DjangoR6ScopeQualificationRegistrationRuntime:
    """Private source-backed registration graph for owner tests."""

    register: RegisterR6ScopeQualificationBinding
    owner_provider: DjangoR6ScopeQualificationRegistryRepository


def build_django_r6_scope_qualification_registry_runtime(
    *, using: str = "default"
) -> DjangoR6ScopeQualificationRegistryRuntime:
    """Expose exact owner reads without a source, clock, store, or token."""

    return DjangoR6ScopeQualificationRegistryRuntime(
        register=UnavailableR6ScopeQualificationRegistrationFacade(),
        owner_provider=DjangoR6ScopeQualificationRegistryRepository(using=using),
    )


def _build_django_r6_scope_qualification_registration_runtime(
    *,
    definition_provider: R6ScopeQualificationDefinitionProvider,
    source_provider: R6ScopeQualificationSourceProvider,
    clock: R6ScopeQualificationRegistryClock | None = None,
    using: str = "default",
) -> _DjangoR6ScopeQualificationRegistrationRuntime:
    """Wire private registration without exporting its store or token."""

    trusted_clock = clock or DjangoR6ScopeQualificationClock(using=using)
    return _DjangoR6ScopeQualificationRegistrationRuntime(
        register=RegisterR6ScopeQualificationBinding(
            definition_provider=definition_provider,
            source_provider=source_provider,
            store=_build_r6_scope_qualification_store(
                using=using,
                clock=trusted_clock,
            ),
            clock=trusted_clock,
        ),
        owner_provider=DjangoR6ScopeQualificationRegistryRepository(using=using),
    )


__all__ = [
    "DjangoR6ScopeQualificationRegistryRuntime",
    "UnavailableR6ScopeQualificationRegistrationFacade",
    "build_django_r6_scope_qualification_registry_runtime",
]
