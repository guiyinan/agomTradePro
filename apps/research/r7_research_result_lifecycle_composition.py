"""Production composition for R7 result Promotion, retirement, and audit."""

from __future__ import annotations

from dataclasses import dataclass

from apps.research.application.r7_research_result_lifecycle import (
    ApplyR7ResultLifecycle,
    AuditR7ResearchResults,
    ExactR7ResultLifecycleAuthorizationProvider,
)
from apps.research.infrastructure.r7_research_result_lifecycle_repository import (
    DjangoR7ResultLifecycleAuthorizationProvider,
    _DjangoR7ResultLifecycleStore,
)
from apps.research.infrastructure.r7_research_result_repository import (
    DjangoR7ResearchResultClock,
    R7ResearchResultClock,
)


@dataclass(frozen=True)
class DjangoR7ResultLifecycleRuntime:
    """Safe public apply/audit capabilities with no active/current selector."""

    apply: ApplyR7ResultLifecycle
    audit: AuditR7ResearchResults


def build_django_r7_result_lifecycle_runtime(
    *,
    authorization_provider: ExactR7ResultLifecycleAuthorizationProvider,
    using: str = "default",
    clock: R7ResearchResultClock | None = None,
) -> DjangoR7ResultLifecycleRuntime:
    """Build a runtime around an explicit exact Research-owner authorization port."""

    authoritative_clock = clock or DjangoR7ResearchResultClock()
    repository = _DjangoR7ResultLifecycleStore(
        using=using,
        clock=authoritative_clock,
    )
    owner_provider = DjangoR7ResultLifecycleAuthorizationProvider(authorization_provider)
    if owner_provider.unit_of_work_key != repository.unit_of_work_key:
        raise ValueError("R7 result lifecycle runtime requires one shared unit of work")
    return DjangoR7ResultLifecycleRuntime(
        apply=ApplyR7ResultLifecycle(owner_provider, repository),
        audit=AuditR7ResearchResults(repository),
    )


__all__ = [
    "DjangoR7ResultLifecycleRuntime",
    "build_django_r7_result_lifecycle_runtime",
]
