"""Production composition for R7 result Promotion, retirement, and audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.r7_research_result_lifecycle import (
    ApplyR7ResultLifecycle,
    ApplyR7ResultLifecycleCommand,
    AuditR7ResearchResults,
    ExactR7ResultLifecycleAuthorizationProvider,
    R7ResearchResultAuditPage,
    R7ResultLifecycleUnavailable,
)
from apps.research.domain.r7_research_result_lifecycle import R7ResultLifecycleEvent
from apps.research.infrastructure.r7_research_result_lifecycle_repository import (
    DjangoR7ResultLifecycleAuthorizationProvider,
    _DjangoR7ResultLifecycleStore,
)
from apps.research.infrastructure.r7_research_result_repository import (
    DjangoR7ResearchResultClock,
    R7ResearchResultClock,
)


class _UnavailableR7ResultLifecycleApplyFacade:
    """State-free production mutation surface while owner authority is absent."""

    __slots__ = ()

    def execute(
        self,
        command: ApplyR7ResultLifecycleCommand,
    ) -> R7ResultLifecycleEvent:
        """Validate the ID-only command and fail without constructing a store."""

        try:
            if type(command) is not ApplyR7ResultLifecycleCommand:
                raise TypeError
            command.__post_init__()
            command.result_ref.__post_init__()
            command.authorization_ref.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise R7ResultLifecycleUnavailable("R7 result lifecycle command is invalid") from error
        raise R7ResultLifecycleUnavailable(
            "R7 result lifecycle canonical owner provider is unavailable"
        )


class _R7ResultLifecycleAuditFacade:
    """Audit-only surface that retains no repository, clock, or token."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str) -> None:
        self._using = using

    def execute(
        self,
        *,
        as_of: datetime,
        cursor: str | None = None,
        limit: int = 50,
    ) -> R7ResearchResultAuditPage:
        """Construct the private audit repository only for this exact query."""

        return AuditR7ResearchResults(_DjangoR7ResultLifecycleStore(using=self._using)).execute(
            as_of=as_of, cursor=cursor, limit=limit
        )


@dataclass(frozen=True, slots=True)
class DjangoR7ResultLifecycleRuntime:
    """Production-safe inert apply plus a capability-minimal audit query."""

    apply: _UnavailableR7ResultLifecycleApplyFacade
    audit: _R7ResultLifecycleAuditFacade


@dataclass(frozen=True, slots=True)
class _DjangoR7ResultLifecycleTestRuntime:
    """Private injectable runtime used by persistence component tests."""

    apply: ApplyR7ResultLifecycle
    audit: AuditR7ResearchResults


def build_django_r7_result_lifecycle_runtime(
    *,
    using: str = "default",
) -> DjangoR7ResultLifecycleRuntime:
    """Build no writer/store graph while the owner provider is unavailable."""

    return DjangoR7ResultLifecycleRuntime(
        apply=_UnavailableR7ResultLifecycleApplyFacade(),
        audit=_R7ResultLifecycleAuditFacade(using=using),
    )


def _build_django_r7_result_lifecycle_test_runtime(
    *,
    authorization_provider: ExactR7ResultLifecycleAuthorizationProvider,
    using: str = "default",
    clock: R7ResearchResultClock | None = None,
) -> _DjangoR7ResultLifecycleTestRuntime:
    """Build the private injectable runtime used by component tests."""

    authoritative_clock = clock or DjangoR7ResearchResultClock()
    repository = _DjangoR7ResultLifecycleStore(
        using=using,
        clock=authoritative_clock,
    )
    owner_provider = DjangoR7ResultLifecycleAuthorizationProvider(authorization_provider)
    if owner_provider.unit_of_work_key != repository.unit_of_work_key:
        raise ValueError("R7 result lifecycle runtime requires one shared unit of work")
    return _DjangoR7ResultLifecycleTestRuntime(
        apply=ApplyR7ResultLifecycle(owner_provider, repository),
        audit=AuditR7ResearchResults(repository),
    )


__all__ = [
    "DjangoR7ResultLifecycleRuntime",
    "build_django_r7_result_lifecycle_runtime",
]
