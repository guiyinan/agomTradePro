"""Fail-closed production composition for R6 activation persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from apps.research.application.state_model_activation import (
    ApplyR6ActivationCommand,
    R6ActivationClock,
    R6ActivationUnavailable,
)
from apps.research.application.state_model_activation_persistence import (
    AuditR6ActivationEventsCommand,
    GetExactR6ActivationAuthorization,
    GetExactR6ActivationEvent,
)
from apps.research.domain.state_model_activation import R6ActivationScopeRef
from apps.research.infrastructure.state_model_activation_repository import (
    DjangoR6ActivationClock,
    DjangoR6ActivationRepository,
)


class UnavailableR6ActivationApplyFacade:
    """Expose no write capability until every canonical owner is wired."""

    __slots__ = ()

    def execute(self, command: ApplyR6ActivationCommand) -> NoReturn:
        """Revalidate the ID-only command and fail before any persistence access."""

        try:
            if type(command) is not ApplyR6ActivationCommand:
                raise TypeError("R6 activation command type differs")
            ApplyR6ActivationCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R6ActivationUnavailable("R6 activation command is malformed") from error
        raise R6ActivationUnavailable("canonical R6 activation owner providers are unavailable")


class UnavailableR6ActiveStateModelFacade:
    """Return no active projection while production owner wiring is absent."""

    __slots__ = ()

    def get_active(
        self,
        *,
        scope_ref: R6ActivationScopeRef,
        as_of: datetime,
    ) -> None:
        """Validate lookup shape without retaining a repository or owner capability."""

        try:
            if type(scope_ref) is not R6ActivationScopeRef:
                raise TypeError("R6 activation scope type differs")
            scope_ref.__post_init__()
            if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
                raise ValueError("R6 activation as_of must be timezone-aware")
        except (AttributeError, TypeError, ValueError) as error:
            raise R6ActivationUnavailable("R6 activation query is malformed") from error
        return None


class UnavailableR6ActivationAuditFacade:
    """Keep snapshot-writing audit capability outside the public runtime object graph."""

    __slots__ = ()

    def execute(self, command: AuditR6ActivationEventsCommand) -> NoReturn:
        """Validate the query and fail closed until an internal audit service is wired."""

        try:
            if type(command) is not AuditR6ActivationEventsCommand:
                raise TypeError("R6 activation audit command type differs")
            AuditR6ActivationEventsCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R6ActivationUnavailable("R6 activation audit query is malformed") from error
        raise R6ActivationUnavailable(
            "R6 activation audit snapshot writer is unavailable in production composition"
        )


@dataclass(frozen=True)
class DjangoR6ActivationRuntime:
    """Read-safe R6 façade with inert mutation and snapshot-writing surfaces."""

    apply: UnavailableR6ActivationApplyFacade
    get_active: UnavailableR6ActiveStateModelFacade
    get_exact_authorization: GetExactR6ActivationAuthorization
    get_exact_event: GetExactR6ActivationEvent
    audit: UnavailableR6ActivationAuditFacade


def build_django_r6_activation_runtime(
    *,
    using: str = "default",
    clock: R6ActivationClock | None = None,
) -> DjangoR6ActivationRuntime:
    """Build production reads without retaining any activation write token or store."""

    read_repository = DjangoR6ActivationRepository(
        using=using,
        clock=clock or DjangoR6ActivationClock(),
    )
    return DjangoR6ActivationRuntime(
        apply=UnavailableR6ActivationApplyFacade(),
        get_active=UnavailableR6ActiveStateModelFacade(),
        get_exact_authorization=GetExactR6ActivationAuthorization(read_repository),
        get_exact_event=GetExactR6ActivationEvent(read_repository),
        audit=UnavailableR6ActivationAuditFacade(),
    )


__all__ = [
    "DjangoR6ActivationRuntime",
    "UnavailableR6ActivationApplyFacade",
    "UnavailableR6ActivationAuditFacade",
    "UnavailableR6ActiveStateModelFacade",
    "build_django_r6_activation_runtime",
]
