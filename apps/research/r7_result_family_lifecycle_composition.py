"""Fail-closed production composition for R7 family lifecycle persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.research.application.r7_result_family_lifecycle import (
    ApplyR7FamilyLifecycle,
    ApplyR7FamilyLifecycleCommand,
    ExactR7FamilyAuthorizationProvider,
    ExactR7FamilyResultProvider,
    ExactR7LocalLifecycleProvider,
    R7FamilyLifecycleUnavailable,
)
from apps.research.application.r7_result_family_lifecycle_persistence import (
    AuditR7FamilyLifecycle,
    AuditR7FamilyLifecycleCommand,
    GetExactR7FamilyAuthorization,
    GetExactR7FamilyEvent,
)
from apps.research.infrastructure.r7_result_family_lifecycle_repository import (
    DjangoR7FamilyLifecycleRepository,
    R7FamilyLifecycleClock,
    _DjangoR7FamilyLifecycleStore,
)


class UnavailableR7FamilyLifecycleApplyFacade:
    """Expose no mutation capability until all canonical owners are wired."""

    __slots__ = ()

    def execute(self, command: ApplyR7FamilyLifecycleCommand) -> NoReturn:
        """Validate the ID-only command, then fail before persistence access."""

        try:
            if type(command) is not ApplyR7FamilyLifecycleCommand:
                raise TypeError("R7 family command type differs")
            ApplyR7FamilyLifecycleCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R7FamilyLifecycleUnavailable("R7 family command is malformed") from error
        raise R7FamilyLifecycleUnavailable(
            "canonical R7 family owner and authorization providers are unavailable"
        )


class UnavailableR7FamilyLifecycleAuditFacade:
    """Keep snapshot writes outside the public runtime object graph."""

    __slots__ = ()

    def execute(self, command: AuditR7FamilyLifecycleCommand) -> NoReturn:
        """Validate the query, then fail before any snapshot writer is reachable."""

        try:
            if type(command) is not AuditR7FamilyLifecycleCommand:
                raise TypeError("R7 family audit command type differs")
            AuditR7FamilyLifecycleCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R7FamilyLifecycleUnavailable("R7 family audit command is malformed") from error
        raise R7FamilyLifecycleUnavailable(
            "R7 family audit snapshot writer is unavailable in production composition"
        )


@dataclass(frozen=True)
class DjangoR7FamilyLifecycleRuntime:
    """Public exact reads with inert mutation and snapshot-writing surfaces."""

    apply: UnavailableR7FamilyLifecycleApplyFacade
    get_exact_authorization: GetExactR7FamilyAuthorization
    get_exact_event: GetExactR7FamilyEvent
    audit: UnavailableR7FamilyLifecycleAuditFacade


@dataclass(frozen=True)
class _DjangoR7FamilyLifecycleTestComponent:
    apply: ApplyR7FamilyLifecycle
    get_exact_authorization: GetExactR7FamilyAuthorization
    get_exact_event: GetExactR7FamilyEvent
    audit: AuditR7FamilyLifecycle


def build_django_r7_family_lifecycle_runtime(
    *,
    using: str = "default",
) -> DjangoR7FamilyLifecycleRuntime:
    """Build production reads without retaining a writer, token, or owner provider."""

    read_repository = DjangoR7FamilyLifecycleRepository(using=using)
    return DjangoR7FamilyLifecycleRuntime(
        apply=UnavailableR7FamilyLifecycleApplyFacade(),
        get_exact_authorization=GetExactR7FamilyAuthorization(read_repository),
        get_exact_event=GetExactR7FamilyEvent(read_repository),
        audit=UnavailableR7FamilyLifecycleAuditFacade(),
    )


def _build_django_r7_family_lifecycle_component_for_tests(
    *,
    result_provider: ExactR7FamilyResultProvider,
    local_lifecycle_provider: ExactR7LocalLifecycleProvider,
    authorization_provider: ExactR7FamilyAuthorizationProvider,
    using: str,
    clock: R7FamilyLifecycleClock,
) -> _DjangoR7FamilyLifecycleTestComponent:
    """Assemble the concrete success path only for isolated component tests."""

    store = _DjangoR7FamilyLifecycleStore(using=using, clock=clock)
    return _DjangoR7FamilyLifecycleTestComponent(
        apply=ApplyR7FamilyLifecycle(
            result_provider=result_provider,
            local_lifecycle_provider=local_lifecycle_provider,
            authorization_provider=authorization_provider,
            repository=store,
        ),
        get_exact_authorization=GetExactR7FamilyAuthorization(store),
        get_exact_event=GetExactR7FamilyEvent(store),
        audit=AuditR7FamilyLifecycle(store),
    )


__all__ = [
    "DjangoR7FamilyLifecycleRuntime",
    "UnavailableR7FamilyLifecycleApplyFacade",
    "UnavailableR7FamilyLifecycleAuditFacade",
    "build_django_r7_family_lifecycle_runtime",
]
